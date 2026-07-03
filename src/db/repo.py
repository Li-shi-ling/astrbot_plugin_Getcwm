from __future__ import annotations

import asyncio
import sqlite3

from .database import DBManager


class SubscribeRepo:
    def __init__(self, db_manager: DBManager):
        self.db = db_manager

    async def load_state(self) -> dict[str, dict]:
        await self.db.init_db()
        return await asyncio.to_thread(self._load_state_sync)

    def _load_state_sync(self) -> dict[str, dict]:
        b2u: dict[int, list[str]] = {}
        bmeta: dict[int, dict] = {}

        with self.db._connect() as conn:
            subscription_rows = conn.execute(
                """
                SELECT source, book_id, session_id
                FROM cwm_subscription
                ORDER BY source, book_id, session_id
                """
            ).fetchall()
            for row in subscription_rows:
                book_id = int(row["book_id"])
                source = str(row["source"] or "cwm").strip() or "cwm"
                session_id = str(row["session_id"]).strip()
                if not session_id:
                    continue
                b2u.setdefault(book_id, []).append(session_id)
                bmeta.setdefault(book_id, {})["source"] = source

            meta_rows = conn.execute(
                """
                SELECT source, book_id, title_text, timestamp, chapter
                FROM cwm_book_meta
                ORDER BY source, book_id
                """
            ).fetchall()
            for row in meta_rows:
                book_id = int(row["book_id"])
                bmeta[book_id] = {
                    "source": str(row["source"] or "cwm").strip() or "cwm",
                    "title_text": str(row["title_text"] or ""),
                    "timestamp": int(row["timestamp"] or 0),
                    "chapter": str(row["chapter"] or ""),
                }

        u2b: dict[str, list[int]] = {}
        for book_id, sessions in b2u.items():
            for session_id in sessions:
                u2b.setdefault(session_id, []).append(book_id)

        return {"b2u": b2u, "u2b": u2b, "bmeta": bmeta}

    async def replace_state(
        self, b2u: dict[int, list[str]], bmeta: dict[int, dict]
    ) -> None:
        await self.db.init_db()
        await asyncio.to_thread(self._replace_state_sync, b2u, bmeta)

    def _replace_state_sync(
        self, b2u: dict[int, list[str]], bmeta: dict[int, dict]
    ) -> None:
        subscription_rows: list[tuple[str, int, str]] = []
        for book_id, sessions in b2u.items():
            source = str((bmeta.get(int(book_id), {}) or {}).get("source") or "cwm")
            for session_id in sessions:
                normalized_session = str(session_id).strip()
                if normalized_session:
                    subscription_rows.append((source, int(book_id), normalized_session))

        meta_rows: list[tuple[str, int, str, int, str]] = []
        for book_id, meta in bmeta.items():
            source = str(meta.get("source", "") or "cwm").strip() or "cwm"
            meta_rows.append(
                (
                    source,
                    int(book_id),
                    str(meta.get("title_text", "") or ""),
                    int(meta.get("timestamp", 0) or 0),
                    str(meta.get("chapter", "") or ""),
                )
            )

        with self.db._connect() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute("DELETE FROM cwm_subscription")
                conn.execute("DELETE FROM cwm_book_meta")
                if subscription_rows:
                    conn.executemany(
                        """
                        INSERT INTO cwm_subscription (source, book_id, session_id)
                        VALUES (?, ?, ?)
                        """,
                        subscription_rows,
                    )
                if meta_rows:
                    conn.executemany(
                        """
                        INSERT INTO cwm_book_meta (source, book_id, title_text, timestamp, chapter)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        meta_rows,
                    )
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise

    async def has_any_data(self) -> bool:
        await self.db.init_db()
        return await asyncio.to_thread(self._has_any_data_sync)

    def _has_any_data_sync(self) -> bool:
        with self.db._connect() as conn:
            sub_count = conn.execute(
                "SELECT COUNT(1) FROM cwm_subscription"
            ).fetchone()[0]
            meta_count = conn.execute("SELECT COUNT(1) FROM cwm_book_meta").fetchone()[
                0
            ]
        return bool(sub_count or meta_count)
