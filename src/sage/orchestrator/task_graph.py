"""
SAGE Task Graph Engine
----------------------
All work in SAGE is modelled as a DAG.
No agent acts outside the graph — this prevents multi-agent chaos.
"""

from dataclasses import dataclass, field
from sage.protocol.schemas import TaskNode


@dataclass
class TaskGraph:
    nodes: list[TaskNode] = field(default_factory=list)

    def add_node(self, node: TaskNode) -> None:
        self.nodes.append(node)

    def get(self, task_id: str) -> TaskNode | None:
        return next((n for n in self.nodes if n.id == task_id), None)

    def get_ready_tasks(self) -> list[TaskNode]:
        """Return tasks whose dependencies are all completed."""
        return [
            task
            for task in self.nodes
            if task.status == "pending"
            and all(
                (self.get(dep) and self.get(dep).status == "completed") for dep in task.dependencies
            )
        ]

    def all_done(self) -> bool:
        return all(n.status in ("completed", "blocked", "failed") for n in self.nodes)

    def to_dict(self) -> dict:
        return {"nodes": [vars(n) for n in self.nodes]}
