"""
Fetches live MLB player prop lines from Underdog Fantasy.
Uses the unofficial API endpoints. The over_under_lines payload identifies
teams only by UUID, so team ids are resolved to abbreviations via the
stats teams endpoint — without this, opponent/venue/platoon adjustments
can't locate the player's game.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import datetime, timezone
from utils.db import get_conn

UNDERDOG_URL = "https://api.underdogfantasy.com/beta/v5/over_under_lines"
UNDERDOG_TEAMS_URL = "https://stats.underdogfantasy.com/v1/teams"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def fetch_team_map() -> dict[str, str]:
    """team UUID → abbreviation (e.g. 'LAA'). Empty dict on failure —
    downstream handles unknown teams by skipping matchup adjustments."""
    try:
        resp = requests.get(UNDERDOG_TEAMS_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        teams = resp.json().get("teams", [])
        return {t["id"]: t.get("abbr", "") for t in teams if t.get("sport_id") == "MLB"}
    except Exception as e:
        print(f"  Warning: Underdog team map fetch failed: {e}")
        return {}


def fetch_mlb_lines() -> list[dict]:
    resp = requests.get(UNDERDOG_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    games = {g["id"]: g for g in data.get("games", [])}
    appearances = {a["id"]: a for a in data.get("appearances", [])}
    players = {p["id"]: p for p in data.get("players", [])}
    team_map = fetch_team_map()

    mlb_match_ids = {gid for gid, g in games.items() if g.get("sport_id") == "MLB"}

    props = []
    for line in data.get("over_under_lines", []):
        appearance_id = line.get("over_under", {}).get("appearance_stat", {}).get("appearance_id")
        appearance = appearances.get(appearance_id, {})
        match_id = appearance.get("match_id")

        if match_id not in mlb_match_ids:
            continue

        player_id = appearance.get("player_id")
        player = players.get(player_id, {})
        stat = line.get("over_under", {}).get("appearance_stat", {}).get("display_stat", "")
        ou_line = line.get("stat_value")
        team_id = appearance.get("team_id", "")

        props.append({
            "platform": "underdog",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "player_name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
            "player_team": team_map.get(team_id, ""),
            "stat_type": stat,
            "line": float(ou_line) if ou_line is not None else None,
            # Underdog main lines pay the standard table; non-standard payout
            # variants aren't fetched by this endpoint shape.
            "odds_type": "standard",
            "game_id": str(match_id),
            "more_odds": None,
            "less_odds": None,
        })

    return props


def save_lines(props: list[dict]):
    conn = get_conn()
    c = conn.cursor()
    for p in props:
        c.execute("""
            INSERT INTO prop_lines
            (fetched_at, platform, game_id, player_name, player_team, stat_type, line, odds_type, more_odds, less_odds)
            VALUES (:fetched_at, :platform, :game_id, :player_name, :player_team, :stat_type, :line, :odds_type, :more_odds, :less_odds)
        """, p)
    conn.commit()
    conn.close()


def get_underdog_lines() -> list[dict]:
    props = fetch_mlb_lines()
    save_lines(props)
    return props


if __name__ == "__main__":
    props = get_underdog_lines()
    print(f"Fetched {len(props)} Underdog MLB props:")
    for p in props[:10]:
        print(f"  {p['player_name']} ({p['player_team']}) | {p['stat_type']} | Line: {p['line']}")
