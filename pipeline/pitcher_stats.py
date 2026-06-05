"""
Pulls current season pitcher stats from Baseball Reference.
Used for matchup context: adjusting batter projections based on opposing starter quality.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pybaseball as pb
from datetime import date
from utils.db import get_conn

LEAGUE_AVG_K9  = 8.8   # MLB league average K/9 (2024)
LEAGUE_AVG_ERA = 4.20


def pull_pitcher_stats() -> pd.DataFrame:
    season = date.today().year
    print(f"  Pulling pitcher stats for {season} from Baseball Reference...")
    df = pb.pitching_stats_bref(season)

    # Keep only starters with meaningful sample
    starters = df[pd.to_numeric(df["GS"], errors="coerce") >= 3].copy()
    starters["IP_num"]    = pd.to_numeric(starters["IP"], errors="coerce")
    starters["SO_num"]    = pd.to_numeric(starters["SO"], errors="coerce")
    starters["ERA_num"]   = pd.to_numeric(starters["ERA"], errors="coerce")
    starters["k_per_9"]   = starters["SO_num"] / starters["IP_num"] * 9
    starters["k_per_gs"]  = starters["SO_num"] / pd.to_numeric(starters["GS"], errors="coerce")

    # Matchup adjustment factor vs league average
    # > 1.0 = pitcher is harder on batters, < 1.0 = easier
    starters["k_adj"] = (starters["k_per_9"] / LEAGUE_AVG_K9).clip(0.5, 2.0)

    return starters[["Name", "GS", "IP_num", "SO_num", "ERA_num", "k_per_9", "k_per_gs", "k_adj"]].rename(
        columns={"IP_num": "IP", "SO_num": "SO", "ERA_num": "ERA"}
    )


def save_pitcher_stats(df: pd.DataFrame):
    conn = get_conn()
    df.to_sql("pitcher_season_stats", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()
    print(f"  Saved {len(df)} pitcher profiles")


def get_pitcher_stats() -> pd.DataFrame:
    df = pull_pitcher_stats()
    save_pitcher_stats(df)
    return df


def lookup_pitcher(name: str, df: pd.DataFrame) -> dict:
    """Return a pitcher's matchup stats, falling back to league average."""
    match = df[df["Name"].str.lower() == name.lower()]
    if match.empty:
        last = name.split()[-1].lower()
        match = df[df["Name"].str.lower().str.contains(last, na=False)]

    if not match.empty:
        row = match.iloc[0]
        return {
            "k_per_9":  float(row["k_per_9"]) if pd.notna(row["k_per_9"]) else LEAGUE_AVG_K9,
            "k_per_gs": float(row["k_per_gs"]) if pd.notna(row["k_per_gs"]) else 5.5,
            "era":      float(row["ERA"]) if pd.notna(row["ERA"]) else LEAGUE_AVG_ERA,
            "k_adj":    float(row["k_adj"]) if pd.notna(row["k_adj"]) else 1.0,
        }

    return {"k_per_9": LEAGUE_AVG_K9, "k_per_gs": 5.5, "era": LEAGUE_AVG_ERA, "k_adj": 1.0}


if __name__ == "__main__":
    df = get_pitcher_stats()
    print(df[["Name", "GS", "k_per_9", "k_per_gs", "ERA", "k_adj"]].head(10).to_string())
