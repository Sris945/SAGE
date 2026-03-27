"""
Orchestrator Intelligence Feed (MVP)
-------------------------------------
Buffers AgentInsight packets and determines whether orchestration should
intervene.

This MVP focuses on ingestion + logging. Future phases can implement
pre-emptive reassignments and prompt injection.
"""

from __future__ import annotations

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
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, init=False)

    def ingest(self, insight: AgentInsight) -> None:
        """Ingest an insight packet and decide whether to intervene (MVP = log-only)."""
        with self._lock:
            # Ensure timestamp exists.
            if not insight.timestamp:
                insight.timestamp = datetime.now(timezone.utc).isoformat()

            self.insights.append(insight)

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
        or explicitly requires orchestrator action.
        """
        with self._lock:
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

    def task_risk_rank(self, task_id: str) -> int:
        """
        Deterministic risk rank for scheduling prioritization.

        Higher number means higher priority:
          - high severity + requires_action => 3
          - high severity => 2
          - medium severity => 1
          - otherwise => 0
        """
        with self._lock:
            best = 0
            for it in self.interventions:
                if it.get("task_id") != task_id:
                    continue
                severity = it.get("severity") or "low"
                requires = bool(it.get("requires_orchestrator_action"))
                rank = 0
                if severity == "high":
                    rank = 3 if requires else 2
                elif severity == "medium":
                    rank = 1
                best = max(best, rank)
            return best
