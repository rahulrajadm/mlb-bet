"""
Generates player prop predictions for today's PrizePicks/Underdog lines.

Five-layer prediction:
1. Season average per-game rate (from batter/pitcher profiles)
2. Recent form blend (last 14 days weighted 55%, season 45%)
3. Opposing starter matchup adjustment (pitcher K-rate vs league avg)
4. Park factor adjustment (venue run/HR environment)
5. Platoon adjustment (batter hand vs pitcher hand)

Lineup filter: if confirmed lineups are posted, only predict for confirmed starters.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
import joblib
from scipy.stats import poisson
from utils.db import get_conn
from pipeline.lineups import get_confirmed_players, lineups_are_posted
from pipeline.pitcher_stats import lookup_pitcher
from pipeline.park_factors import apply_park_factor
from pipeline.handedness import load_handedness_from_db, get_platoon_adj

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

# Stats that are pitcher props (opposing lineup quality matters, handled separately)
PITCHER_PROP_STATS = {
    "Pitcher Strikeouts", "Earned Runs Allowed", "Hits Allowed",
    "Pitches Thrown", "Pitching Outs", "Pitcher Fantasy Score",
    "Pitcher Strikeouts (Combo)",
}

# Maps platform stat names → internal rate column
STAT_MAP = {
    "Pitcher Strikeouts":         "k_pg",
    "Hitter Strikeouts":          "so_pg",
    "Batter Strikeouts":          "so_pg",
    "Hitter Fantasy Score":       "fantasy_score_pg",
    "Pitcher Fantasy Score":       "fantasy_score_pg",
    "Fantasy Points":             "fantasy_score_pg",
    "Hits":                       "hits_pg",
    "Home Runs":                  "hr_pg",
    "RBIs":                       "rbi_pg",
    "Runs":                       "runs_pg",
    "Total Bases":                "tb_pg",
    "Hits+Runs+RBIs":             "h_r_rbi_pg",
    "Hits + Runs + RBIs":         "h_r_rbi_pg",
    "Singles":                    "singles_pg",
    "Doubles":                    "doubles_pg",
    "Walks":                      "bb_pg",
    "Batter Walks":               "bb_pg",
    "Stolen Bases":               "sb_pg",
    "Earned Runs Allowed":        "era_pg",
    "Hits Allowed":               "hits_allowed_pg",
    "Pitches Thrown":             "pitches_pg",
    "Pitching Outs":              "pitching_outs_pg",
    "Pitcher Strikeouts (Combo)": "k_pg",
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
    df = pd.read_sql("SELECT * FROM games WHERE date = DATE('now')", conn)
    conn.close()
    return df


def get_recent_rate(player_name: str, stat_col: str, recent_batting: pd.DataFrame, recent_pitching: pd.DataFrame) -> float | None:
    """Look up player's recent per-game rate from last 14 days."""
    name_lower = player_name.lower()

    # Map internal stat col → recent_batting column name
    recent_col_map = {
        "hits_pg":       "H_pg",
        "hr_pg":         "HR_pg",
        "rbi_pg":        "RBI_pg",
        "runs_pg":       "R_pg",
        "bb_pg":         "BB_pg",
        "so_pg":         "SO_pg",
        "sb_pg":         "SB_pg",
        "doubles_pg":    "2B_pg",
        "singles_pg":    "singles_pg",
        "tb_pg":         "tb_pg",
        "h_r_rbi_pg":    "h_r_rbi_pg",
    }
    recent_col = recent_col_map.get(stat_col)

    for df in [recent_batting, recent_pitching]:
        if df.empty or "Name" not in df.columns:
            continue
        match = df[df["Name"].str.lower() == name_lower]
        if match.empty:
            last = name_lower.split()[-1]
            match = df[df["Name"].str.lower().str.contains(last, na=False)]
        if not match.empty and recent_col and recent_col in match.columns:
            val = match.iloc[0][recent_col]
            if pd.notna(val) and val >= 0:
                return float(val)

    return None


def get_season_rate(player_name: str, stat_col: str, batters: pd.DataFrame, pitchers: pd.DataFrame) -> float | None:
    """Look up player's season per-game rate from historical profiles."""
    name_lower = player_name.lower()
    for df in [batters, pitchers]:
        if "Name" not in df.columns:
            continue
        match = df[df["Name"].str.lower() == name_lower]
        if match.empty:
            last = name_lower.split()[-1]
            match = df[df["Name"].str.lower().str.contains(last, na=False)]
        if not match.empty and stat_col in match.columns:
            val = match.iloc[0][stat_col]
            if pd.notna(val) and val >= 0:
                return float(val)
    return None


def get_opponent_pitcher(player_team: str, games: pd.DataFrame) -> str:
    """Given a batter's team, find tonight's opposing starting pitcher name."""
    for _, g in games.iterrows():
        if player_team and (
            player_team.lower() in g.get("home_team", "").lower() or
            g.get("home_team", "").lower() in player_team.lower()
        ):
            return g.get("away_starter", "TBD")
        if player_team and (
            player_team.lower() in g.get("away_team", "").lower() or
            g.get("away_team", "").lower() in player_team.lower()
        ):
            return g.get("home_starter", "TBD")
    return "TBD"


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


def prob_over_line(expected_rate: float, line: float) -> float:
    """P(stat > line) using Poisson distribution."""
    threshold = int(np.ceil(line))
    return 1.0 - poisson.cdf(threshold - 1, mu=expected_rate)


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
) -> list[dict]:
    batters, pitchers = load_profiles()

    # Use pre-fetched data if provided, otherwise read from SQLite
    if recent_batting_data is not None and recent_pitching_data is not None:
        recent_batting, recent_pitching = recent_batting_data, recent_pitching_data
    else:
        recent_batting, recent_pitching = load_recent_form()

    pitcher_stats = pitcher_stats_data if pitcher_stats_data is not None else load_pitcher_season_stats()
    handedness_db = handedness_data if handedness_data is not None else load_handedness_from_db()

    if games_data is not None:
        games = pd.DataFrame(games_data)
    else:
        games = load_games_today()

    # Lineup filter
    if confirmed_players_data is not None:
        lineups_posted    = len(confirmed_players_data) > 0
        confirmed_players = confirmed_players_data
    else:
        lineups_posted    = lineups_are_posted()
        confirmed_players = get_confirmed_players() if lineups_posted else set()

    # Build venue lookup: team_name → venue
    venue_map = {}
    if not games.empty:
        for _, g in games.iterrows():
            venue_map[g.get("home_team", "")] = g.get("venue", "")
            venue_map[g.get("away_team", "")] = g.get("venue", "")

    # Build lines DataFrame from pre-fetched data or SQLite
    if lines_data is not None:
        lines = pd.DataFrame(lines_data)
        if platform:
            lines = lines[lines["platform"] == platform]
    else:
        conn = get_conn()
        query = "SELECT * FROM prop_lines WHERE DATE(fetched_at) = DATE('now')"
        if platform:
            query += f" AND platform = '{platform}'"
        lines = pd.read_sql(query, conn)
        conn.close()

    lines = lines.sort_values("fetched_at", ascending=False).drop_duplicates(
        subset=["platform", "player_name", "stat_type"]
    )

    predictions = []
    for _, row in lines.iterrows():
        stat_col = STAT_MAP.get(row["stat_type"])
        if stat_col is None or row["line"] is None:
            continue

        player_name = row["player_name"]
        line        = float(row["line"])

        # Lineup filter: skip if lineups are posted and player isn't confirmed
        if lineups_posted and confirmed_players and player_name not in confirmed_players:
            continue

        # Season rate
        season_rate = get_season_rate(player_name, stat_col, batters, pitchers)
        if season_rate is None:
            continue

        # Recent form rate
        recent_rate = get_recent_rate(player_name, stat_col, recent_batting, recent_pitching)

        # Blend: recent form + season average
        if recent_rate is not None:
            blended_rate = RECENT_WEIGHT * recent_rate + SEASON_WEIGHT * season_rate
            form_source  = "blended"
        else:
            blended_rate = season_rate
            form_source  = "season_only"

        player_team = row.get("player_team", "")

        # 3. Pitcher matchup adjustment (batter stats only)
        opp_pitcher  = "TBD"
        k_adj        = 1.0
        matchup_note = "no_adj"
        if stat_col in PITCHER_ADJ_BATTER_STATS and not games.empty:
            opp_pitcher = get_opponent_pitcher(player_team, games)
            if opp_pitcher and opp_pitcher != "TBD":
                pitcher_info = lookup_pitcher(opp_pitcher, pitcher_stats)
                k_adj        = pitcher_info["k_adj"]
                blended_rate = apply_pitcher_matchup(blended_rate, stat_col, k_adj)
                matchup_note = f"vs {opp_pitcher} (k_adj={k_adj:.2f})"

        # 4. Park factor adjustment
        venue      = venue_map.get(player_team, "")
        park_note  = venue if venue else "avg"
        blended_rate = apply_park_factor(blended_rate, stat_col, venue)

        # 5. Platoon adjustment (batter hand vs pitcher hand)
        platoon_note = ""
        player_info  = handedness_db.get(player_name, {})
        bat_side     = player_info.get("bat_side", "")
        pitcher_info_h = handedness_db.get(opp_pitcher, {})
        pitch_hand   = pitcher_info_h.get("pitch_hand", "")
        if bat_side and pitch_hand:
            platoon_mult = get_platoon_adj(bat_side, pitch_hand, stat_col)
            blended_rate = max(blended_rate * platoon_mult, 0.0)
            platoon_note = f"{bat_side}HB vs {pitch_hand}HP ({platoon_mult:.3f}x)"

        if blended_rate <= 0:
            continue

        p_more = prob_over_line(blended_rate, line)
        p_less = 1.0 - p_more

        implied_p  = 0.50
        edge_more  = p_more - implied_p
        edge_less  = p_less - implied_p

        if edge_more >= edge_less:
            direction  = "More"
            model_prob = p_more
            edge       = edge_more
        else:
            direction  = "Less"
            model_prob = p_less
            edge       = edge_less

        if edge <= 0:
            continue

        predictions.append({
            "platform":      row["platform"],
            "player_name":   player_name,
            "player_team":   player_team,
            "stat_type":     row["stat_type"],
            "line":          line,
            "direction":     direction,
            "model_prob":    round(model_prob, 4),
            "implied_prob":  implied_p,
            "edge":          round(edge, 4),
            "expected_rate": round(blended_rate, 3),
            "season_rate":   round(season_rate, 3),
            "recent_rate":   round(recent_rate, 3) if recent_rate is not None else None,
            "form_source":   form_source,
            "matchup":       matchup_note,
            "park":          park_note,
            "platoon":       platoon_note,
            "game_id":       row.get("game_id", ""),
        })

    return predictions


if __name__ == "__main__":
    preds = predict_props()
    preds_sorted = sorted(preds, key=lambda x: x["edge"], reverse=True)
    print(f"Generated {len(preds)} predictions\n")

    # Show picks where recent form differs from season (most interesting)
    blended = [p for p in preds_sorted if p["form_source"] == "blended" and 0.55 <= p["model_prob"] <= 0.85]
    print(f"Blended (recent+season) picks: {len(blended)}")
    print(f"\n{'Player':<22} {'Stat':<25} {'Line':>4} {'Dir':>5} {'Model%':>7} {'Edge':>6} {'Season':>7} {'Recent':>7} {'Matchup'}")
    print("-" * 115)
    for p in blended[:15]:
        recent = f"{p['recent_rate']:.2f}" if p["recent_rate"] is not None else "  N/A"
        print(
            f"{p['player_name']:<22} {p['stat_type']:<25} {p['line']:>4} "
            f"{p['direction']:>5} {p['model_prob']:>6.1%} {p['edge']:>+6.1%} "
            f"{p['season_rate']:>7.2f} {recent:>7}  {p['matchup']}"
        )
