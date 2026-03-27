# SAGE — Phase 5 & 6 task plan

Aligned with **`SAGE_v1_FINAL.md` §26** (Phase 5 — Offline RL, Phase 6 — Simulator RL).

**Order:** Complete **Phase 5** foundations before **Phase 6**. Phase 6 assumes trajectories, benchmarks, and execution semantics from Phase 4–5.

---

## Phase 5 — Offline RL (post-launch, ~2 months)

**Goal:** Learned routing policy outperforms the static `models.yaml` table on held-out benchmark splits.

| ID | Task | Outcome / acceptance |
|----|------|------------------------|
| P5-1 | **Trajectory contract** | Define a single JSONL (or parquet) schema for routing decisions: `(state_features, discrete_action, reward, terminal, task_id, session_id, timestamp)`. Export from existing `TRAJECTORY_STEP` / session logs + bandit updates. |
| P5-2 | **Dataset build pipeline** | Script: aggregate logs → filtered dataset; configurable min quality (e.g. completed tasks only). Milestone: **500+** rows (spec); document how to regenerate. |
| P5-3 | **Reward function** | Implement composite reward (e.g. reviewer pass, verification pass, −timeout, −retries). Version in config; log ablation flags. |
| P5-4 | **Behavior Cloning baseline** | Small policy network (or sklearn if features are tabular): **state → action** (e.g. primary vs fallback). Train/eval split; save checkpoint path. |
| P5-5 | **CQL (or conservative offline RL) prototype** | Train offline policy with pessimism vs BC; compare validation metrics to BC. |
| P5-6 | **Router integration** | `ModelRouter` (or thin wrapper): `SAGE_RL_POLICY=1` uses learned logits/probs with fallback to YAML if low confidence or load failure. |
| P5-7 | **Benchmark: policy vs static** | Extend `sage bench` (or separate command): run **A/B** — static table vs learned policy; report same 8 metrics + win rate. |

**Dependencies:** P5-1 → P5-2 → P5-3 → P5-4 → P5-5 → P5-6 → P5-7.

---

## Phase 6 — Simulator RL (6+ months)

**Goal:** Fast, safe iteration on policies using simulated tasks and optional online fine-tuning.

| ID | Task | Outcome / acceptance |
|----|------|------------------------|
| P6-1 | **Curriculum of tasks with oracle** | **1000+** (spec) small tasks with **known** pass/fail checks (unit tests, golden outputs). Store as YAML/JSON suite under `benchmarks/` or `sim/`. |
| P6-2 | **Docker sandbox POC** | One container image: run pytest / file ops in isolation; ToolExecutionEngine path or adapter behind flag. |
| P6-3 | **Parallel runner** | N workers over task suite; aggregate metrics (throughput, pass rate). |
| P6-4 | **PPO (or similar) pipeline** | Train on simulator rollouts; optional bridge from Phase 5 offline policy as initialization. |

**Dependencies:** P6-1 before P6-3; P6-2 before scaling P6-3; P6-4 last.

---

## Links

- Full spec: `SAGE_v1_FINAL.md` §26, §29 (RL strategy).
- Current Tier 1: `src/sage/rl/ucb_bandit.py`.
- Trajectory logging: `src/sage/observability/trajectory_logger.py`.

---

*Last updated: living document — adjust IDs as work lands.*
