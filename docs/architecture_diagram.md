# SAGE Architecture (MVP → Phase 4)

```mermaid
flowchart TD
  A[detect_mode] --> B{repo_mode}
  B -->|existing_repo| C[codebase_intel]
  B -->|greenfield| P[prompt_middleware]

  C --> H1[human_checkpoint_1_post_scan]
  H1 --> P

  P --> R[route_model]
  R --> L[planner]
  L --> H2[human_checkpoint]
  H2 --> S[scheduler_batch]
  S --> D[parallel_dispatch]
  D --> W[task_worker xN]
  W --> M[merge_task_updates]
  M --> T{{DAG done?}}
  T -->|no| S
  T -->|yes| END[save_memory]

  %% Per-task lifecycle
  W --> X[execute_agent] --> Y[tool_executor] --> Z[verification_gate]
  Z --> F[check_fix_patterns] --> DBG[debug_agent] --> CB[circuit_breaker]
  CB --> END2[save_memory]
```

## Notes
- Tool execution is sandboxed and governed by safety rules (`ToolExecutionEngine`).
- Parallel scheduling uses LangGraph when available, otherwise falls back to a rule-based worker pool.
- Phase 4 observability emits `PROMPT_QUALITY_DELTA` and `TRAJECTORY_STEP` events into the session journal.

