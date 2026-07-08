"""
Fetches live MLB player prop lines from PrizePicks via their unofficial JSON API.
No auth required. Lines update every few minutes.

odds_type matters: "goblin" (easier line, pays less) and "demon" (harder line,
pays more) are More-only and change the payout, so the model prices only
"standard" lines — but everything is fetched and stored for visibility.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import datetime, timezone
from utils.db import get_conn

PRIZEPICKS_URL = "https://api.prizepicks.com/projections"
MLB_LEAGUE_ID = 2  # MLB league ID on PrizePicks

# PrizePicks is fronted by DataDome bot protection, which returns a 403 with a
# captcha-delivery.com interstitial when it doesn't trust the caller (datacenter
# IPs like Streamlit Cloud are challenged aggressively). A full browser-like
# header set is more legitimate but does NOT defeat DataDome — that needs a real
# browser to solve the challenge and mint a `datadome` cookie. So this is
# best-effort only; callers MUST degrade gracefully when the fetch 403s.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
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
    # ids are only unique within a type — keying all included items together
    # lets a "league"/"team" item shadow a player with the same id
    included = {item["id"]: item for item in data.get("included", [])
                if item.get("type") == "new_player"}

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
            "odds_type": attrs.get("odds_type", "standard") or "standard",
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
            (fetched_at, platform, game_id, player_name, player_team, stat_type, line, odds_type, more_odds, less_odds)
            VALUES (:fetched_at, :platform, :game_id, :player_name, :player_team, :stat_type, :line, :odds_type, :more_odds, :less_odds)
        """, p)
    conn.commit()
    conn.close()


def get_prizepicks_lines() -> list[dict]:
    props = fetch_mlb_lines()
    save_lines(props)
    return props


if __name__ == "__main__":
    props = get_prizepicks_lines()
    by_type = {}
    for p in props:
        by_type[p["odds_type"]] = by_type.get(p["odds_type"], 0) + 1
    print(f"Fetched {len(props)} PrizePicks MLB props (odds_type: {by_type}):")
    for p in props[:10]:
        print(f"  {p['player_name']} ({p['player_team']}) | {p['stat_type']} | Line: {p['line']} | {p['odds_type']}")
