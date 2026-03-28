"""Smoke tests for TaskStore (Feature 1: SQLite task metadata)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sage.memory.sqlite_store import TaskStore


@pytest.fixture
def tmp_store(tmp_path: Path) -> TaskStore:
    db = tmp_path / "tasks.db"
    return TaskStore(db_path=db)


def test_record_and_query_basic(tmp_store: TaskStore) -> None:
    tmp_store.record("task-001", agent="coder", model="gpt-4o", status="success", tokens_used=100)
    rows = tmp_store.query(since_days=0)
    assert len(rows) == 1
    row = rows[0]
    assert row["task_id"] == "task-001"
    assert row["agent"] == "coder"
    assert row["status"] == "success"
    assert row["tokens_used"] == 100


def test_upsert_on_task_id(tmp_store: TaskStore) -> None:
    tmp_store.record("task-dup", agent="reviewer", model="gpt-4o", status="success")
    tmp_store.record("task-dup", agent="reviewer", model="gpt-4o", status="failure", error="oops")
    rows = tmp_store.query(since_days=0)
    # Should be only one row due to upsert
    assert len(rows) == 1
    assert rows[0]["status"] == "failure"
    assert rows[0]["error_preview"] == "oops"


def test_query_filter_by_agent(tmp_store: TaskStore) -> None:
    tmp_store.record("t1", agent="coder", model="m", status="success")
    tmp_store.record("t2", agent="reviewer", model="m", status="success")
    rows = tmp_store.query(agent="coder", since_days=0)
    assert len(rows) == 1
    assert rows[0]["agent"] == "coder"


def test_query_filter_by_status(tmp_store: TaskStore) -> None:
    tmp_store.record("t1", agent="coder", model="m", status="success")
    tmp_store.record("t2", agent="coder", model="m", status="failure")
    failed = tmp_store.query(status="failure", since_days=0)
    assert len(failed) == 1
    assert failed[0]["status"] == "failure"


def test_summary_empty(tmp_store: TaskStore) -> None:
    s = tmp_store.summary(since_days=7)
    assert s["total_tasks"] == 0
    assert s["success_rate"] == 0.0
    assert s["total_tokens"] == 0
    assert s["top_errors"] == []


def test_summary_with_data(tmp_store: TaskStore) -> None:
    tmp_store.record("t1", agent="coder", model="m", status="success", tokens_used=50)
    tmp_store.record("t2", agent="coder", model="m", status="success", tokens_used=50)
    tmp_store.record("t3", agent="coder", model="m", status="failure", tokens_used=10, error="timeout")
    s = tmp_store.summary(since_days=7)
    assert s["total_tasks"] == 3
    assert abs(s["success_rate"] - 2 / 3) < 0.01
    assert s["total_tokens"] == 110
    assert "timeout" in s["top_errors"][0]


def test_summary_top_errors(tmp_store: TaskStore) -> None:
    for i in range(3):
        tmp_store.record(f"t{i}", agent="a", model="m", status="failure", error="ImportError: foo")
    tmp_store.record("t99", agent="a", model="m", status="failure", error="TimeoutError")
    s = tmp_store.summary(since_days=7)
    # top error should be the most common one
    assert s["top_errors"][0] == "ImportError: foo"


def test_db_path_auto_created(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "dir" / "tasks.db"
    store = TaskStore(db_path=nested)
    store.record("x", agent="a", model="m", status="success")
    assert nested.exists()
    store.close()


def test_thread_safety(tmp_store: TaskStore) -> None:
    import threading

    def worker(i: int) -> None:
        tmp_store.record(f"task-{i}", agent="bot", model="m", status="success")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = tmp_store.query(since_days=0)
    assert len(rows) == 20
