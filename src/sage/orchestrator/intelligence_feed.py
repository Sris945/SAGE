"""
Orchestrator Intelligence Feed (MVP)
-------------------------------------
Buffers AgentInsight packets and determines whether orchestration should
intervene.

This MVP focuses on ingestion + logging. Future phases can implement
pre-emptive reassignments and prompt injection.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading

from sage.protocol.schemas import AgentInsight


@dataclass
class OrchestratorIntelligenceFeed:
    uncertainty_count: int = 3
    high_severity_count: int = 1
    risk_accumulation: float = 0.7

    insights: list[AgentInsight] = field(default_factory=list)
    interventions: list[dict] = field(default_factory=list)
    _unclear_escalated_task_ids: set[str] = field(default_factory=set, repr=False)
    _risk_by_task: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, init=False)

    SEVERITY_WEIGHT: dict[str, float] = field(
        default_factory=lambda: {"low": 0.12, "medium": 0.35, "high": 0.65}
    )

    # Active orchestration fields
    pending_context: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    _high_severity_task_ids: set[str] = field(default_factory=set, repr=False)
    _consumed_note_indices: dict[str, int] = field(default_factory=dict, repr=False)

    def _unclear_signal_count(self, task_id: str) -> int:
        n = 0
        for ins in self.insights:
            if getattr(ins, "task_id", "") != task_id:
                continue
            flag = (getattr(ins, "epistemic_flag", "") or "").upper()
            if "UNCLEAR" in flag:
                n += 1
                continue
            if getattr(ins, "insight_type", "") == "uncertainty":
                n += 1
        return n

    def _emit_intervention_event(
        self, insight: AgentInsight, *, cause: str, action_taken: str = "emit_event"
    ) -> None:
        try:
            from sage.orchestrator.workflow import EVENT_BUS
            from sage.protocol.schemas import Event

            EVENT_BUS.emit_sync(
                Event(
                    type="ORCHESTRATOR_INTERVENTION",
                    task_id=insight.task_id,
                    payload={
                        "cause": cause,
                        "action_taken": action_taken,
                        "agent": insight.agent,
                        "severity": insight.severity,
                        "requires_orchestrator_action": insight.requires_orchestrator_action,
                        "content_preview": (insight.content or "")[:500],
                    },
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
        except Exception:
            return

    def _annotate_downstream(self, insight: AgentInsight) -> None:
        """Append a pending note for medium-severity insights."""
        tid = str(insight.task_id or "")
        note = f"ORCHESTRATOR_NOTE [{insight.agent}]: {(insight.content or '')[:300]}"
        self.pending_context[tid].append(note)

    def _intervene(self, insight: AgentInsight) -> None:
        """Handle high-severity or requires_orchestrator_action insights."""
        tid = str(insight.task_id or "")
        # Emit the ORCHESTRATOR_INTERVENTION event
        self._emit_intervention_event(
            insight, cause="agent_insight", action_taken="log_and_event_bus"
        )
        # Track high-severity task IDs
        self._high_severity_task_ids.add(tid)
        # Also append a note to pending_context
        note = f"ORCHESTRATOR_NOTE [{insight.agent}]: {(insight.content or '')[:300]}"
        self.pending_context[tid].append(note)

    def get_pending_notes(self, task_id: str) -> list[str]:
        """Return all accumulated ORCHESTRATOR_NOTE strings not yet consumed.

        After calling this, marks them as consumed so they don't repeat.
        """
        notes = self.pending_context.get(task_id) or []
        consumed_idx = self._consumed_note_indices.get(task_id, 0)
        new_notes = notes[consumed_idx:]
        if new_notes:
            self._consumed_note_indices[task_id] = len(notes)
        return list(new_notes)

    def ingest(self, insight: AgentInsight) -> None:
        """Ingest an insight packet and decide whether to intervene."""
        with self._lock:
            # Ensure timestamp exists.
            if not insight.timestamp:
                insight.timestamp = datetime.now(timezone.utc).isoformat()

            self.insights.append(insight)

            # Composite risk (0–1) for model pre-emption / routing.
            tid_r = str(insight.task_id or "")
            if tid_r:
                sev = (insight.severity or "low").lower()
                w = float(self.SEVERITY_WEIGHT.get(sev, 0.15))
                if bool(insight.requires_orchestrator_action):
                    w = min(1.0, w + 0.15)
                prev = float(self._risk_by_task.get(tid_r, 0.0))
                self._risk_by_task[tid_r] = min(1.0, prev + w * 0.25)

            # Spec §11: escalate after repeated UNCLEAR / uncertainty on the same task.
            tid = str(insight.task_id or "")
            if tid and self._unclear_signal_count(tid) >= self.uncertainty_count:
                if tid not in self._unclear_escalated_task_ids:
                    self._unclear_escalated_task_ids.add(tid)
                    self.interventions.append(
                        {
                            "task_id": tid,
                            "agent": "orchestrator",
                            "severity": "high",
                            "insight_type": "unclear_threshold",
                            "content": (
                                f"Task {tid}: {self.uncertainty_count}+ uncertainty/UNCLEAR signals "
                                "— escalate to human checkpoint in research/auto modes."
                            ),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "requires_orchestrator_action": True,
                        }
                    )
                    self._emit_intervention_event(
                        insight, cause="unclear_threshold", action_taken="escalate_human_checkpoint"
                    )

            # Phase 3 contract: emit a log entry for every ingested packet.
            # Observability must be best-effort and never break orchestration.
            try:
                from sage.observability.structured_logger import log_event

                log_event(
                    "AGENT_INSIGHT_EMITTED",
                    payload={
                        "task_id": insight.task_id,
                        "agent": insight.agent,
                        "insight_type": insight.insight_type,
                        "severity": insight.severity,
                        "requires_orchestrator_action": insight.requires_orchestrator_action,
                        "epistemic_flag": insight.epistemic_flag,
                        # Bounded content to keep payload size stable.
                        "content_preview": (insight.content or "")[:500],
                    },
                    timestamp=insight.timestamp,
                )
            except Exception:
                pass

            # MVP: record medium/high notes and anything that explicitly requires action.
            if insight.severity in ("medium", "high") or insight.requires_orchestrator_action:
                self.interventions.append(
                    {
                        "task_id": insight.task_id,
                        "agent": insight.agent,
                        "severity": insight.severity,
                        "insight_type": insight.insight_type,
                        "content": insight.content,
                        "timestamp": insight.timestamp,
                        "requires_orchestrator_action": insight.requires_orchestrator_action,
                    }
                )

            # Active orchestration: annotate or intervene based on severity
            if insight.severity == "medium":
                self._annotate_downstream(insight)
            elif insight.severity == "high" or bool(insight.requires_orchestrator_action):
                self._intervene(insight)

    def get_injected_context(self, task_id: str, *, next_agent: str | None = None) -> str:
        """
        Convert buffered insights into an ORCHESTRATOR NOTE block.

        MVP: include all ingested insights for `task_id` (full stream).
        Escalation decisions still come from the intervention buffer.

        `next_agent` is currently unused but kept for future selective injection.
        """
        with self._lock:
            notes: list[str] = []
            max_notes = 10
            for insight in self.insights:
                if getattr(insight, "task_id", "") != task_id:
                    continue
                content = getattr(insight, "content", "") or ""
                if not content.strip():
                    continue
                agent = getattr(insight, "agent", "") or "unknown_agent"
                itype = getattr(insight, "insight_type", "") or "observation"
                sev = getattr(insight, "severity", "") or "low"
                notes.append(f"ORCHESTRATOR_NOTE [{agent} {itype}/{sev}]: {content}")
                if len(notes) >= max_notes:
                    break
            return "\n".join(notes)

    def should_escalate(self, task_id: str) -> bool:
        """
        Escalate if we have any intervention for this task that is high severity
        or explicitly requires orchestrator action. Also escalates if task has
        any high-severity insight that hasn't been acknowledged.
        """
        with self._lock:
            # Check high-severity task set first (fast path)
            if task_id in self._high_severity_task_ids:
                return True
            for it in self.interventions:
                if it.get("task_id") != task_id:
                    continue
                if it.get("severity") == "high" or it.get("requires_orchestrator_action"):
                    return True
            return False

    def should_require_human(self, task_id: str) -> bool:
        """
        Return True if the Intel Feed requested explicit human action.

        Spec intent:
          - Insight escalation checkpoint (type 5) triggers when
            `requires_orchestrator_action` is true.
        """
        with self._lock:
            for it in self.interventions:
                if it.get("task_id") != task_id:
                    continue
                if it.get("requires_orchestrator_action"):
                    return True
            return False

    def task_risk_rank(self, task_id: str) -> float:
        """
        Composite risk score for scheduling prioritization.

        Returns sum of severity weights for all insights on this task.
        Higher score means higher priority / riskier task.
        """
        with self._lock:
            total = 0.0
            for ins in self.insights:
                if getattr(ins, "task_id", "") != task_id:
                    continue
                sev = (getattr(ins, "severity", "") or "low").lower()
                total += float(self.SEVERITY_WEIGHT.get(sev, 0.12))
                if bool(getattr(ins, "requires_orchestrator_action", False)):
                    total += 0.15
            return total

    def risk_score(self, task_id: str) -> float:
        """Composite risk in [0, 1] for the task."""
        with self._lock:
            return float(self._risk_by_task.get(task_id, 0.0))

    def should_preempt(self, task_id: str) -> bool:
        """
        Returns True if this task has any high-severity insight that hasn't been
        acknowledged. Used by coder to decide if it should use fallback model.
        """
        with self._lock:
            return task_id in self._high_severity_task_ids

    def get_model_override(self, task_id: str) -> str | None:
        """
        If a task has a high-severity insight with content containing 'security'
        or 'complexity', return 'fallback' to trigger model reassignment.
        Otherwise None.
        """
        with self._lock:
            for ins in self.insights:
                if getattr(ins, "task_id", "") != task_id:
                    continue
                if (getattr(ins, "severity", "") or "").lower() != "high":
                    continue
                content = (getattr(ins, "content", "") or "").lower()
                if "security" in content or "complexity" in content:
                    return "fallback"
            return None

    def get_reviewer_coder_high_notes(self, task_id: str) -> str:
        """Merge high-severity coder insights for reviewer prefix (spec §11)."""
        with self._lock:
            lines: list[str] = []
            for ins in self.insights:
                if getattr(ins, "task_id", "") != task_id:
                    continue
                if (ins.agent or "") != "coder":
                    continue
                if (ins.severity or "") != "high":
                    continue
                c = (ins.content or "").strip()
                if c:
                    lines.append(f"[CODER_HIGH_RISK]: {c[:1200]}")
            return "\n".join(lines[:8])
