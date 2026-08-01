"""SQLite helpers for the OW Ban Room app."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "ow_ban.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rooms (
    code TEXT PRIMARY KEY,
    host_token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'voting',
    auto_reveal INTEGER NOT NULL DEFAULT 1,
    lobby_ban INTEGER NOT NULL DEFAULT 1,
    round_no INTEGER NOT NULL DEFAULT 1,
    round_seed TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    room_code TEXT NOT NULL,
    name TEXT NOT NULL,
    team TEXT NOT NULL CHECK (team IN ('A', 'B')),
    token TEXT NOT NULL UNIQUE,
    ready INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_code) REFERENCES rooms(code) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_players_room ON players(room_code);

CREATE TABLE IF NOT EXISTS votes (
    player_id TEXT NOT NULL,
    round_no INTEGER NOT NULL,
    rank_no INTEGER NOT NULL CHECK (rank_no BETWEEN 1 AND 3),
    hero TEXT NOT NULL,
    PRIMARY KEY (player_id, round_no, rank_no),
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_votes_round ON votes(round_no);
"""


def init_db(path: str | Path = DEFAULT_DB_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)


@contextmanager
def connect(path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
