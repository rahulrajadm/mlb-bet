import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/mlb_bet.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_starter TEXT,
            away_starter TEXT,
            venue TEXT,
            game_time TEXT
        );

        CREATE TABLE IF NOT EXISTS game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER,
            home_starter TEXT,
            away_starter TEXT,
            home_win INTEGER,
            total_runs INTEGER,
            run_diff INTEGER
        );

        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            player_name TEXT,
            player_id TEXT,
            team TEXT,
            game_id TEXT,
            stat_type TEXT,
            stat_value REAL
        );

        CREATE TABLE IF NOT EXISTS statcast (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT,
            player_id TEXT,
            season INTEGER,
            pa INTEGER,
            k_pct REAL,
            bb_pct REAL,
            barrel_pct REAL,
            hard_hit_pct REAL,
            woba REAL,
            xwoba REAL,
            avg_exit_velo REAL,
            player_type TEXT
        );

        CREATE TABLE IF NOT EXISTS prop_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT,
            platform TEXT,
            game_id TEXT,
            player_name TEXT,
            player_team TEXT,
            stat_type TEXT,
            line REAL,
            more_odds REAL,
            less_odds REAL
        );

        CREATE TABLE IF NOT EXISTS game_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT,
            platform TEXT,
            game_id TEXT,
            home_team TEXT,
            away_team TEXT,
            market TEXT,
            home_odds REAL,
            away_odds REAL,
            over_odds REAL,
            under_odds REAL,
            total_line REAL
        );

        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at TEXT,
            pick_type TEXT,
            selection TEXT,
            best_platform TEXT,
            model_prob REAL,
            implied_prob REAL,
            edge REAL,
            ev_per_100 REAL,
            confidence_tier TEXT,
            risk_profile TEXT,
            kelly_pct REAL,
            payout_multiplier REAL,
            details TEXT
        );
    """)

    conn.commit()
    conn.close()
    print("Database initialized.")


if __name__ == "__main__":
    init_db()
