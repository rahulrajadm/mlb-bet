"""
Pulls last 14 days of batting and pitching stats from Baseball Reference.
Stored separately from season data and blended into predictions at model time.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pybaseball as pb
from datetime import date, timedelta
from utils.db import get_conn

RECENT_DAYS = 14
MIN_PA = 10   # minimum plate appearances to trust recent batting form
MIN_IP = 3    # minimum innings pitched to trust recent pitching form


def pull_recent_batting() -> pd.DataFrame:
    end   = date.today()
    start = end - timedelta(days=RECENT_DAYS)
    print(f"  Pulling recent batting {start} → {end}...")
    df = pb.batting_stats_range(str(start), str(end))
    df = df[df["Lev"].str.startswith("Maj", na=False)].copy()
    df = df[df["PA"] >= MIN_PA].copy()

    df["singles"]   = df["H"] - df["2B"] - df["3B"] - df["HR"]
    df["tb"]        = df["H"] + df["2B"] + 2 * df["3B"] + 3 * df["HR"]
    df["h_r_rbi"]   = df["H"] + df["R"] + df["RBI"]

    rate_cols = ["H", "HR", "RBI", "R", "BB", "SO", "SB", "2B", "singles", "tb", "h_r_rbi"]
    for col in rate_cols:
        df[f"{col}_pg"] = df[col] / df["G"].replace(0, pd.NA)

    return df[["Name", "G", "PA"] + [f"{c}_pg" for c in rate_cols] + ["BA", "OBP", "SLG"]]


def pull_recent_pitching() -> pd.DataFrame:
    end   = date.today()
    start = end - timedelta(days=RECENT_DAYS)
    print(f"  Pulling recent pitching {start} → {end}...")
    try:
        df = pb.pitching_stats_bref(2026)
        df = df[df["Lev"].str.startswith("Maj", na=False)].copy() if "Lev" in df.columns else df
        df = df[pd.to_numeric(df["IP"], errors="coerce") >= MIN_IP].copy()
        df["k_per_9"]  = pd.to_numeric(df["SO"], errors="coerce") / pd.to_numeric(df["IP"], errors="coerce") * 9
        df["k_per_gs"] = pd.to_numeric(df["SO"], errors="coerce") / df["GS"].replace(0, pd.NA)
        return df[["Name", "G", "GS", "IP", "SO", "ERA", "WHIP", "k_per_9", "k_per_gs"]]
    except Exception as e:
        print(f"  Warning: {e}")
        return pd.DataFrame()


def save_recent_form(batting: pd.DataFrame, pitching: pd.DataFrame):
    conn = get_conn()
    if not batting.empty:
        batting.to_sql("recent_batting", conn, if_exists="replace", index=False)
        print(f"  Saved {len(batting)} recent batting rows")
    if not pitching.empty:
        pitching.to_sql("recent_pitching", conn, if_exists="replace", index=False)
        print(f"  Saved {len(pitching)} recent pitching rows")
    conn.commit()
    conn.close()


def get_recent_form():
    print("Pulling recent form (last 14 days)...")
    batting  = pull_recent_batting()
    pitching = pull_recent_pitching()
    save_recent_form(batting, pitching)
    return batting, pitching


if __name__ == "__main__":
    b, p = get_recent_form()
    print(f"\nRecent batting sample:")
    print(b[["Name", "G", "H_pg", "HR_pg", "SO_pg"]].head(5).to_string())
