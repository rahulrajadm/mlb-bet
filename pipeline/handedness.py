"""
Fetches and caches pitcher and batter handedness from the MLB Stats API.
Used for platoon adjustment in prop predictions.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from datetime import date
from utils.db import get_conn

MLB_API   = "https://statsapi.mlb.com/api/v1"
CHUNK     = 50   # max IDs per people API call

# Platoon adjustment factors applied to hit/TB/HR rates (dampened to 40% of full effect)
# Full empirical advantage: RHB vs LHP ~+8%, LHB vs RHP ~+7%
PLATOON_ADJ = {
    ("R", "L"): 1.04,   # RHB vs LHP — batter advantage
    ("L", "R"): 1.035,  # LHB vs RHP — batter advantage
    ("R", "R"): 0.982,  # same hand — pitcher advantage
    ("L", "L"): 0.978,  # same hand — pitcher advantage
    ("S", "R"): 1.02,   # switch hitter vs RHP
    ("S", "L"): 1.02,   # switch hitter vs LHP
}

# Stats platoon adjustment applies to
PLATOON_STATS = {
    "hits_pg", "hr_pg", "rbi_pg", "runs_pg", "tb_pg",
    "h_r_rbi_pg", "singles_pg", "doubles_pg", "so_pg",
}


def _fetch_people(player_ids: list[int]) -> dict[int, dict]:
    """Batch-fetch handedness for a list of player IDs."""
    result = {}
    for i in range(0, len(player_ids), CHUNK):
        chunk = player_ids[i:i + CHUNK]
        id_str = ",".join(str(x) for x in chunk)
        url    = f"{MLB_API}/people?personIds={id_str}&hydrate=pitchHand,batSide"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            for p in resp.json().get("people", []):
                result[p["id"]] = {
                    "name":       p.get("fullName", ""),
                    "pitch_hand": p.get("pitchHand", {}).get("code", ""),
                    "bat_side":   p.get("batSide",   {}).get("code", ""),
                }
        except Exception as e:
            print(f"  Warning fetching handedness: {e}")
    return result


def fetch_and_save_pitcher_hands(game_date: str = None) -> dict[str, str]:
    """
    Fetches handedness for today's starting pitchers.
    Returns dict: pitcher_name → pitch_hand (L/R/S)
    """
    if game_date is None:
        game_date = date.today().isoformat()

    url = f"{MLB_API}/schedule"
    params = {"sportId": 1, "date": game_date, "hydrate": "probablePitcher,team"}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    id_to_name = {}
    for d in resp.json().get("dates", []):
        for g in d.get("games", []):
            for side in ["home", "away"]:
                p = g["teams"][side].get("probablePitcher", {})
                if p.get("id"):
                    id_to_name[p["id"]] = p.get("fullName", "")

    if not id_to_name:
        return {}

    people = _fetch_people(list(id_to_name.keys()))

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_handedness (
            name TEXT PRIMARY KEY,
            pitch_hand TEXT,
            bat_side TEXT
        )
    """)
    pitcher_hands = {}
    for pid, info in people.items():
        name = info["name"]
        pitcher_hands[name] = info["pitch_hand"]
        c.execute(
            "INSERT OR REPLACE INTO player_handedness (name, pitch_hand, bat_side) VALUES (?,?,?)",
            (name, info["pitch_hand"], info["bat_side"])
        )
    conn.commit()
    conn.close()
    return pitcher_hands


def fetch_and_save_batter_hands() -> dict[str, str]:
    """
    Fetches handedness for batters using mlbIDs stored in batter_game_logs.
    Returns dict: player_name → bat_side (L/R/S)
    """
    conn = get_conn()
    import pandas as pd
    try:
        df = pd.read_sql(
            "SELECT DISTINCT Name, mlbID FROM batter_game_logs WHERE mlbID IS NOT NULL AND mlbID != ''",
            conn
        )
    except Exception:
        conn.close()
        return {}

    id_to_name = {}
    for _, row in df.iterrows():
        try:
            mlb_id = int(float(row["mlbID"]))
            id_to_name[mlb_id] = row["Name"]
        except (ValueError, TypeError):
            pass

    conn.close()
    if not id_to_name:
        return {}

    print(f"  Fetching handedness for {len(id_to_name)} batters...")
    people = _fetch_people(list(id_to_name.keys()))

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_handedness (
            name TEXT PRIMARY KEY,
            pitch_hand TEXT,
            bat_side TEXT
        )
    """)
    batter_sides = {}
    for pid, info in people.items():
        name = id_to_name.get(pid, info["name"])
        batter_sides[name] = info["bat_side"]
        c.execute(
            "INSERT OR REPLACE INTO player_handedness (name, pitch_hand, bat_side) VALUES (?,?,?)",
            (name, info["pitch_hand"], info["bat_side"])
        )
    conn.commit()
    conn.close()
    return batter_sides


def load_handedness_from_db() -> dict[str, dict]:
    """Load cached handedness table from DB."""
    conn = get_conn()
    try:
        import pandas as pd
        df = pd.read_sql("SELECT * FROM player_handedness", conn)
        conn.close()
        return {
            row["name"]: {"pitch_hand": row["pitch_hand"], "bat_side": row["bat_side"]}
            for _, row in df.iterrows()
        }
    except Exception:
        conn.close()
        return {}


def get_platoon_adj(bat_side: str, pitch_hand: str, stat_col: str) -> float:
    """Return platoon adjustment multiplier. 1.0 if stat not affected."""
    if stat_col not in PLATOON_STATS:
        return 1.0
    if not bat_side or not pitch_hand:
        return 1.0
    return PLATOON_ADJ.get((bat_side, pitch_hand), 1.0)


if __name__ == "__main__":
    print("Fetching pitcher handedness...")
    ph = fetch_and_save_pitcher_hands()
    for name, hand in list(ph.items())[:5]:
        print(f"  {name}: {hand}")

    print("Fetching batter handedness...")
    bh = fetch_and_save_batter_hands()
    print(f"  Fetched {len(bh)} batters")
