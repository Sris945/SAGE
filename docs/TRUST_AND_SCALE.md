# Trust, proof, and scale — roadmap

This document turns the “what SAGE is missing at scale” list into **concrete controls** (implemented now) and **next bets** (not yet shipped).

## Implemented in-tree (OSS)

| Area | What exists |
|------|-------------|
| **Proof / traces** | JSON-lines session log (`memory/sessions/`), `SAGE_SESSION_ID`, optional `SAGE_TRACE_ID` on each line, `MODEL_ROUTING_DECISION`, `TOKEN_USAGE`, `CONTEXT_CLAMPED`, `HUMAN_CHECKPOINT_REACHED`. |
| **Laptop-friendly eval** | `SAGE_MODEL_PROFILE=test` or `SAGE_FORCE_LOCAL_MODEL=<tag>` forces one small Ollama model for all roles (see `sage/llm/test_profile.py`). `sage eval smoke` runs `tests/integration` with that profile. **`sage eval golden`** checks golden JSONL + event order (routing → clamp → token usage) without Ollama. |
| **Hardware-aware real work** | **`sage prep`** (same stack logic as `sage setup suggest`) recommends pulls for your RAM/VRAM/disk — **not** the test profile. Use `sage setup apply` to merge into `models.yaml`. |
| **Grounding / limits** | `SAGE_MAX_PROMPT_CHARS_TOTAL` clamps prompts; successful clamps emit `CONTEXT_CLAMPED`. Tool policy + workspace roots unchanged. |
| **Human-in-the-loop** | `research` mode pauses at checkpoints; plan snapshot written to `.sage/last_plan.json` before Enter-to-continue. `auto` / `silent` skip blocking prompts. |
| **Operational hygiene** | Log redaction for common secret patterns; `SAGE_TOOL_POLICY`; session log rotation via `SAGE_SESSION_LOG_MAX_MB`. |

## Next bets (prioritized)

1. **Regression as a product**: ~~Golden traces (JSONL fixtures) + ordering checks~~ — **in progress** (`tests/fixtures/golden_trace_minimal.jsonl`, `sage eval golden`). Optional: nightly diff of full session logs vs baselines.
2. **Stronger retrieval**: RAG index health metrics, citation snippets in agent context, and explicit “no evidence” flags when retrieval is empty.
3. **Review UX**: Web or TUI diff view, queue of pending patches, approve/reject with audit log (beyond file export + Enter).
4. **Service hardening**: Per-tenant roots, tool allowlists, secret backends — only if SAGE becomes a hosted service.

## Differentiation (one sentence)

**SAGE is a self-improving, multi-agent orchestration loop with explicit routing, policy gates, and structured logs** — the north star is *trust through observability*, not only “more autonomy.”

## Local commands

```bash
# Fast routing for tests (single small Ollama model everywhere)
export SAGE_MODEL_PROFILE=test
pytest tests/ -q

# Greenfield mocked e2e (full graph, no Ollama)
pytest tests/e2e/test_greenfield_pipeline_mocked.py -q

# Golden trace ordering (no Ollama)
sage eval golden

# Planner + Ollama integration only (requires `ollama` + pulled model, e.g. qwen2.5-coder:1.5b)
sage eval smoke

# Recommended models for *your* hardware (do not conflate with SAGE_MODEL_PROFILE=test)
sage prep

# Full regression script (unit tests + golden + optional profile)
./scripts/regression_local.sh
```

Correlate log lines across tools: set `SAGE_TRACE_ID` to the same value in every terminal that participates in one logical run.
