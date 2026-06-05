"""
Fetches live MLB player prop lines from PrizePicks via their unofficial JSON API.
No auth required. Lines update every few minutes.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import datetime, timezone
from utils.db import get_conn

PRIZEPICKS_URL = "https://api.prizepicks.com/projections"
MLB_LEAGUE_ID = 2  # MLB league ID on PrizePicks

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://app.prizepicks.com/",
}


def fetch_mlb_lines() -> list[dict]:
    params = {
        "league_id": MLB_LEAGUE_ID,
        "per_page": 250,
        "single_stat": "true",
    }
    resp = requests.get(PRIZEPICKS_URL, headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    projections = data.get("data", [])
    included = {item["id"]: item for item in data.get("included", [])}

    props = []
    for proj in projections:
        attrs = proj.get("attributes", {})
        relationships = proj.get("relationships", {})

        player_id = relationships.get("new_player", {}).get("data", {}).get("id")
        player_info = included.get(player_id, {}).get("attributes", {}) if player_id else {}

        props.append({
            "platform": "prizepicks",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "player_name": player_info.get("display_name", attrs.get("description", "")),
            "player_team": player_info.get("team", ""),
            "stat_type": attrs.get("stat_type", ""),
            "line": attrs.get("line_score", None),
            "game_id": attrs.get("game_id", ""),
            "more_odds": None,  # PrizePicks uses fixed multipliers, not per-prop odds
            "less_odds": None,
        })

    return props


def save_lines(props: list[dict]):
    conn = get_conn()
    c = conn.cursor()
    for p in props:
        c.execute("""
            INSERT INTO prop_lines
            (fetched_at, platform, game_id, player_name, player_team, stat_type, line, more_odds, less_odds)
            VALUES (:fetched_at, :platform, :game_id, :player_name, :player_team, :stat_type, :line, :more_odds, :less_odds)
        """, p)
    conn.commit()
    conn.close()


def get_prizepicks_lines() -> list[dict]:
    props = fetch_mlb_lines()
    save_lines(props)
    return props


if __name__ == "__main__":
    props = get_prizepicks_lines()
    print(f"Fetched {len(props)} PrizePicks MLB props:")
    for p in props[:10]:
        print(f"  {p['player_name']} | {p['stat_type']} | Line: {p['line']}")
