"""
Pulls current season pitcher stats + last 3 starts recent form.
Used for matchup context: adjusting batter/pitcher prop projections.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pybaseball as pb
from datetime import date, timedelta
from utils.db import get_conn

LEAGUE_AVG_K9   = 8.8
LEAGUE_AVG_K_GS = 5.5
LEAGUE_AVG_ERA  = 4.20
RECENT_DAYS     = 21   # ~3 starts for a rotation pitcher
RECENT_WEIGHT   = 0.60
SEASON_WEIGHT   = 0.40


def pull_pitcher_stats() -> pd.DataFrame:
    season = date.today().year
    print(f"  Pulling season pitcher stats ({season})...")
    df = pb.pitching_stats_bref(season)

    starters = df[pd.to_numeric(df["GS"], errors="coerce") >= 3].copy()
    starters["IP_num"]   = pd.to_numeric(starters["IP"],  errors="coerce")
    starters["SO_num"]   = pd.to_numeric(starters["SO"],  errors="coerce")
    starters["ERA_num"]  = pd.to_numeric(starters["ERA"], errors="coerce")
    starters["GS_num"]   = pd.to_numeric(starters["GS"],  errors="coerce")
    starters["k_per_9"]  = starters["SO_num"] / starters["IP_num"] * 9
    starters["k_per_gs"] = starters["SO_num"] / starters["GS_num"]
    starters["k_adj"]    = (starters["k_per_9"] / LEAGUE_AVG_K9).clip(0.5, 2.0)

    return starters[["Name", "GS_num", "IP_num", "SO_num", "ERA_num", "k_per_9", "k_per_gs", "k_adj"]].rename(
        columns={"GS_num": "GS", "IP_num": "IP", "SO_num": "SO", "ERA_num": "ERA"}
    )


def pull_recent_pitcher_form() -> pd.DataFrame:
    end   = date.today()
    start = end - timedelta(days=RECENT_DAYS)
    print(f"  Pulling recent pitcher form {start} → {end} (~last 3 starts)...")
    try:
        df = pb.pitching_stats_range(str(start), str(end))
        starters = df[pd.to_numeric(df["GS"], errors="coerce") >= 1].copy()
        starters["SO_num"]        = pd.to_numeric(starters["SO"], errors="coerce")
        starters["GS_num"]        = pd.to_numeric(starters["GS"], errors="coerce")
        starters["IP_num"]        = pd.to_numeric(starters["IP"], errors="coerce")
        starters["recent_k_gs"]   = starters["SO_num"] / starters["GS_num"]
        starters["recent_k_9"]    = starters["SO_num"] / starters["IP_num"] * 9
        starters["recent_era"]    = pd.to_numeric(starters["ERA"], errors="coerce")
        return starters[["Name", "GS_num", "recent_k_gs", "recent_k_9", "recent_era"]].rename(
            columns={"GS_num": "recent_GS"}
        )
    except Exception as e:
        print(f"  Warning pulling recent pitcher form: {e}")
        return pd.DataFrame()


def blend_pitcher_stats(season_df: pd.DataFrame, recent_df: pd.DataFrame) -> pd.DataFrame:
    """
    Blend season K/GS with recent 3-start K/GS.
    60% recent, 40% season — same philosophy as batter form blending.
    """
    if recent_df.empty:
        season_df["blended_k_gs"]  = season_df["k_per_gs"]
        season_df["blended_k_9"]   = season_df["k_per_9"]
        season_df["recent_k_gs"]   = None
        season_df["recent_era"]    = None
        return season_df

    merged = season_df.merge(recent_df, on="Name", how="left")

    merged["blended_k_gs"] = merged.apply(
        lambda r: (
            RECENT_WEIGHT * r["recent_k_gs"] + SEASON_WEIGHT * r["k_per_gs"]
            if pd.notna(r.get("recent_k_gs")) else r["k_per_gs"]
        ), axis=1
    )
    merged["blended_k_9"] = merged.apply(
        lambda r: (
            RECENT_WEIGHT * r["recent_k_9"] + SEASON_WEIGHT * r["k_per_9"]
            if pd.notna(r.get("recent_k_9")) else r["k_per_9"]
        ), axis=1
    )
    # Recalculate k_adj from blended K/9
    merged["k_adj"] = (merged["blended_k_9"] / LEAGUE_AVG_K9).clip(0.5, 2.0)

    return merged


def save_pitcher_stats(df: pd.DataFrame):
    conn = get_conn()
    df.to_sql("pitcher_season_stats", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()
    print(f"  Saved {len(df)} pitcher profiles")


def get_pitcher_stats() -> pd.DataFrame:
    season_df = pull_pitcher_stats()
    recent_df = pull_recent_pitcher_form()
    blended   = blend_pitcher_stats(season_df, recent_df)
    save_pitcher_stats(blended)
    return blended


def lookup_pitcher(name: str, df: pd.DataFrame) -> dict:
    """Return a pitcher's blended matchup stats, falling back to league average."""
    default = {
        "k_per_9": LEAGUE_AVG_K9, "k_per_gs": LEAGUE_AVG_K_GS,
        "blended_k_gs": LEAGUE_AVG_K_GS, "era": LEAGUE_AVG_ERA, "k_adj": 1.0,
        "recent_k_gs": None, "recent_era": None,
    }
    if df.empty:
        return default

    match = df[df["Name"].str.lower() == name.lower()]
    if match.empty:
        last = name.split()[-1].lower()
        match = df[df["Name"].str.lower().str.contains(last, na=False)]

    if not match.empty:
        row = match.iloc[0]
        return {
            "k_per_9":      float(row["k_per_9"])      if pd.notna(row.get("k_per_9"))      else LEAGUE_AVG_K9,
            "k_per_gs":     float(row["k_per_gs"])     if pd.notna(row.get("k_per_gs"))     else LEAGUE_AVG_K_GS,
            "blended_k_gs": float(row["blended_k_gs"]) if pd.notna(row.get("blended_k_gs")) else LEAGUE_AVG_K_GS,
            "era":          float(row["ERA"])           if pd.notna(row.get("ERA"))          else LEAGUE_AVG_ERA,
            "k_adj":        float(row["k_adj"])         if pd.notna(row.get("k_adj"))        else 1.0,
            "recent_k_gs":  float(row["recent_k_gs"])  if pd.notna(row.get("recent_k_gs"))  else None,
            "recent_era":   float(row["recent_era"])   if pd.notna(row.get("recent_era"))   else None,
        }
    return default


if __name__ == "__main__":
    df = get_pitcher_stats()
    cols = ["Name", "GS", "k_per_gs", "recent_k_gs", "blended_k_gs", "k_per_9", "k_adj", "ERA"]
    available = [c for c in cols if c in df.columns]
    print(df[available].head(12).to_string())
