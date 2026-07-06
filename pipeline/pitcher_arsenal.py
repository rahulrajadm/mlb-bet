"""
Pitcher arsenal analysis — weighted whiff rate across pitch mix.
Used to refine K-prop predictions beyond raw K/9.

A pitcher with a high-whiff slider and heavy slider usage will generate
more strikeouts than their K/9 suggests against certain lineups.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
import pybaseball as pb
from datetime import date
from utils.db import get_conn
from utils.names import clean_name, make_lookup

LEAGUE_AVG_WHIFF_PCT = 26.0   # MLB average weighted whiff rate ~2024
MIN_PA               = 50     # minimum PA to include a pitch type


def pull_arsenal_stats(season: int = None) -> pd.DataFrame:
    if season is None:
        season = date.today().year
    print(f"  Pulling pitcher arsenal stats for {season}...")
    df = pb.statcast_pitcher_arsenal_stats(season, minPA=MIN_PA)
    df.rename(columns={"last_name, first_name": "name_raw"}, inplace=True)
    df["Name"] = df["name_raw"].apply(
        lambda x: clean_name(" ".join(reversed(x.split(", "))) if ", " in str(x) else str(x))
    )
    return df


def compute_weighted_whiff(arsenal_df: pd.DataFrame) -> pd.DataFrame:
    """
    Per pitcher: weighted whiff rate = sum(pitch_usage% * whiff%) / 100.
    Returns one row per pitcher with their overall arsenal whiff rate.
    """
    arsenal_df = arsenal_df.copy()
    arsenal_df["whiff_percent"]  = pd.to_numeric(arsenal_df["whiff_percent"],  errors="coerce")
    arsenal_df["pitch_usage"]    = pd.to_numeric(arsenal_df["pitch_usage"],    errors="coerce")
    arsenal_df["put_away"]       = pd.to_numeric(arsenal_df["put_away"],       errors="coerce")
    arsenal_df["hard_hit_percent"] = pd.to_numeric(arsenal_df["hard_hit_percent"], errors="coerce")

    arsenal_df["weighted_whiff"] = arsenal_df["whiff_percent"] * arsenal_df["pitch_usage"] / 100.0

    profiles = arsenal_df.groupby("Name").agg(
        arsenal_whiff_pct  = ("weighted_whiff",    "sum"),
        avg_put_away       = ("put_away",          "mean"),
        avg_hard_hit_pct   = ("hard_hit_percent",  "mean"),
        pitch_count        = ("pitch_usage",       "count"),
    ).reset_index()

    # Arsenal adjustment: how much better/worse than league avg whiff rate
    # > 1.0 = more swing-and-miss → more Ks
    profiles["arsenal_adj"] = (
        profiles["arsenal_whiff_pct"] / LEAGUE_AVG_WHIFF_PCT
    ).clip(0.5, 2.0)

    return profiles


def save_arsenal(df: pd.DataFrame):
    conn = get_conn()
    df.to_sql("pitcher_arsenal", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()
    print(f"  Saved arsenal profiles for {len(df)} pitchers")


def get_pitcher_arsenal() -> pd.DataFrame:
    raw      = pull_arsenal_stats()
    profiles = compute_weighted_whiff(raw)
    save_arsenal(profiles)
    return profiles


def load_arsenal_from_db() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql("SELECT * FROM pitcher_arsenal", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


ARSENAL_DEFAULT = {"arsenal_whiff_pct": LEAGUE_AVG_WHIFF_PCT, "arsenal_adj": 1.0, "avg_put_away": 18.0}


def make_arsenal_lookup(arsenal_df: pd.DataFrame):
    """name → arsenal dict (league-average default). Build once per run."""
    row_lookup = make_lookup(arsenal_df)

    def lookup(pitcher_name: str) -> dict:
        row = row_lookup(pitcher_name)
        if row is None:
            return dict(ARSENAL_DEFAULT)
        return {
            "arsenal_whiff_pct": float(row["arsenal_whiff_pct"]) if pd.notna(row["arsenal_whiff_pct"]) else LEAGUE_AVG_WHIFF_PCT,
            "arsenal_adj":       float(row["arsenal_adj"])       if pd.notna(row["arsenal_adj"])       else 1.0,
            "avg_put_away":      float(row["avg_put_away"])      if pd.notna(row["avg_put_away"])      else 18.0,
        }

    return lookup


def lookup_arsenal(pitcher_name: str, arsenal_df: pd.DataFrame) -> dict:
    return make_arsenal_lookup(arsenal_df)(pitcher_name)


if __name__ == "__main__":
    df = get_pitcher_arsenal()
    print(df.sort_values("arsenal_adj", ascending=False).head(10)[
        ["Name", "arsenal_whiff_pct", "arsenal_adj", "avg_put_away"]
    ].to_string())
