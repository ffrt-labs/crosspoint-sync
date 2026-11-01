"""SQLite storage. Every session row is kept; `latest` derives the current position."""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from progress_endpoint.events import MAX_BP, ReaderSession

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    start_bp INTEGER NOT NULL,
    end_bp INTEGER NOT NULL,
    duration_s INTEGER NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    received_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_document ON sessions (document, end_time);
CREATE VIEW IF NOT EXISTS latest AS
SELECT document, end_bp, end_time, ts, received_at, seq FROM (
    SELECT *, rowid AS seq, row_number() OVER (
        PARTITION BY document ORDER BY end_time DESC, ts DESC, rowid DESC
    ) AS rank
    FROM sessions
)
WHERE rank = 1;
"""

SESSION_COLUMNS = [field.name for field in fields(ReaderSession)] + ["received_at"]
INSERT_SESSION = f"""
INSERT INTO sessions ({", ".join(SESSION_COLUMNS)})
VALUES ({", ".join(f":{column}" for column in SESSION_COLUMNS)})
ON CONFLICT (id) DO NOTHING
"""


@dataclass(frozen=True)
class Position:
    """Where a document was left: the row `latest` picks for it."""

    document: str
    end_bp: int
    end_time: int
    ts: int
    received_at: int

    @property
    def progress(self) -> float:
        return self.end_bp / MAX_BP

    def as_json(self) -> dict:
        return asdict(self) | {"progress": self.progress}


POSITION_COLUMNS = ", ".join(field.name for field in fields(Position))


class Store:
    def __init__(self, path: Path):
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # One connection per operation: handlers run on different threads.
        db = sqlite3.connect(self._path, timeout=5, autocommit=True)
        try:
            db.row_factory = sqlite3.Row
            yield db
        finally:
            db.close()

    def add_session(self, session: ReaderSession) -> bool:
        """Store a session. Returns False for a replayed id; the first copy wins."""
        with self._connect() as db:
            cursor = db.execute(
                INSERT_SESSION,
                asdict(session) | {"received_at": int(time.time())},
            )
            return cursor.rowcount == 1

    def latest(self) -> list[Position]:
        """Latest position per document, most recently read first."""
        with self._connect() as db:
            rows = db.execute(
                f"SELECT {POSITION_COLUMNS} FROM latest ORDER BY end_time DESC, ts DESC, seq DESC"
            )
            return [Position(**row) for row in rows]

    def latest_for(self, document: str) -> Position | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT {POSITION_COLUMNS} FROM latest WHERE document = ?", (document,)
            ).fetchone()
            return Position(**row) if row else None

    def check(self) -> None:
        """Raises sqlite3.Error if the database cannot be read or written."""
        with self._connect() as db:
            db.execute("SELECT 1 FROM sessions LIMIT 1").fetchone()
            # A write that is rolled back. BEGIN IMMEDIATE alone is not enough: on a WAL
            # database it succeeds for a read-only file, and only touching a page fails.
            db.execute("BEGIN IMMEDIATE")
            db.execute("PRAGMA user_version = 0")
            db.execute("ROLLBACK")
