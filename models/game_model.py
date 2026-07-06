"""
Game-outcome model: moneyline, run line (±1.5), and totals.

Heuristic, in the same spirit as the prop pipeline (no trained ML). Each team's
expected runs come from a Bill-James-style matchup of season run rates:

    E[team runs] = (team RS/G) * (opponent RA/G) / (league R/G)

adjusted for today's opposing starter (ERA vs league, dampened) and the park's
run factor. From the two expected-run means:

  * moneyline & run line   → Skellam (difference of two Poissons)
  * totals                 → Poisson on the summed mean

Model probabilities are compared against de-vigged sportsbook consensus (from
the game_odds table / in-memory odds) to surface edges and per-$100 EV. When no
odds are available the markets still show as model projections (edge/EV = None).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from scipy.stats import poisson, skellam

from utils.names import normalize_name
from utils.dates import local_day_utc_bounds
from utils.db import get_conn
from pipeline.team_names import to_full_name
from pipeline.park_factors import get_park_factor
from pipeline.team_stats import load_team_stats

LEAGUE_AVG_ERA = 4.20
STARTER_WEIGHT = 0.35   # today's starter only nudges the team RA (already
                        # reflects their pitching) — dampened to avoid double count
MIN_GAME_EDGE  = 0.03   # surface a market only if |model − book| clears this


# ── American-odds helpers ───────────────────────────────────────────────────────

def american_to_prob(odds: float) -> float:
    if odds is None:
        return None
    odds = float(odds)
    return (-odds) / (-odds + 100) if odds < 0 else 100 / (odds + 100)


def american_profit(odds: float, stake: float = 100.0) -> float:
    """Profit on a winning `stake` bet at these American odds."""
    odds = float(odds)
    return stake * (odds / 100.0) if odds > 0 else stake * (100.0 / -odds)


def ev_per_100(model_prob: float, odds: float) -> float:
    """Expected value of a $100 bet at the book's price given the model prob."""
    profit = american_profit(odds, 100.0)
    return model_prob * profit - (1 - model_prob) * 100.0


def _devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    total = (prob_a or 0) + (prob_b or 0)
    if total <= 0:
        return None, None
    return prob_a / total, prob_b / total


# ── Run expectation + pricing ───────────────────────────────────────────────────

def expected_runs(rs_off, ra_def_opp, lg_rpg, opp_starter_era, park):
    base = rs_off * ra_def_opp / lg_rpg if lg_rpg else rs_off
    if opp_starter_era and opp_starter_era > 0:
        factor = opp_starter_era / LEAGUE_AVG_ERA
        base *= STARTER_WEIGHT * factor + (1 - STARTER_WEIGHT)
    return max(base * park, 0.05)


def _p_over(mean: float, line: float) -> float:
    """P(total > line). x.5 lines: P(T ≥ ceil). Integer lines push-condition
    out P(T = line) (a refund), matching the prop pipeline's convention."""
    if float(line).is_integer():
        li = int(line)
        p_over  = 1.0 - poisson.cdf(li, mean)
        p_under = poisson.cdf(li - 1, mean)
        denom = p_over + p_under
        return p_over / denom if denom > 0 else 0.5
    return 1.0 - poisson.cdf(int(np.ceil(line)) - 1, mean)


def price_game(e_home: float, e_away: float, total_line: float | None) -> dict:
    """Model probabilities for every game market from the two run means."""
    # Skellam(D = home − away). MLB has no ties, so split the P(D=0) mass 50/50.
    p_home_win = (1.0 - skellam.cdf(0, e_home, e_away)) + 0.5 * skellam.pmf(0, e_home, e_away)
    # Run line: favourite lays 1.5 (win by ≥2), dog takes +1.5 (lose by ≤1 / win).
    p_home_minus15 = 1.0 - skellam.cdf(1, e_home, e_away)   # D ≥ 2
    p_home_plus15  = 1.0 - skellam.cdf(-2, e_home, e_away)  # D ≥ −1
    out = {
        "p_home_win":     p_home_win,
        "p_away_win":     1.0 - p_home_win,
        "p_home_minus15": p_home_minus15,
        "p_away_plus15":  1.0 - p_home_minus15,
        "p_home_plus15":  p_home_plus15,
        "p_away_minus15": 1.0 - p_home_plus15,
        "proj_total":     e_home + e_away,
    }
    if total_line is not None:
        p_over = _p_over(e_home + e_away, total_line)
        out["p_over"], out["p_under"] = p_over, 1.0 - p_over
    return out


# ── Odds consensus ──────────────────────────────────────────────────────────────

def _load_odds_rows(odds_data):
    if odds_data is not None:
        return pd.DataFrame(odds_data)
    conn = get_conn()
    try:
        latest = conn.execute("SELECT MAX(fetched_at) FROM game_odds").fetchone()[0]
        df = pd.read_sql("SELECT * FROM game_odds WHERE fetched_at = ?",
                         conn, params=[latest]) if latest else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def _consensus(odds_df: pd.DataFrame, home_full: str, away_full: str) -> dict:
    """Average book prices for one game across all sportsbooks (excludes the
    generic Yes/No Polymarket rows). Matched on full team names."""
    if odds_df.empty:
        return {}
    g = odds_df[(odds_df["home_team"] == home_full) &
                (odds_df["away_team"] == away_full) &
                (odds_df["platform"] != "polymarket")]
    if g.empty:
        return {}
    out = {}
    ml = g[g["market"] == "moneyline"]
    if not ml.empty:
        out["ml_home"] = ml["home_odds"].dropna().mean()
        out["ml_away"] = ml["away_odds"].dropna().mean()
    # Run line: pair each book's price to the HOME point it was posted at.
    # total_line holds that point, so home −1.5 and home +1.5 never blend.
    rl = g[g["market"] == "runline"]
    rl_minus = rl[rl["total_line"] == -1.5]   # home −1.5 (away +1.5)
    rl_plus  = rl[rl["total_line"] == 1.5]     # home +1.5 (away −1.5)
    if not rl_minus.empty:
        out["rl_home_minus15"] = rl_minus["home_odds"].dropna().mean()
        out["rl_away_plus15"]  = rl_minus["away_odds"].dropna().mean()
    if not rl_plus.empty:
        out["rl_home_plus15"]  = rl_plus["home_odds"].dropna().mean()
        out["rl_away_minus15"] = rl_plus["away_odds"].dropna().mean()
    tot = g[g["market"] == "totals"].dropna(subset=["total_line"])
    if not tot.empty:
        # Books post different totals (8.0 vs 8.5); price the modal line and
        # average only the odds at THAT line — mixing lines corrupts the edge.
        line = tot["total_line"].mode().iloc[0]
        at_line = tot[tot["total_line"] == line]
        out["total_line"] = float(line)
        out["over_odds"]  = at_line["over_odds"].dropna().mean()
        out["under_odds"] = at_line["under_odds"].dropna().mean()
    return out


def _market(name, side, line, model_prob, book_odds, opp_book_odds):
    """Assemble one market row, de-vigging the book price against its opposite
    side. edge/EV are None when no odds are available (projection only)."""
    row = {"market": name, "side": side, "line": line,
           "model_prob": round(model_prob, 4),
           "book_prob": None, "book_odds": book_odds, "edge": None, "ev_100": None}
    if book_odds is not None and opp_book_odds is not None:
        fair, _ = _devig(american_to_prob(book_odds), american_to_prob(opp_book_odds))
        if fair is not None:
            row["book_prob"] = round(fair, 4)
            row["edge"]      = round(model_prob - fair, 4)
            row["ev_100"]    = round(ev_per_100(model_prob, book_odds), 1)
    return row


# ── Orchestrator ────────────────────────────────────────────────────────────────

def _era_lookup(pitcher_stats):
    if pitcher_stats is None or len(pitcher_stats) == 0:
        return {}
    df = pd.DataFrame(pitcher_stats) if not isinstance(pitcher_stats, pd.DataFrame) else pitcher_stats
    col = "ERA" if "ERA" in df.columns else ("era" if "era" in df.columns else None)
    if col is None or "Name" not in df.columns:
        return {}
    out = {}
    for _, r in df.iterrows():
        try:
            out[normalize_name(str(r["Name"]))] = float(r[col])
        except (TypeError, ValueError):
            continue
    return out


def predict_games(games_data=None, team_stats_data=None,
                  pitcher_stats_data=None, odds_data=None) -> list[dict]:
    # Games
    if games_data is not None:
        games = pd.DataFrame(games_data)
    else:
        conn = get_conn()
        start_utc, end_utc = local_day_utc_bounds()
        games = pd.read_sql(
            "SELECT * FROM games WHERE game_time >= ? AND game_time < ?",
            conn, params=[start_utc, end_utc])
        if games.empty:
            games = pd.read_sql("SELECT * FROM games", conn)
        conn.close()
    if games.empty:
        return []

    teams   = team_stats_data if team_stats_data else load_team_stats()
    if not teams:
        return []
    lg      = teams.get("lg_rs_pg") or 4.5

    # Starter ERA: in-memory when provided (cloud), else SQLite (local)
    if pitcher_stats_data is None:
        conn = get_conn()
        try:
            pitcher_stats_data = pd.read_sql(
                "SELECT Name, ERA FROM pitcher_season_stats", conn)
        except Exception:
            pitcher_stats_data = None
        conn.close()
    era_of  = _era_lookup(pitcher_stats_data)
    odds_df = _load_odds_rows(odds_data)

    results = []
    for _, g in games.iterrows():
        home_full = to_full_name(g.get("home_team", "")) or g.get("home_team", "")
        away_full = to_full_name(g.get("away_team", "")) or g.get("away_team", "")
        home, away = teams.get(home_full), teams.get(away_full)
        if not home or not away:
            continue

        park = get_park_factor(g.get("venue", ""))
        era_home = era_of.get(normalize_name(g.get("home_starter", "") or ""))
        era_away = era_of.get(normalize_name(g.get("away_starter", "") or ""))

        e_home = expected_runs(home["rs_pg"], away["ra_pg"], lg, era_away, park)
        e_away = expected_runs(away["rs_pg"], home["ra_pg"], lg, era_home, park)

        book  = _consensus(odds_df, home_full, away_full)
        total_line = book.get("total_line")
        p = price_game(e_home, e_away, total_line)

        # Favourite (lays −1.5) from the book moneyline when priced, else model.
        if book.get("ml_home") is not None and book.get("ml_away") is not None:
            home_fav = book["ml_home"] < book["ml_away"]   # more negative = fav
        else:
            home_fav = e_home >= e_away

        markets = [
            _market("Moneyline", f"{away_full}", None, p["p_away_win"],
                    book.get("ml_away"), book.get("ml_home")),
            _market("Moneyline", f"{home_full}", None, p["p_home_win"],
                    book.get("ml_home"), book.get("ml_away")),
        ]
        if home_fav:
            markets += [
                _market("Run line", f"{home_full} -1.5", -1.5, p["p_home_minus15"],
                        book.get("rl_home_minus15"), book.get("rl_away_plus15")),
                _market("Run line", f"{away_full} +1.5", 1.5, p["p_away_plus15"],
                        book.get("rl_away_plus15"), book.get("rl_home_minus15")),
            ]
        else:
            markets += [
                _market("Run line", f"{away_full} -1.5", -1.5, p["p_away_minus15"],
                        book.get("rl_away_minus15"), book.get("rl_home_plus15")),
                _market("Run line", f"{home_full} +1.5", 1.5, p["p_home_plus15"],
                        book.get("rl_home_plus15"), book.get("rl_away_minus15")),
            ]
        if total_line is not None:
            markets += [
                _market("Total", f"Over {total_line:g}", total_line, p["p_over"],
                        book.get("over_odds"), book.get("under_odds")),
                _market("Total", f"Under {total_line:g}", total_line, p["p_under"],
                        book.get("under_odds"), book.get("over_odds")),
            ]

        results.append({
            "game_id":   g.get("game_id", ""),
            "home_team": home_full, "away_team": away_full,
            "matchup":   f"{away_full} @ {home_full}",
            "e_home": round(e_home, 2), "e_away": round(e_away, 2),
            "proj_total": round(p["proj_total"], 1),
            "has_odds":  bool(book),
            "markets":   markets,
        })
    return results


def best_game_edges(predictions: list[dict], min_edge: float = MIN_GAME_EDGE) -> list[dict]:
    """Flatten to +edge market picks, best first (only markets with book odds)."""
    picks = []
    for gm in predictions:
        for m in gm["markets"]:
            if m["edge"] is not None and m["edge"] >= min_edge:
                picks.append({**m, "matchup": gm["matchup"], "game_id": gm["game_id"]})
    picks.sort(key=lambda x: x["edge"], reverse=True)
    return picks


if __name__ == "__main__":
    preds = predict_games()
    print(f"Priced {len(preds)} games\n")
    for gm in preds:
        tag = "odds" if gm["has_odds"] else "model-only"
        print(f"{gm['matchup']:<48} proj {gm['e_away']:.1f}-{gm['e_home']:.1f} "
              f"(tot {gm['proj_total']}) [{tag}]")
        for m in gm["markets"]:
            edge = f"{m['edge']:+.1%}" if m["edge"] is not None else "  —  "
            ev   = f"{m['ev_100']:+.1f}" if m["ev_100"] is not None else "  — "
            print(f"    {m['market']:<10} {m['side']:<26} model {m['model_prob']:>6.1%}  edge {edge:>7}  ev/100 {ev:>6}")
    print()
    best = best_game_edges(preds)
    print(f"Top +edge game markets ({len(best)}):")
    for b in best[:12]:
        print(f"  {b['matchup']:<44} {b['market']:<10} {b['side']:<24} "
              f"edge {b['edge']:+.1%}  ev/100 {b['ev_100']:+.1f}")
