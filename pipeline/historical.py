"""
Pulls recent seasons of MLB player stats and Statcast quality data via
pybaseball and stores them in SQLite. Run to (re)seed the database — tables
are rebuilt from scratch, so re-running mid-season refreshes the current
season's partial data.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pybaseball as pb
from utils.db import get_conn, init_db
from utils.dates import today_local

SEASONS = [2024, 2025, 2026]


def _season_range(season: int) -> tuple[str, str]:
    """Opening day-ish through season end, clamped to today for the
    in-progress season."""
    start = f"{season}-03-20"
    end = f"{season}-10-01"
    today = today_local()
    if season == today.year:
        end = min(pd.Timestamp(end).date(), today).isoformat()
    return start, end


def pull_statcast_batters():
    conn = get_conn()
    print("Pulling Statcast batter data...")
    frames = []
    for season in SEASONS:
        print(f"  Statcast batters {season}...")
        try:
            df = pb.statcast_batter_exitvelo_barrels(season, minBBE=50)
            df["season"] = season
            frames.append(df)
        except Exception as e:
            print(f"  Warning: {e}")
    if frames:
        pd.concat(frames).to_sql("statcast_batters", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()


def pull_statcast_pitchers():
    conn = get_conn()
    print("Pulling Statcast pitcher data...")
    frames = []
    for season in SEASONS:
        print(f"  Statcast pitchers {season}...")
        try:
            df = pb.statcast_pitcher_exitvelo_barrels(season, minBBE=50)
            df["season"] = season
            frames.append(df)
        except Exception as e:
            print(f"  Warning: {e}")
    if frames:
        pd.concat(frames).to_sql("statcast_pitchers", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()


def pull_player_game_logs():
    """Per-player season aggregates (B-Ref range stats) for profile building."""
    conn = get_conn()
    print("Pulling batter season stats (this may take a few minutes)...")
    frames = []
    for season in SEASONS:
        start, end = _season_range(season)
        print(f"  Batter stats {season} ({start} → {end})...")
        try:
            df = pb.batting_stats_range(start, end)
            df["season"] = season
            frames.append(df)
        except Exception as e:
            print(f"  Warning: {e}")
    if frames:
        pd.concat(frames).to_sql("batter_game_logs", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    pull_statcast_batters()
    pull_statcast_pitchers()
    pull_player_game_logs()
    print("\nHistorical data pull complete.")
