"""
Team-level season run rates from the MLB Stats API (free, no key).

Runs scored per game (offense) and runs allowed per game (defense/pitching)
plus league averages — the inputs to the game run-expectation model in
models/game_model.py. Keyed by MLB full team name to match schedule rows.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import datetime, timezone
from utils.db import get_conn
from utils.dates import today_str

STATS_URL = "https://statsapi.mlb.com/api/v1/teams/stats"


def _team_group(season: int, group: str) -> dict[str, dict]:
    resp = requests.get(STATS_URL, params={
        "season": season, "group": group, "stats": "season", "sportId": 1,
    }, timeout=15)
    resp.raise_for_status()
    splits = resp.json().get("stats", [{}])[0].get("splits", [])
    out = {}
    for s in splits:
        st = s.get("stat", {})
        g  = st.get("gamesPlayed") or 0
        r  = st.get("runs") or 0
        if g:
            out[s["team"]["name"]] = {"runs": float(r), "games": float(g),
                                      "era": float(st.get("era") or 0) or None}
    return out


def fetch_team_stats(season: int | None = None) -> dict:
    """{full_team_name: {rs_pg, ra_pg}} plus 'lg_rs_pg' / 'lg_ra_pg' averages.

    lg_rs_pg == lg_ra_pg by construction (every run scored is a run allowed);
    both are returned so callers read whichever is clearer.
    """
    season = season or int(today_str()[:4])
    hitting  = _team_group(season, "hitting")
    pitching = _team_group(season, "pitching")

    teams = {}
    for name, h in hitting.items():
        p = pitching.get(name)
        if not p:
            continue
        teams[name] = {
            "rs_pg": h["runs"] / h["games"],
            "ra_pg": p["runs"] / p["games"],
        }
    if not teams:
        return {}

    lg_rs = sum(t["rs_pg"] for t in teams.values()) / len(teams)
    lg_ra = sum(t["ra_pg"] for t in teams.values()) / len(teams)
    teams["lg_rs_pg"] = lg_rs
    teams["lg_ra_pg"] = lg_ra
    return teams


def save_team_stats(teams: dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS team_stats (
        fetched_at TEXT, team TEXT PRIMARY KEY, rs_pg REAL, ra_pg REAL)""")
    now = datetime.now(timezone.utc).isoformat()
    for name, t in teams.items():
        if name.startswith("lg_"):
            continue
        c.execute("""INSERT INTO team_stats (fetched_at, team, rs_pg, ra_pg)
                     VALUES (?, ?, ?, ?)
                     ON CONFLICT(team) DO UPDATE SET
                       fetched_at=excluded.fetched_at,
                       rs_pg=excluded.rs_pg, ra_pg=excluded.ra_pg""",
                  (now, name, t["rs_pg"], t["ra_pg"]))
    conn.commit()
    conn.close()


def load_team_stats() -> dict:
    """Read team run rates from SQLite (local path); recomputes league avgs."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT team, rs_pg, ra_pg FROM team_stats").fetchall()
    except Exception:
        rows = []
    conn.close()
    teams = {r[0]: {"rs_pg": r[1], "ra_pg": r[2]} for r in rows}
    if teams:
        n = len(teams)
        lg_rs = sum(t["rs_pg"] for t in teams.values()) / n
        lg_ra = sum(t["ra_pg"] for t in teams.values()) / n
        teams["lg_rs_pg"], teams["lg_ra_pg"] = lg_rs, lg_ra
    return teams


def get_team_stats() -> dict:
    teams = fetch_team_stats()
    save_team_stats(teams)
    return teams


if __name__ == "__main__":
    teams = get_team_stats()
    lg = teams.get("lg_rs_pg", 0)
    print(f"Fetched {len([k for k in teams if not k.startswith('lg_')])} teams "
          f"| league R/G = {lg:.2f}\n")
    for name in sorted((k for k in teams if not k.startswith("lg_")),
                       key=lambda n: teams[n]["rs_pg"], reverse=True)[:6]:
        t = teams[name]
        print(f"  {name:<24} RS/G {t['rs_pg']:.2f}  RA/G {t['ra_pg']:.2f}")
