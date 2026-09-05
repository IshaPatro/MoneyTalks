"""Tiny SQLite-backed memory of user-confirmed explanations.

Schema (README section 13):
    id, account, entity, period, explanation, confirmed, created_at

This is intentionally dumb: no embeddings, no vector search. "Similar prior
record" just means same account (optionally same entity), most recent first.
The historical context this returns is a hint for the LLM's narrative --
it never overrides or replaces what current transaction data shows.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "memory.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS confirmed_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    entity TEXT,
    period TEXT NOT NULL,
    explanation TEXT NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""


@dataclass
class ConfirmedContext:
    id: int
    account: str
    entity: Optional[str]
    period: str
    explanation: str
    confirmed: bool
    created_at: str


class MemoryStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_confirmed_context(
        self,
        account: str,
        period: str,
        explanation: str,
        entity: Optional[str] = None,
        confirmed: bool = True,
    ) -> ConfirmedContext:
        """Persist a user-confirmed (or user-corrected) explanation.

        Corrections are handled the same way as confirmations: the caller
        passes the corrected explanation text and it's stored as a new
        confirmed record, so future runs retrieve the corrected version.
        """
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO confirmed_context
                    (account, entity, period, explanation, confirmed, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (account, entity, period, explanation, int(confirmed), created_at),
            )
            row_id = cur.lastrowid
        return ConfirmedContext(
            id=row_id, account=account, entity=entity, period=period,
            explanation=explanation, confirmed=confirmed, created_at=created_at,
        )

    def get_previous_context(
        self,
        account: str,
        period: str,
        entity: Optional[str] = None,
        limit: int = 5,
    ) -> list[ConfirmedContext]:
        """Return confirmed explanations for this account (optionally this
        entity) from periods before `period`, most recent first."""
        query = (
            "SELECT * FROM confirmed_context "
            "WHERE account = ? AND confirmed = 1 AND period < ?"
        )
        params: list = [account, period]
        if entity is not None:
            query += " AND entity = ?"
            params.append(entity)
        query += " ORDER BY period DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ConfirmedContext(
                id=r["id"], account=r["account"], entity=r["entity"],
                period=r["period"], explanation=r["explanation"],
                confirmed=bool(r["confirmed"]), created_at=r["created_at"],
            )
            for r in rows
        ]


_default_store: Optional[MemoryStore] = None


def _default() -> MemoryStore:
    global _default_store
    if _default_store is None:
        _default_store = MemoryStore()
    return _default_store


def save_confirmed_context(
    account: str,
    period: str,
    explanation: str,
    entity: Optional[str] = None,
    confirmed: bool = True,
) -> ConfirmedContext:
    return _default().save_confirmed_context(
        account, period, explanation, entity=entity, confirmed=confirmed
    )


def get_previous_context(
    account: str, period: str, entity: Optional[str] = None, limit: int = 5
) -> list[ConfirmedContext]:
    return _default().get_previous_context(account, period, entity=entity, limit=limit)
