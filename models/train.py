"""
Builds per-player per-game rate profiles from historical data.
Joins season stats with Statcast quality indicators.
Saves serialized player profiles to data/ for use by the prediction engine.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
import joblib
from utils.db import get_conn
from utils.names import clean_name

MODELS_DIR = os.path.join(os.path.dirname(__file__), "../data/models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Recency weights over the seasons present in batter_game_logs
# (kept in sync with pipeline/historical.py SEASONS)
SEASON_WEIGHTS = {2024: 0.15, 2025: 0.30, 2026: 0.55}


def load_batter_logs() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM batter_game_logs", conn)
    conn.close()
    df = df[df["Lev"].str.startswith("Maj")].copy()
    df["season"] = df["season"].astype(int)
    df["Name"] = df["Name"].map(clean_name)  # B-Ref names arrive mojibake'd
    return df


def load_statcast_batters() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM statcast_batters", conn)
    conn.close()
    df.rename(columns={"last_name, first_name": "name_raw"}, inplace=True)
    df["season"] = df["season"].astype(int)
    return df


def load_statcast_pitchers() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM statcast_pitchers", conn)
    conn.close()
    df.rename(columns={"last_name, first_name": "name_raw"}, inplace=True)
    df["season"] = df["season"].astype(int)
    return df


def build_batter_profiles(logs: pd.DataFrame, statcast: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-game stat rates per player per season, then blend seasons
    using recency weights. Join with Statcast quality indicators.
    """
    logs = logs[logs["G"] >= 10].copy()

    rate_cols = {
        "hits_pg": ("H", "G"),
        "hr_pg": ("HR", "G"),
        "rbi_pg": ("RBI", "G"),
        "runs_pg": ("R", "G"),
        "bb_pg": ("BB", "G"),
        "so_pg": ("SO", "G"),
        "sb_pg": ("SB", "G"),
        "doubles_pg": ("2B", "G"),
        "singles_pg": (None, None),  # computed below
        "tb_pg": (None, None),       # computed below
        "h_r_rbi_pg": (None, None),  # computed below
    }

    logs["singles"] = logs["H"] - logs["2B"] - logs["3B"] - logs["HR"]
    logs["tb"] = logs["H"] + logs["2B"] + 2 * logs["3B"] + 3 * logs["HR"]
    logs["h_r_rbi"] = logs["H"] + logs["R"] + logs["RBI"]

    for col, (num, denom) in [
        ("hits_pg", ("H", "G")),
        ("hr_pg", ("HR", "G")),
        ("rbi_pg", ("RBI", "G")),
        ("runs_pg", ("R", "G")),
        ("bb_pg", ("BB", "G")),
        ("so_pg", ("SO", "G")),
        ("sb_pg", ("SB", "G")),
        ("doubles_pg", ("2B", "G")),
        ("singles_pg", ("singles", "G")),
        ("tb_pg", ("tb", "G")),
        ("h_r_rbi_pg", ("h_r_rbi", "G")),
    ]:
        logs[col] = logs[num] / logs[denom].replace(0, np.nan)

    rate_feature_cols = [
        "hits_pg", "hr_pg", "rbi_pg", "runs_pg", "bb_pg", "so_pg",
        "sb_pg", "doubles_pg", "singles_pg", "tb_pg", "h_r_rbi_pg",
        "BA", "OBP", "SLG", "OPS",
    ]

    profiles = []
    for name, grp in logs.groupby("Name"):
        weighted_rows = []
        for _, row in grp.iterrows():
            season = row["season"]
            w = SEASON_WEIGHTS.get(season, 0.1)
            weighted_rows.append((w, row))

        blended = {}
        for col in rate_feature_cols:
            # Normalize by the weights actually present for THIS column, so a
            # season with a missing value doesn't drag the average toward 0.
            pairs = [(w, row[col]) for w, row in weighted_rows if pd.notna(row.get(col))]
            col_w = sum(w for w, _ in pairs)
            blended[col] = sum(w * v for w, v in pairs) / col_w if col_w > 0 else np.nan

        latest = grp.sort_values("season").iloc[-1]
        blended["Name"] = name
        blended["Team"] = latest.get("Tm", "")
        blended["mlbID"] = latest.get("mlbID", "")
        blended["games_sample"] = grp["G"].sum()
        profiles.append(blended)

    profiles_df = pd.DataFrame(profiles)

    # Join Statcast quality indicators (latest season available)
    statcast_latest = statcast.sort_values("season").groupby("player_id").last().reset_index()
    statcast_latest["Name_clean"] = statcast_latest["name_raw"].apply(
        lambda x: clean_name(" ".join(reversed(x.split(", "))) if ", " in str(x) else str(x))
    )

    statcast_feats = statcast_latest[[
        "Name_clean", "avg_hit_speed", "brl_percent", "brl_pa", "ev95percent"
    ]].rename(columns={"Name_clean": "Name"})

    profiles_df = profiles_df.merge(statcast_feats, on="Name", how="left")
    return profiles_df


def build_pitcher_profiles(statcast_pitchers: pd.DataFrame) -> pd.DataFrame:
    """
    Build per-start rate profiles for pitchers from Statcast allowed metrics.
    K rate comes from Odds API game lines + external pitching data.
    """
    statcast_pitchers["Name_clean"] = statcast_pitchers["name_raw"].apply(
        lambda x: clean_name(" ".join(reversed(x.split(", "))) if ", " in str(x) else str(x))
    )

    pitcher_latest = statcast_pitchers.sort_values("season").groupby("Name_clean").last().reset_index()

    pitcher_profiles = pitcher_latest[[
        "Name_clean", "avg_hit_speed", "brl_percent", "brl_pa", "ev95percent", "season"
    ]].rename(columns={"Name_clean": "Name"})

    return pitcher_profiles


def main():
    print("Loading data...")
    logs = load_batter_logs()
    statcast_b = load_statcast_batters()
    statcast_p = load_statcast_pitchers()

    print(f"  Batter logs: {len(logs)} player-seasons")
    print(f"  Statcast batters: {len(statcast_b)} rows")
    print(f"  Statcast pitchers: {len(statcast_p)} rows")

    print("Building batter profiles...")
    batter_profiles = build_batter_profiles(logs, statcast_b)
    print(f"  Built profiles for {len(batter_profiles)} batters")

    print("Building pitcher profiles...")
    pitcher_profiles = build_pitcher_profiles(statcast_p)
    print(f"  Built profiles for {len(pitcher_profiles)} pitchers")

    batter_path = os.path.join(MODELS_DIR, "batter_profiles.pkl")
    pitcher_path = os.path.join(MODELS_DIR, "pitcher_profiles.pkl")
    joblib.dump(batter_profiles, batter_path)
    joblib.dump(pitcher_profiles, pitcher_path)

    print(f"\nSaved:")
    print(f"  {batter_path}")
    print(f"  {pitcher_path}")
    print("\nTraining complete.")


if __name__ == "__main__":
    main()
