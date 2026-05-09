from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path


class DBManager:
    _CREATE_TABLE_SQL = (
        """
        CREATE TABLE IF NOT EXISTS cwm_subscription (
            book_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            PRIMARY KEY (book_id, session_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cwm_book_meta (
            book_id INTEGER PRIMARY KEY,
            title_text TEXT NOT NULL DEFAULT '',
            timestamp INTEGER NOT NULL DEFAULT 0,
            chapter TEXT NOT NULL DEFAULT ''
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_cwm_subscription_session_id ON cwm_subscription(session_id)",
    )

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def init_db(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._init_db_sync)
            self._initialized = True

    def _init_db_sync(self) -> None:
        with self._connect() as conn:
            for sql in self._CREATE_TABLE_SQL:
                conn.execute(sql)
            conn.commit()
