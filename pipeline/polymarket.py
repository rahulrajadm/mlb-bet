"""
Fetches active MLB prediction markets from Polymarket's public API.
No auth required. Returns game outcome markets with implied probabilities.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import datetime, timezone
from utils.db import get_conn

GAMMA_API = "https://gamma-api.polymarket.com"


MLB_KEYWORDS = [
    "Yankees", "Red Sox", "Dodgers", "Cubs", "Mets", "Giants", "Braves",
    "Astros", "Cardinals", "Padres", "Phillies", "Rays", "Tigers", "Mariners",
    "Rangers", "Twins", "Royals", "Orioles", "Blue Jays", "Athletics", "Reds",
    "Pirates", "Brewers", "Rockies", "Nationals", "Diamondbacks", "Angels",
    "Marlins", "Guardians", "White Sox", "MLB", "World Series", "pennant",
]


def fetch_mlb_markets() -> list[dict]:
    url = f"{GAMMA_API}/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 500,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    all_markets = resp.json()

    # Filter to MLB-related markets by keyword
    markets = [
        m for m in all_markets
        if any(kw.lower() in m.get("question", "").lower() for kw in MLB_KEYWORDS)
    ]

    results = []
    for m in markets:
        outcomes = m.get("outcomes", "[]")
        if isinstance(outcomes, str):
            import json
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = []

        prices = m.get("outcomePrices", "[]")
        if isinstance(prices, str):
            import json
            try:
                prices = json.loads(prices)
            except Exception:
                prices = []

        outcome_map = {}
        for i, outcome in enumerate(outcomes):
            price = float(prices[i]) if i < len(prices) else None
            outcome_map[outcome] = price

        results.append({
            "platform": "polymarket",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "market_id": m.get("id", ""),
            "question": m.get("question", ""),
            "outcomes": outcome_map,
            "volume": m.get("volume", 0),
            "end_date": m.get("endDate", ""),
        })

    return results


def save_markets(markets: list[dict]):
    conn = get_conn()
    c = conn.cursor()
    for m in markets:
        outcomes = m["outcomes"]
        teams = list(outcomes.keys())
        if len(teams) >= 2:
            home_team = teams[0]
            away_team = teams[1]
            home_odds = outcomes.get(home_team)
            away_odds = outcomes.get(away_team)

            c.execute("""
                INSERT INTO game_odds
                (fetched_at, platform, game_id, home_team, away_team, market, home_odds, away_odds, over_odds, under_odds, total_line)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
            """, (
                m["fetched_at"], "polymarket", m["market_id"],
                home_team, away_team, "moneyline",
                home_odds, away_odds
            ))
    conn.commit()
    conn.close()


def get_polymarket_lines() -> list[dict]:
    markets = fetch_mlb_markets()
    save_markets(markets)
    return markets


if __name__ == "__main__":
    markets = get_polymarket_lines()
    print(f"Fetched {len(markets)} Polymarket MLB markets:")
    for m in markets[:10]:
        print(f"  {m['question']}")
        for outcome, price in m["outcomes"].items():
            print(f"    {outcome}: {price:.2%}" if price else f"    {outcome}: N/A")
