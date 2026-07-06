"""
Fetches confirmed starting lineups from the MLB Stats API.
Lineups are typically posted 3-4 hours before first pitch.
Falls back gracefully when lineups aren't confirmed yet.

get_confirmed_players() includes probable starting pitchers — the lineup
arrays are batters only, and without the pitchers every pitcher prop would
be dropped the moment lineups post.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from utils.dates import today_str

MLB_API = "https://statsapi.mlb.com/api/v1"


def _fetch_schedule(game_date: str = None) -> dict:
    if game_date is None:
        game_date = today_str()
    url = f"{MLB_API}/schedule"
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "lineups,probablePitcher,team",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_lineups(game_date: str = None) -> dict:
    """
    Returns a dict mapping game_id -> lineup info.
    Empty player lists mean lineups aren't posted yet.
    """
    data = _fetch_schedule(game_date)

    lineups = {}
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            game_id = str(g["gamePk"])
            home = g["teams"]["home"]
            away = g["teams"]["away"]

            home_players = [p.get("fullName", "") for p in home.get("lineup", [])]
            away_players = [p.get("fullName", "") for p in away.get("lineup", [])]

            lineups[game_id] = {
                "home_team":    home["team"]["name"],
                "away_team":    away["team"]["name"],
                "home_players": home_players,
                "away_players": away_players,
                "confirmed":    len(home_players) > 0 or len(away_players) > 0,
            }

    return lineups


def get_confirmed_players(game_date: str = None) -> set:
    """
    Confirmed batters for today plus both probable starting pitchers.
    Empty set = lineups not posted yet (don't filter in that case).
    """
    data = _fetch_schedule(game_date)
    confirmed = set()
    any_lineup = False
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            for side in ("home", "away"):
                team = g["teams"][side]
                lineup = team.get("lineup", [])
                if lineup:
                    any_lineup = True
                confirmed.update(p.get("fullName", "") for p in lineup)
                pitcher = team.get("probablePitcher", {}).get("fullName")
                if pitcher:
                    confirmed.add(pitcher)
    confirmed.discard("")
    return confirmed if any_lineup else set()


def get_todays_player_ids(game_date: str = None) -> set[int]:
    """MLB player ids for confirmed lineups + probable pitchers — used to
    fetch handedness without a seeded local DB (cloud parity)."""
    data = _fetch_schedule(game_date)
    ids = set()
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            for side in ("home", "away"):
                team = g["teams"][side]
                ids.update(p["id"] for p in team.get("lineup", []) if p.get("id"))
                pid = team.get("probablePitcher", {}).get("id")
                if pid:
                    ids.add(pid)
    return ids


def lineups_are_posted(game_date: str = None) -> bool:
    lineups = fetch_lineups(game_date)
    return any(info["confirmed"] for info in lineups.values())


if __name__ == "__main__":
    lineups = fetch_lineups()
    posted = any(v["confirmed"] for v in lineups.values())
    print(f"Lineups posted: {posted}")
    print(f"Confirmed players (incl. probable pitchers): {len(get_confirmed_players())}")
    for game_id, info in lineups.items():
        status = "CONFIRMED" if info["confirmed"] else "pending"
        print(f"  {info['away_team']} @ {info['home_team']} [{status}]")
