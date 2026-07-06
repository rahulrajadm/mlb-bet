"""
Fetches today's MLB schedule and starting lineups from the official MLB Stats API.
No API key required.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from utils.db import get_conn
from utils.dates import today_str

MLB_API = "https://statsapi.mlb.com/api/v1"


def fetch_today_schedule(game_date: str = None) -> list[dict]:
    if game_date is None:
        game_date = today_str()  # Central time — UTC hosts roll over at 7pm CDT

    url = f"{MLB_API}/schedule"
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "probablePitcher,lineups,team,venue",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            home = g["teams"]["home"]
            away = g["teams"]["away"]
            game = {
                "game_id": str(g["gamePk"]),
                "date": game_date,
                "home_team": home["team"]["name"],
                "away_team": away["team"]["name"],
                "home_starter": home.get("probablePitcher", {}).get("fullName", "TBD"),
                "away_starter": away.get("probablePitcher", {}).get("fullName", "TBD"),
                "venue": g.get("venue", {}).get("name", ""),
                "game_time": g.get("gameDate", ""),
            }
            games.append(game)

    return games


def save_schedule(games: list[dict]):
    conn = get_conn()
    c = conn.cursor()
    for g in games:
        c.execute("""
            INSERT OR REPLACE INTO games
            (game_id, date, home_team, away_team, home_starter, away_starter, venue, game_time)
            VALUES (:game_id, :date, :home_team, :away_team, :home_starter, :away_starter, :venue, :game_time)
        """, g)
    conn.commit()
    conn.close()


def get_today_games(game_date: str = None) -> list[dict]:
    games = fetch_today_schedule(game_date)
    save_schedule(games)
    return games


if __name__ == "__main__":
    games = get_today_games()
    print(f"Found {len(games)} games today:")
    for g in games:
        print(f"  {g['away_team']} @ {g['home_team']}  |  {g['away_starter']} vs {g['home_starter']}")
