"""
SAGE Task Scheduler
-------------------
Controls execution order and enforces parallelism limits.
Without this, all tasks start simultaneously and the system collapses.
"""

from sage.protocol.schemas import TaskNode
from sage.orchestrator.task_graph import TaskGraph

MAX_PARALLEL = 3
MAX_QUEUE_SIZE = 10


class TaskScheduler:
    def schedule_next(self, dag: TaskGraph, running: list[TaskNode]) -> list[TaskNode]:
        """Schedule up to MAX_PARALLEL tasks."""
        slots = MAX_PARALLEL - len(running)
        if slots <= 0:
            return []
        ready = dag.get_ready_tasks()
        return ready[:slots]
