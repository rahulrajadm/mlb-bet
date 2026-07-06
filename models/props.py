"""
Generates player prop predictions for today's PrizePicks/Underdog lines.

Five-layer prediction:
1. Season average per-game rate (from batter/pitcher profiles)
2. Recent form blend (last 14 days weighted 55%, season 45%)
3. Opposing starter matchup adjustment (pitcher K-rate vs league avg)
4. Park factor adjustment (venue run environment)
5. Platoon adjustment (batter hand vs pitcher hand)

Then Poisson P(> line), with the winning side's edge measured against the
platform break-even (~0.577 for a 2-pick 3x) — not 0.50.

Only "standard" odds_type lines are priced: goblins/demons change the payout
and are More-only, so our EV math doesn't apply to them.

Pitcher props are strikeouts only. Other pitcher stats (ER, hits allowed,
pitch count, outs) have no per-game rate model and are deliberately skipped
— see UNMODELED_STATS.

Filter diagnostics print to stderr as `[props] lines=... passed=...`;
check them after any change to stat mapping or filters.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
import joblib
from scipy.stats import poisson
from utils.db import get_conn
from utils.dates import today_str, local_day_utc_bounds
from utils.names import clean_name, normalize_name, make_lookup
from pipeline.team_names import to_full_name
from pipeline.lineups import get_confirmed_players, lineups_are_posted
from pipeline.pitcher_stats import make_pitcher_lookup, LEAGUE_DEFAULT
from pipeline.park_factors import apply_park_factor
from pipeline.handedness import load_handedness_from_db, get_platoon_adj
from pipeline.pitcher_arsenal import load_arsenal_from_db, make_arsenal_lookup
from analysis.ev import breakeven_prob

MODELS_DIR = os.path.join(os.path.dirname(__file__), "../data/models")

# Blend weights: recent form vs season average
RECENT_WEIGHT = 0.55
SEASON_WEIGHT = 0.45

# How much pitcher matchup shifts batter rates (dampened — not full adjustment)
MATCHUP_STRENGTH = 0.40

# Stats where pitcher matchup adjustment applies (batter stats)
PITCHER_ADJ_BATTER_STATS = {
    "hits_pg", "hr_pg", "rbi_pg", "runs_pg", "tb_pg",
    "h_r_rbi_pg", "singles_pg", "doubles_pg", "so_pg",
}

# Pitcher props we model: strikeouts only ("Strikeouts" is Underdog's name)
PITCHER_PROP_STATS = {"Pitcher Strikeouts", "Strikeouts"}

# Maps platform stat names → internal rate column.
# A new stat must also be added to analysis/risk.py variance sets and, if
# rare-event, NO_LESS_AT_HALF in picks/engine.py (see CLAUDE.md).
STAT_MAP = {
    "Pitcher Strikeouts":  "k_pg",
    "Strikeouts":          "k_pg",     # Underdog pitcher Ks
    "Hitter Strikeouts":   "so_pg",
    "Batter Strikeouts":   "so_pg",
    "Hits":                "hits_pg",
    "Home Runs":           "hr_pg",
    "RBIs":                "rbi_pg",
    "Runs":                "runs_pg",
    "Total Bases":         "tb_pg",
    "Hits+Runs+RBIs":      "h_r_rbi_pg",
    "Hits + Runs + RBIs":  "h_r_rbi_pg",
    "Singles":             "singles_pg",
    "Doubles":             "doubles_pg",
    "Walks":               "bb_pg",
    "Batter Walks":        "bb_pg",
    "Stolen Bases":        "sb_pg",
}

# Canonical display name per internal rate column — cross-platform grouping
# (PP "Walks" and UD "Batter Walks" are the same prop).
STAT_DISPLAY = {
    "k_pg":       "Pitcher Strikeouts",
    "so_pg":      "Batter Strikeouts",
    "hits_pg":    "Hits",
    "hr_pg":      "Home Runs",
    "rbi_pg":     "RBIs",
    "runs_pg":    "Runs",
    "tb_pg":      "Total Bases",
    "h_r_rbi_pg": "Hits + Runs + RBIs",
    "singles_pg": "Singles",
    "doubles_pg": "Doubles",
    "bb_pg":      "Walks",
    "sb_pg":      "Stolen Bases",
}

# Lines we knowingly don't model: continuous/scored stats with no rate column
# (fantasy), pitcher stats with no per-game model, multi-player combos, and
# partial-inning exotics. Skipped with a counter, not silently.
UNMODELED_STATS = {
    "Hitter Fantasy Score", "Pitcher Fantasy Score", "Fantasy Points",
    "Earned Runs Allowed", "Hits Allowed", "Walks Allowed",
    "Pitches Thrown", "Pitching Outs",
    "Pitcher Strikeouts (Combo)",
    "1st Inning Walks Allowed", "1st Inning Runs Allowed",
    "1st Inn. Pitch Count", "1st Inn. Batters Faced",
    "1st Inn. Hits Allowed", "1st Inn. Runs Allowed", "1st Inn. Strikeouts",
    "Plate Appearances", "Triples",
}


def load_profiles():
    batter_path  = os.path.join(MODELS_DIR, "batter_profiles.pkl")
    pitcher_path = os.path.join(MODELS_DIR, "pitcher_profiles.pkl")
    return joblib.load(batter_path), joblib.load(pitcher_path)


def load_recent_form() -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = get_conn()
    try:
        batting  = pd.read_sql("SELECT * FROM recent_batting",  conn)
    except Exception:
        batting  = pd.DataFrame()
    try:
        pitching = pd.read_sql("SELECT * FROM recent_pitching", conn)
    except Exception:
        pitching = pd.DataFrame()
    conn.close()
    return batting, pitching


def load_pitcher_season_stats() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql("SELECT * FROM pitcher_season_stats", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def load_games_today() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM games WHERE date = ?", conn, params=(today_str(),))
    conn.close()
    return df


# Maps internal stat col → recent_batting column name. A new batter stat
# needs an entry here too, or it silently blends season-only.
RECENT_COL_MAP = {
    "hits_pg":    "H_pg",
    "hr_pg":      "HR_pg",
    "rbi_pg":     "RBI_pg",
    "runs_pg":    "R_pg",
    "bb_pg":      "BB_pg",
    "so_pg":      "SO_pg",
    "sb_pg":      "SB_pg",
    "doubles_pg": "2B_pg",
    "singles_pg": "singles_pg",
    "tb_pg":      "tb_pg",
    "h_r_rbi_pg": "h_r_rbi_pg",
}


def _rate_from_row(row, col) -> float | None:
    if row is None or col not in row:
        return None
    val = row[col]
    if pd.notna(val) and val >= 0:
        return float(val)
    return None


def prob_more_less(expected_rate: float, line: float) -> tuple[float, float]:
    """
    Win probabilities for More/Less on a Poisson stat.
    x.5 lines: P(X ≥ ceil(line)) vs the complement.
    Whole-number lines push at X == line (refund): win probabilities are
    conditioned on no push.
    """
    if float(line).is_integer():
        line_i = int(line)
        p_more = 1.0 - poisson.cdf(line_i, mu=expected_rate)
        p_less = poisson.cdf(line_i - 1, mu=expected_rate)
        denom = p_more + p_less
        if denom <= 0:
            return 0.5, 0.5
        return p_more / denom, p_less / denom
    threshold = int(np.ceil(line))
    p_more = 1.0 - poisson.cdf(threshold - 1, mu=expected_rate)
    return p_more, 1.0 - p_more


def predict_props(
    platform: str = None,
    # Optional pre-fetched data for cloud/in-memory mode (skips SQLite reads)
    lines_data: list[dict] | None = None,
    games_data: list[dict] | None = None,
    recent_batting_data: pd.DataFrame | None = None,
    recent_pitching_data: pd.DataFrame | None = None,
    pitcher_stats_data: pd.DataFrame | None = None,
    handedness_data: dict | None = None,
    confirmed_players_data: set | None = None,
    arsenal_data: pd.DataFrame | None = None,
) -> list[dict]:
    batters, pitchers = load_profiles()

    # Use pre-fetched data if provided, otherwise read from SQLite
    if recent_batting_data is not None and recent_pitching_data is not None:
        recent_batting, recent_pitching = recent_batting_data, recent_pitching_data
    else:
        recent_batting, recent_pitching = load_recent_form()

    pitcher_stats = pitcher_stats_data if pitcher_stats_data is not None else load_pitcher_season_stats()
    handedness_db = handedness_data if handedness_data is not None else load_handedness_from_db()
    arsenal_db    = arsenal_data if arsenal_data is not None else load_arsenal_from_db()

    if games_data is not None:
        games = pd.DataFrame(games_data)
    else:
        games = load_games_today()

    # Lineup filter (batters only — pitcher props come from probable starters)
    if confirmed_players_data is not None:
        lineups_posted    = len(confirmed_players_data) > 0
        confirmed_players = confirmed_players_data
    else:
        lineups_posted    = lineups_are_posted()
        confirmed_players = get_confirmed_players() if lineups_posted else set()
    confirmed_norm = {normalize_name(n) for n in confirmed_players}

    # Per-team game context keyed by MLB full team name
    team_context: dict[str, dict] = {}
    if not games.empty:
        for _, g in games.iterrows():
            home, away = g.get("home_team", ""), g.get("away_team", "")
            venue = g.get("venue", "")
            team_context[home] = {"opp_starter": g.get("away_starter", ""), "venue": venue}
            team_context[away] = {"opp_starter": g.get("home_starter", ""), "venue": venue}

    # Name-safe lookups, built once
    batter_lookup     = make_lookup(batters)
    recent_bat_lookup = make_lookup(recent_batting)
    pitcher_lookup    = make_pitcher_lookup(pitcher_stats)
    arsenal_lookup    = make_arsenal_lookup(arsenal_db)
    handedness_norm   = {normalize_name(k): v for k, v in handedness_db.items()}

    # Build lines DataFrame from pre-fetched data or SQLite
    if lines_data is not None:
        lines = pd.DataFrame(lines_data)
        if platform:
            lines = lines[lines["platform"] == platform]
    else:
        conn = get_conn()
        start_utc, end_utc = local_day_utc_bounds()
        query = "SELECT * FROM prop_lines WHERE fetched_at >= ? AND fetched_at < ?"
        params = [start_utc, end_utc]
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        lines = pd.read_sql(query, conn, params=params)
        conn.close()

    if lines.empty:
        print("[props] no lines for today", file=sys.stderr)
        return []

    if "odds_type" not in lines.columns:
        lines["odds_type"] = "standard"
    lines["odds_type"] = lines["odds_type"].fillna("standard")

    # Latest line per platform+player+stat+odds_type
    lines = lines.sort_values("fetched_at", ascending=False).drop_duplicates(
        subset=["platform", "player_name", "stat_type", "odds_type"]
    )

    counts = {"lines": len(lines), "non_standard": 0, "unmodeled": 0, "no_stat": 0,
              "not_confirmed": 0, "no_profile": 0, "no_edge": 0, "passed": 0}
    unknown_stat_types: set[str] = set()

    predictions = []
    for _, row in lines.iterrows():
        stat_type = row["stat_type"]
        if row.get("odds_type", "standard") != "standard":
            counts["non_standard"] += 1
            continue
        if stat_type in UNMODELED_STATS:
            counts["unmodeled"] += 1
            continue
        stat_col = STAT_MAP.get(stat_type)
        if stat_col is None or row["line"] is None:
            counts["no_stat"] += 1
            unknown_stat_types.add(stat_type)
            continue

        player_name = clean_name(row["player_name"])
        line        = float(row["line"])
        is_pitcher_prop = stat_type in PITCHER_PROP_STATS

        # Lineup filter: batters only (probable pitchers are in the confirmed
        # set, but exempting pitcher props guards against name-format drift)
        if (not is_pitcher_prop and lineups_posted and confirmed_norm
                and normalize_name(player_name) not in confirmed_norm):
            counts["not_confirmed"] += 1
            continue

        team_full = to_full_name(row.get("player_team", ""))
        ctx       = team_context.get(team_full, {})
        venue     = ctx.get("venue", "")
        opp_pitcher = ctx.get("opp_starter", "") or "TBD"

        matchup_note = "no_adj"
        arsenal_note = ""
        platoon_note = ""
        park_note    = venue if venue else "avg"

        if is_pitcher_prop:
            info = pitcher_lookup(player_name)
            if info is None or info["blended_k_gs"] <= 0:
                # No standalone rate for this pitcher — a league-average prop
                # prediction is noise, so skip rather than default.
                counts["no_profile"] += 1
                continue
            season_rate  = info["k_per_gs"]
            recent_rate  = info["recent_k_gs"]
            blended_rate = info["blended_k_gs"]
            form_source  = "blended_pitcher" if recent_rate else "season_only"
            games_sample = info["gs"]
            matchup_note = f"K/GS: season={season_rate:.1f}" + (f" recent={recent_rate:.1f}" if recent_rate else "")

            # Arsenal adjustment: pitcher's own whiff rate vs league avg
            arsenal_info = arsenal_lookup(player_name)
            blended_rate = blended_rate * arsenal_info["arsenal_adj"]
            if arsenal_info["arsenal_adj"] != 1.0:
                arsenal_note = f"whiff={arsenal_info['arsenal_whiff_pct']:.1f}% adj={arsenal_info['arsenal_adj']:.2f}x"

        else:
            profile_row = batter_lookup(player_name)
            season_rate = _rate_from_row(profile_row, stat_col)
            if season_rate is None:
                counts["no_profile"] += 1
                continue
            games_sample = int(profile_row.get("games_sample", 0) or 0)

            recent_row  = recent_bat_lookup(player_name)
            recent_rate = _rate_from_row(recent_row, RECENT_COL_MAP.get(stat_col, ""))

            if recent_rate is not None:
                blended_rate = RECENT_WEIGHT * recent_rate + SEASON_WEIGHT * season_rate
                form_source  = "blended"
            else:
                blended_rate = season_rate
                form_source  = "season_only"

            # 3. Opposing-starter matchup + arsenal
            if stat_col in PITCHER_ADJ_BATTER_STATS and opp_pitcher and opp_pitcher != "TBD":
                opp_info = pitcher_lookup(opp_pitcher) or dict(LEAGUE_DEFAULT)
                k_adj = opp_info["k_adj"]
                blended_rate = apply_pitcher_matchup(blended_rate, stat_col, k_adj)
                matchup_note = f"vs {opp_pitcher} (k_adj={k_adj:.2f})"

                opp_arsenal = arsenal_lookup(opp_pitcher)
                if opp_arsenal["arsenal_adj"] != 1.0:
                    arsenal_mult = 1.0 - 0.3 * (opp_arsenal["arsenal_adj"] - 1.0)
                    blended_rate = max(blended_rate * arsenal_mult, 0.0)
                    arsenal_note = f"arsenal_adj={opp_arsenal['arsenal_adj']:.2f}x"

            # 4. Park factor
            blended_rate = apply_park_factor(blended_rate, stat_col, venue)

            # 5. Platoon (batter hand vs opposing starter's hand)
            bat_side   = handedness_norm.get(normalize_name(player_name), {}).get("bat_side", "")
            pitch_hand = handedness_norm.get(normalize_name(opp_pitcher), {}).get("pitch_hand", "")
            if bat_side and pitch_hand:
                platoon_mult = get_platoon_adj(bat_side, pitch_hand, stat_col)
                blended_rate = max(blended_rate * platoon_mult, 0.0)
                platoon_note = f"{bat_side}HB vs {pitch_hand}HP ({platoon_mult:.3f}x)"

        if blended_rate <= 0:
            counts["no_profile"] += 1
            continue

        p_more, p_less = prob_more_less(blended_rate, line)
        breakeven = breakeven_prob(row["platform"])

        if p_more >= p_less:
            direction, model_prob = "More", p_more
        else:
            direction, model_prob = "Less", p_less
        edge = model_prob - breakeven

        if edge <= 0:
            counts["no_edge"] += 1
            continue

        counts["passed"] += 1
        predictions.append({
            "platform":      row["platform"],
            "player_name":   player_name,
            "player_team":   row.get("player_team", ""),
            "stat_type":     stat_type,
            "stat_key":      stat_col,
            "stat_display":  STAT_DISPLAY.get(stat_col, stat_type),
            "line":          line,
            "direction":     direction,
            "model_prob":    round(model_prob, 4),
            "implied_prob":  round(breakeven, 4),
            "edge":          round(edge, 4),
            "expected_rate": round(blended_rate, 3),
            "season_rate":   round(season_rate, 3),
            "recent_rate":   round(recent_rate, 3) if recent_rate is not None else None,
            "games_sample":  games_sample,
            "form_source":   form_source,
            "matchup":       matchup_note,
            "arsenal":       arsenal_note,
            "park":          park_note,
            "platoon":       platoon_note,
            "game_id":       row.get("game_id", ""),
        })

    diag = " ".join(f"{k}={v}" for k, v in counts.items())
    print(f"[props] {diag}", file=sys.stderr)
    if unknown_stat_types:
        print(f"[props] unknown_stat_types={sorted(unknown_stat_types)}", file=sys.stderr)

    return predictions


def apply_pitcher_matchup(base_rate: float, stat_col: str, k_adj: float) -> float:
    """
    Adjust batter's expected rate based on opposing pitcher's K-rate vs league avg.
    k_adj > 1.0 = tougher pitcher → fewer hits, more Ks
    k_adj < 1.0 = weaker pitcher  → more hits, fewer Ks
    Dampened by MATCHUP_STRENGTH so season form isn't completely overridden.
    """
    if stat_col == "so_pg":
        adj = 1.0 + MATCHUP_STRENGTH * (k_adj - 1.0)
    elif stat_col in PITCHER_ADJ_BATTER_STATS:
        adj = 1.0 - MATCHUP_STRENGTH * (k_adj - 1.0)
    else:
        adj = 1.0
    return max(base_rate * adj, 0.0)


if __name__ == "__main__":
    preds = predict_props()
    preds_sorted = sorted(preds, key=lambda x: x["edge"], reverse=True)
    print(f"Generated {len(preds)} predictions\n")

    print(f"{'Player':<22} {'Stat':<22} {'Line':>4} {'Dir':>5} {'Model%':>7} {'Edge':>6} {'Season':>7} {'Recent':>7} {'Matchup'}")
    print("-" * 115)
    for p in preds_sorted[:20]:
        recent = f"{p['recent_rate']:.2f}" if p["recent_rate"] is not None else "  N/A"
        print(
            f"{p['player_name']:<22} {p['stat_type']:<22} {p['line']:>4} "
            f"{p['direction']:>5} {p['model_prob']:>6.1%} {p['edge']:>+6.1%} "
            f"{p['season_rate']:>7.2f} {recent:>7}  {p['matchup']}"
        )
