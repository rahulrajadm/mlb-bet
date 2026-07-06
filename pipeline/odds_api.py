"""
Fetches MLB odds from The Odds API — used for Fliff reference lines
and as a cross-check for model EV calculations.
Markets: moneyline (h2h), run line (spreads), totals.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from utils.db import get_conn

load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"
REGION = "us"
MARKETS = ["h2h", "spreads", "totals"]


def fetch_odds(market: str, api_key: str | None = None) -> list[dict]:
    url = f"{BASE_URL}/sports/{SPORT}/odds"
    params = {
        "apiKey": api_key or API_KEY,
        "regions": REGION,
        "markets": market,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    print(f"  Odds API requests remaining: {resp.headers.get('x-requests-remaining', 'N/A')}")
    return resp.json()


_MARKET_NAME = {"h2h": "moneyline", "spreads": "runline", "totals": "totals"}


def _rows_from_games(games: list[dict], market: str) -> list[dict]:
    """Normalize one market's API payload to game_odds row dicts (in-memory,
    no DB writes) — the same shape predict_games/_consensus expect."""
    name = _MARKET_NAME[market]
    rows = []
    for game in games:
        home, away = game.get("home_team"), game.get("away_team")
        for bk in game.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                if mkt["key"] != market:
                    continue
                outcomes = {o["name"]: o for o in mkt["outcomes"]}
                row = {"platform": bk["key"], "game_id": game["id"],
                       "home_team": home, "away_team": away, "market": name,
                       "home_odds": None, "away_odds": None,
                       "over_odds": None, "under_odds": None, "total_line": None}
                if market in ("h2h", "spreads"):
                    row["home_odds"] = outcomes.get(home, {}).get("price")
                    row["away_odds"] = outcomes.get(away, {}).get("price")
                    if market == "spreads":  # store HOME point (−1.5/+1.5)
                        row["total_line"] = outcomes.get(home, {}).get("point")
                else:  # totals
                    row["over_odds"]  = outcomes.get("Over", {}).get("price")
                    row["under_odds"] = outcomes.get("Under", {}).get("price")
                    row["total_line"] = outcomes.get("Over", {}).get("point")
                rows.append(row)
    return rows


def fetch_all_odds_rows(api_key: str | None = None) -> list[dict]:
    """All three markets as in-memory game_odds rows. One call per market =
    3 metered credits. Used by the cloud app (no SQLite)."""
    rows = []
    for market in MARKETS:
        rows.extend(_rows_from_games(fetch_odds(market, api_key), market))
    return rows


def parse_and_save(games: list[dict], market: str, fetched_at: str | None = None):
    conn = get_conn()
    c = conn.cursor()
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()

    for game in games:
        game_id = game["id"]
        home_team = game["home_team"]
        away_team = game["away_team"]

        for bookmaker in game.get("bookmakers", []):
            book = bookmaker["key"]
            for mkt in bookmaker.get("markets", []):
                if mkt["key"] != market:
                    continue

                outcomes = {o["name"]: o for o in mkt["outcomes"]}

                if market == "h2h":
                    home_odds = outcomes.get(home_team, {}).get("price")
                    away_odds = outcomes.get(away_team, {}).get("price")
                    c.execute("""
                        INSERT INTO game_odds
                        (fetched_at, platform, game_id, home_team, away_team, market, home_odds, away_odds, over_odds, under_odds, total_line)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                    """, (fetched_at, book, game_id, home_team, away_team, "moneyline", home_odds, away_odds))

                elif market == "spreads":
                    home_o = outcomes.get(home_team, {})
                    away_odds = outcomes.get(away_team, {}).get("price")
                    # total_line holds the HOME point (−1.5 fav / +1.5 dog) so
                    # readers can pair each book's odds to the right side.
                    c.execute("""
                        INSERT INTO game_odds
                        (fetched_at, platform, game_id, home_team, away_team, market, home_odds, away_odds, over_odds, under_odds, total_line)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                    """, (fetched_at, book, game_id, home_team, away_team, "runline",
                          home_o.get("price"), away_odds, home_o.get("point")))

                elif market == "totals":
                    over = outcomes.get("Over", {})
                    under = outcomes.get("Under", {})
                    c.execute("""
                        INSERT INTO game_odds
                        (fetched_at, platform, game_id, home_team, away_team, market, home_odds, away_odds, over_odds, under_odds, total_line)
                        VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                    """, (fetched_at, book, game_id, home_team, away_team, "totals",
                          over.get("price"), under.get("price"), over.get("point")))

    conn.commit()
    conn.close()


def get_all_odds():
    # One shared timestamp so all three markets land in the same fetch batch —
    # readers filter on the latest fetched_at and must see every market.
    fetched_at = datetime.now(timezone.utc).isoformat()
    for market in MARKETS:
        print(f"Fetching {market} odds...")
        games = fetch_odds(market)
        parse_and_save(games, market, fetched_at)
        print(f"  Saved {len(games)} games for market: {market}")


if __name__ == "__main__":
    get_all_odds()
