"""
Fetches confirmed starting lineups from the MLB Stats API.
Lineups are typically posted 3-4 hours before first pitch.
Falls back gracefully when lineups aren't confirmed yet.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import date
from utils.db import get_conn

MLB_API = "https://statsapi.mlb.com/api/v1"


def fetch_lineups(game_date: str = None) -> dict:
    """
    Returns a dict mapping game_id -> {home: [player_names], away: [player_names]}.
    Empty lists mean lineups aren't posted yet.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    url = f"{MLB_API}/schedule"
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "lineups,probablePitcher,team",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

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
    Returns a set of confirmed player names for today.
    Empty set = lineups not posted yet (don't filter in that case).
    """
    lineups = fetch_lineups(game_date)
    confirmed = set()
    for info in lineups.values():
        confirmed.update(info["home_players"])
        confirmed.update(info["away_players"])
    return confirmed


def lineups_are_posted(game_date: str = None) -> bool:
    lineups = fetch_lineups(game_date)
    return any(info["confirmed"] for info in lineups.values())


if __name__ == "__main__":
    lineups = fetch_lineups()
    posted = any(v["confirmed"] for v in lineups.values())
    print(f"Lineups posted: {posted}")
    for game_id, info in lineups.items():
        status = "CONFIRMED" if info["confirmed"] else "pending"
        print(f"  {info['away_team']} @ {info['home_team']} [{status}]")
        if info["confirmed"]:
            print(f"    Home: {', '.join(info['home_players'][:4])}...")
            print(f"    Away: {', '.join(info['away_players'][:4])}...")
