# Architecture implementation status

This table tracks parity with the architecture specification (see `sage plan/SAGE_ARCHITECTURE_V1_FINAL.md` or project architecture docs). It is the **source of truth** for shipped behavior versus future work.

| Spec area | Feature | Status | Notes |
|-----------|---------|--------|-------|
| §3 Codebase intelligence | Tree-sitter / semantic maps | Partial | `context_builder`, `semantic_reader`, `runtime_analyzer`; vector index: `codebase/code_index.py`, Qdrant under `.sage/qdrant_code_index/` |
| §3 | Retrieved chunks in prompts | Partial | `ensure_index_for_brief` → `retrieved_code_chunks` in brief; embedded in `CODEBASE CONTEXT` — quality still validated by **bench + real repos**, not line count alone |
| §4 Prompt intelligence | Global external doc corpus (Claude/OpenAI papers, etc.) | Not implemented | Local `docs/` + README via `docs_rag_retriever.py`; middleware lives in `workflow.prompt_middleware` — **by design** until a bundled/imported corpus is added |
| §11 Intel feed | Composite risk + preempt | Implemented | `intelligence_feed.py`, `should_preempt`, coder fallback wiring |
| §11 | Reviewer pre-injection | Implemented | `prefix_builder` + `get_reviewer_coder_high_notes` |
| §11 | Intervention logging | Implemented | `ORCHESTRATOR_INTERVENTION` with `action_taken` where applicable |
| §12 Event bus | Full PDF event registry | Partial | `event_bus.py` (FIFO worker); structured logs include `TASK_STATUS_CHANGED`, `PIPELINE_BLOCKED`, `PATTERN_LEARNED`, `ORCHESTRATOR_INTERVENTION`, etc. — not every aspirational row in the spec |
| §16 Memory | 3-layer retrieval | Documented | `memory/manager.py`; RAG + patterns in orchestrator |
| §16 | Fix-pattern RAG + recency | Implemented | `memory/rag_retriever.py` — cosine + success_rate + recency; `private` flag on patterns excluded from index |
| §16 | SQLite task execution history | Implemented | `memory/sqlite_store.py` (`memory/tasks.db`); rows recorded on **completed/failed** transitions in `merge_task_updates` (per-task token attribution still TBD) |
| §16 | Weekly digest | Implemented | `sage memory digest` → `memory/weekly_digest.md`; `maybe_auto_digest()` in `save_memory` if digest ≥7 days old or missing |
| §16 | Session log token summary | Implemented | `[TOKEN_SUMMARY]` line in session journal when `token_usage` accumulated (Ollama `chat_with_timeout` path) |
| §16 | `<private>` everywhere | Partial | Semantic reader + RAG pattern filtering; **not** a single guarantee across all logs/stores |
| §17 Session / overload | Model overload heuristic + handoff | Partial | `ollama_safe.is_overload_error`, optional handoff + `model_override` / `SAGE_FALLBACK_MODEL` — string heuristics, not true API-level load shedding |
| §18 Rules | Merge / validate | Implemented | `rules_manager`; `sage rules add`; `sage rules validate` includes `_detect_conflicts` (always/never, numeric, negation) |
| §20 HITL | Checkpoints 1–5 | Partial | `workflow.human_checkpoint*`; registry: `orchestrator/checkpoints.py` |
| §20 | Plan reject / edit | Implemented | Post-plan `a`/`r`/`e` in research mode; `.sage/last_plan.json` — resume = next `sage run` without `--fresh` when handoff exists |
| §20 | Checkpoint 4 sensitive / destructive | Partial | `ToolExecutionEngine.execute(..., mode=...)`, `needs_confirmation` for destructive ops in research mode |
| §15 Tools | Git ops via executor | Partial | `execution/git_tools.py` + `PatchRequest` git operations dispatched from `executor.py` |
| §8 Epistemic | `[UNVERIFIED]` gate | Partial | Blocks completion in `verification_gate` when tests missing |
| §9 Parallelism | Conflict UX | Partial | `merge_task_updates` panel for file-lock blocks |
| §22 Observability | Run metrics JSON | Implemented | `.sage/last_run_metrics.json` via `run_metrics.py` |
| §23 Benchmarks | Six YAML cases + 8 metrics | Partial | `src/sage/benchmarks/tasks/*.yaml`; `metrics_notes` for stubs |
| Research / RL | Export + BC/CQL | Partial | `sage rl export`, `train_bc`, `train_cql`, `scripts/train_routing_policy.py` |
| Dashboard (§22 future) | Live web UI | Not planned (substitute) | Structured JSON + TTY summary |

**Banner for spec checklists:** If an older checklist in a long-form architecture document disagrees with this file, **trust `ARCHITECTURE_STATUS.md`**.

**Refinement note:** The v1 spec describes a research-lab breadth; SAGE ships a **product-shaped** subset first. **§3 existing-repo quality** and **§4 external prompt corpus** remain the main long-horizon gaps unless you add measurable benchmarks or import a curated doc corpus.
