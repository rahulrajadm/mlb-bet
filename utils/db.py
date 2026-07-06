import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/mlb_bet.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    _migrate(conn)
    return conn


def _migrate(conn):
    """Additive migrations for DBs created before a column existed."""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(prop_lines)")]
        if cols and "odds_type" not in cols:
            conn.execute("ALTER TABLE prop_lines ADD COLUMN odds_type TEXT")
            conn.commit()
    except sqlite3.Error:
        pass


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

        CREATE TABLE IF NOT EXISTS prop_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT,
            platform TEXT,
            game_id TEXT,
            player_name TEXT,
            player_team TEXT,
            stat_type TEXT,
            line REAL,
            odds_type TEXT,
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
    """)

    conn.commit()
    conn.close()
    print("Database initialized.")


if __name__ == "__main__":
    init_db()
