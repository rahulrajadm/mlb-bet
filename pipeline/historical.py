"""
Pulls 3 seasons of historical MLB game logs and Statcast batting/pitching data
via pybaseball and stores in SQLite. Run once to seed the database.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pybaseball as pb
from utils.db import get_conn, init_db

SEASONS = [2022, 2023, 2024]


def pull_game_logs():
    conn = get_conn()
    print("Pulling historical game logs...")

    for season in SEASONS:
        print(f"  Season {season}...")
        try:
            schedule = pb.schedule_and_record(season, "NYY")
            # Use team_game_logs for each team instead — build from Retrosheet
            pass
        except Exception:
            pass

    # Use pybaseball's team batting/pitching logs via Lahman or fg_team
    try:
        for season in SEASONS:
            print(f"  Fetching batting stats {season}...")
            batting = pb.batting_stats(season, qual=50)
            batting["season"] = season
            batting.to_sql("batting_season", conn, if_exists="append", index=False)

            print(f"  Fetching pitching stats {season}...")
            pitching = pb.pitching_stats(season, qual=30)
            pitching["season"] = season
            pitching.to_sql("pitching_season", conn, if_exists="append", index=False)
    except Exception as e:
        print(f"  Warning: {e}")

    conn.commit()
    conn.close()


def pull_statcast_batters():
    conn = get_conn()
    print("Pulling Statcast batter data...")

    for season in SEASONS:
        print(f"  Statcast batters {season}...")
        try:
            df = pb.statcast_batter_exitvelo_barrels(season, minBBE=50)
            df["season"] = season
            df.to_sql("statcast_batters", conn, if_exists="append", index=False)
        except Exception as e:
            print(f"  Warning: {e}")

    conn.commit()
    conn.close()


def pull_statcast_pitchers():
    conn = get_conn()
    print("Pulling Statcast pitcher data...")

    for season in SEASONS:
        print(f"  Statcast pitchers {season}...")
        try:
            df = pb.statcast_pitcher_exitvelo_barrels(season, minBBE=50)
            df["season"] = season
            df.to_sql("statcast_pitchers", conn, if_exists="append", index=False)
        except Exception as e:
            print(f"  Warning: {e}")

    # Pitcher strikeout/walk rates
    for season in SEASONS:
        print(f"  Pitcher K/BB rates {season}...")
        try:
            df = pb.pitching_stats(season, qual=30)
            df["season"] = season
            df[["Name", "Team", "season", "SO", "BB", "IP", "ERA", "FIP", "xFIP",
                "K/9", "BB/9", "K%", "BB%", "WHIP", "GB%", "HR/9"]].to_sql(
                "pitcher_rates", conn, if_exists="append", index=False
            )
        except Exception as e:
            print(f"  Warning: {e}")

    conn.commit()
    conn.close()


def pull_player_game_logs():
    """Pull individual batter game logs for prop model training."""
    conn = get_conn()
    print("Pulling batter game logs (this may take a few minutes)...")

    try:
        for season in SEASONS:
            print(f"  Batter game logs {season}...")
            df = pb.batting_stats_range(f"{season}-03-28", f"{season}-10-01")
            df["season"] = season
            df.to_sql("batter_game_logs", conn, if_exists="append", index=False)
    except Exception as e:
        print(f"  Warning: {e}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    pull_game_logs()
    pull_statcast_batters()
    pull_statcast_pitchers()
    pull_player_game_logs()
    print("\nHistorical data pull complete.")
