# Token efficiency (practical)

SAGE already injects **truncated** skill blocks from `simialr stuff/` via `src/sage/prompt_engine/skill_injector.py` (per-role caps).

## Reduce tokens further

- Prefer **smaller** local models for reviewer/planner when `sage setup` assigns tiers.
- Use **`sage run`** with narrow prompts; avoid pasting huge logs unless the debugger needs them.
- Run **`sage rl export --data-source real`** only on real sessions when training; keep synthetic separate.
- Set benchmark env tightening for local runs (see `docs/models.md` for `SAGE_BENCH_*` timeouts).

## “Claude mem” style memory

SAGE uses **session logs + memory layers**, not a separate product named “Claude Mem”. For long-horizon reuse, rely on:

- `memory/sessions/*.log` structured events
- `memory/system_state.json` for resumable state

Future work: explicit summarization / compaction layer between sessions.
