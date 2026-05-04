# Architecture implementation status

This table tracks parity with the architecture specification (see `sage plan/SAGE_ARCHITECTURE_V1_FINAL.md` or project architecture docs). It is the **source of truth** for shipped behavior versus future work.

## Agentic tool-use loop (Phase 1–4, shipped)

| Feature | Status | Notes |
|---------|--------|-------|
| ReAct tool-use loop | **Implemented** | `execution/tool_loop.py` — `ToolLoopEngine`, up to 24 turns, budget warning at turn 18 |
| Tool registry | **Implemented** | `tools/tool_registry.py` — 9 tools: `read_file`, `edit_file`, `write_file`, `grep_code`, `find_files`, `list_directory`, `run_command`, `git_status`, `git_diff` |
| Surgical edit (`edit_file`) | **Implemented** | Uniqueness-enforced `old_string → new_string`; count=0 hints at grep result; count>1 lists line numbers |
| Context compression | **Implemented** | `memory/context_compressor.py` — Qdrant → TF-IDF BM25-style → grep; `MAX_CONTEXT_CHARS=16K` |
| Cross-file review | **Implemented** | `agents/cross_file_reviewer.py` — post-DAG unified diff review; wired into LangGraph and fallback `invoke()` paths |
| Model upgrade path | **Implemented** | `config/models.yaml` — 14B primary / 32B fallback for coder; VRAM-tier guide in `docs/models.md` |
| `SAGE_TOOL_LOOP=0` escape | **Implemented** | Reverts to legacy single-shot PatchRequest mode for small models or debugging |

## Spec parity

| Spec area | Feature | Status | Notes |
|-----------|---------|--------|-------|
| §3 Codebase intelligence | Tree-sitter / semantic maps | Partial | `context_builder`, `semantic_reader`, `runtime_analyzer`; vector index: `codebase/code_index.py`, Qdrant under `.sage/qdrant_code_index/` |
| §3 | Retrieved chunks in prompts | **Implemented** | `context_compressor` injects `CODEBASE CONTEXT` block into every tool-loop run |
| §4 Prompt intelligence | Global external doc corpus | Not implemented | Local `docs/` + README via `docs_rag_retriever.py`; **by design** until a bundled corpus is added |
| §11 Intel feed | Composite risk + preempt | Implemented | `intelligence_feed.py`, `should_preempt`, coder fallback wiring |
| §11 | Reviewer pre-injection | Implemented | `prefix_builder` + `get_reviewer_coder_high_notes` |
| §11 | Intervention logging | Implemented | `ORCHESTRATOR_INTERVENTION` with `action_taken` where applicable |
| §12 Event bus | Full PDF event registry | Partial | `event_bus.py` (FIFO worker); structured logs cover main events |
| §15 Tools | Agentic tool loop in coder | **Implemented** | See Phase 1–4 table above |
| §15 | Git ops via executor | Partial | `execution/git_tools.py` + `PatchRequest` git operations |
| §16 Memory | 3-layer retrieval | Documented | `memory/manager.py`; RAG + patterns in orchestrator |
| §16 | Fix-pattern RAG + recency | Implemented | `memory/rag_retriever.py` — cosine + success_rate + recency |
| §16 | SQLite task execution history | Implemented | `memory/sqlite_store.py` (`memory/tasks.db`) |
| §16 | Weekly digest | Implemented | `sage memory digest`; `maybe_auto_digest()` in `save_memory` |
| §16 | Session log token summary | Implemented | `[TOKEN_SUMMARY]` line in session journal |
| §16 | Cross-file review in session log | **Implemented** | `[CrossFileReview]` line appended by `cross_file_review` node |
| §17 Session / overload | Model overload heuristic + handoff | Partial | `ollama_safe.is_overload_error`, optional handoff + `model_override` |
| §18 Rules | Merge / validate | Implemented | `rules_manager`; `sage rules add`; `sage rules validate` |
| §20 HITL | Checkpoints 1–5 | Partial | `workflow.human_checkpoint*`; registry: `orchestrator/checkpoints.py` |
| §20 | Plan reject / edit | Implemented | Post-plan `a`/`r`/`e` in research mode |
| §20 | Checkpoint 4 sensitive / destructive | Partial | `ToolExecutionEngine.execute(..., mode=...)` |
| §8 Epistemic | `[UNVERIFIED]` gate | Partial | Blocks completion in `verification_gate` when tests missing |
| §9 Parallelism | Conflict UX | Partial | `merge_task_updates` panel for file-lock blocks |
| §22 Observability | Run metrics JSON | Implemented | `.sage/last_run_metrics.json` via `run_metrics.py` |
| §23 Benchmarks | Six YAML cases + 8 metrics | Partial | `src/sage/benchmarks/tasks/*.yaml`; `metrics_notes` for stubs |
| Research / RL | Export + BC/CQL | Partial | `sage rl export`, `train_bc`, `train_cql` |
| Dashboard (§22 future) | Live web UI | Not planned | Structured JSON + TTY summary |

**Banner for spec checklists:** If an older checklist in a long-form architecture document disagrees with this file, **trust `ARCHITECTURE_STATUS.md`**.

**Refinement note:** The v1 spec describes a research-lab breadth; SAGE ships a **product-shaped** subset first. **§3 existing-repo quality** and **§4 external prompt corpus** remain the main long-horizon gaps unless you add measurable benchmarks or import a curated doc corpus.
