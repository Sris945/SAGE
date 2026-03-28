"""
SAGE SQLite Task Store
----------------------
Persistent task execution history alongside JSON flat files.
Enables richer queries than JSON allows: filter by agent, date range,
success/failure, token cost, error type.

Schema:
  tasks(id, task_id, agent, model, status, tokens_used, error_preview,
        timestamp, session_date)
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class TaskStore:
    """Persistent SQLite store for task execution history."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path("memory") / "tasks.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id      TEXT    NOT NULL,
                    agent        TEXT    NOT NULL DEFAULT '',
                    model        TEXT    NOT NULL DEFAULT '',
                    status       TEXT    NOT NULL DEFAULT '',
                    tokens_used  INTEGER NOT NULL DEFAULT 0,
                    error_preview TEXT   NOT NULL DEFAULT '',
                    timestamp    TEXT    NOT NULL,
                    session_date TEXT    NOT NULL,
                    UNIQUE(task_id)
                )
                """
            )
            self._conn.commit()

    def record(
        self,
        task_id: str,
        agent: str,
        model: str,
        status: str,
        tokens_used: int = 0,
        error: str = "",
    ) -> None:
        """Upsert a task record (INSERT OR REPLACE on task_id)."""
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        session_date = now.strftime("%Y-%m-%d")
        error_preview = (error or "")[:500]
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO tasks
                    (task_id, agent, model, status, tokens_used, error_preview,
                     timestamp, session_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    agent,
                    model,
                    status,
                    tokens_used,
                    error_preview,
                    timestamp,
                    session_date,
                ),
            )
            self._conn.commit()

    def query(
        self,
        agent: str | None = None,
        status: str | None = None,
        since_days: int = 7,
    ) -> list[dict]:
        """
        Return task records filtered by agent, status, and recency.
        since_days=0 means no date filter.
        """
        clauses: list[str] = []
        params: list[object] = []

        if since_days and since_days > 0:
            from datetime import timedelta

            cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
            clauses.append("session_date >= ?")
            params.append(cutoff)

        if agent is not None:
            clauses.append("agent = ?")
            params.append(agent)

        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM tasks {where} ORDER BY timestamp DESC"

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]

    def summary(self, since_days: int = 7) -> dict:
        """
        Return aggregated stats:
          {total_tasks, success_rate, total_tokens, top_errors: [str]}
        """
        rows = self.query(since_days=since_days)
        total = len(rows)
        if total == 0:
            return {
                "total_tasks": 0,
                "success_rate": 0.0,
                "total_tokens": 0,
                "top_errors": [],
            }

        success_count = sum(1 for r in rows if r.get("status", "").lower() == "success")
        total_tokens = sum(int(r.get("tokens_used", 0) or 0) for r in rows)

        # Collect non-empty error previews and count them
        from collections import Counter

        error_counter: Counter[str] = Counter()
        for r in rows:
            ep = (r.get("error_preview") or "").strip()
            if ep:
                # Truncate to first 120 chars for readability
                error_counter[ep[:120]] += 1

        top_errors = [msg for msg, _ in error_counter.most_common(5)]

        return {
            "total_tasks": total,
            "success_rate": success_count / total,
            "total_tokens": total_tokens,
            "top_errors": top_errors,
        }

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()
