from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path


class DBManager:
    _CREATE_TABLE_SQL = (
        """
        CREATE TABLE IF NOT EXISTS cwm_subscription (
            source TEXT NOT NULL DEFAULT 'cwm',
            book_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            PRIMARY KEY (source, book_id, session_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cwm_book_meta (
            source TEXT NOT NULL DEFAULT 'cwm',
            book_id INTEGER NOT NULL,
            title_text TEXT NOT NULL DEFAULT '',
            timestamp INTEGER NOT NULL DEFAULT 0,
            chapter TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (source, book_id)
        )
        """,
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
            self._migrate_source_schema(conn)
            self._create_indexes(conn)
            conn.commit()

    def _create_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cwm_subscription_session_id ON cwm_subscription(session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cwm_subscription_source_book_id ON cwm_subscription(source, book_id)"
        )

    def _migrate_source_schema(self, conn: sqlite3.Connection) -> None:
        sub_cols = conn.execute("PRAGMA table_info(cwm_subscription)").fetchall()
        meta_cols = conn.execute("PRAGMA table_info(cwm_book_meta)").fetchall()

        sub_has_source = any(row["name"] == "source" for row in sub_cols)
        meta_has_source = any(row["name"] == "source" for row in meta_cols)
        sub_pk = [row["name"] for row in sorted(sub_cols, key=lambda row: row["pk"]) if row["pk"]]
        meta_pk = [row["name"] for row in sorted(meta_cols, key=lambda row: row["pk"]) if row["pk"]]

        if sub_has_source and meta_has_source and sub_pk == ["source", "book_id", "session_id"] and meta_pk == ["source", "book_id"]:
            return

        conn.execute("ALTER TABLE cwm_subscription RENAME TO cwm_subscription_legacy")
        conn.execute("ALTER TABLE cwm_book_meta RENAME TO cwm_book_meta_legacy")

        conn.execute(
            """
            CREATE TABLE cwm_subscription (
                source TEXT NOT NULL DEFAULT 'cwm',
                book_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                PRIMARY KEY (source, book_id, session_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE cwm_book_meta (
                source TEXT NOT NULL DEFAULT 'cwm',
                book_id INTEGER NOT NULL,
                title_text TEXT NOT NULL DEFAULT '',
                timestamp INTEGER NOT NULL DEFAULT 0,
                chapter TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (source, book_id)
            )
            """
        )

        legacy_sub_source = "source" if sub_has_source else "'cwm'"
        legacy_meta_source = "source" if meta_has_source else "'cwm'"
        conn.execute(
            f"""
            INSERT OR IGNORE INTO cwm_subscription (source, book_id, session_id)
            SELECT COALESCE(NULLIF({legacy_sub_source}, ''), 'cwm'), book_id, session_id
            FROM cwm_subscription_legacy
            """
        )
        conn.execute(
            f"""
            INSERT OR REPLACE INTO cwm_book_meta (source, book_id, title_text, timestamp, chapter)
            SELECT COALESCE(NULLIF({legacy_meta_source}, ''), 'cwm'), book_id, title_text, timestamp, chapter
            FROM cwm_book_meta_legacy
            """
        )

        conn.execute("DROP TABLE cwm_subscription_legacy")
        conn.execute("DROP TABLE cwm_book_meta_legacy")
