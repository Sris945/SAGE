## SAGE Project Rules (baseline)

### Testing discipline
- Always write/ensure tests before claiming the change is correct.
- Prefer minimal, deterministic tests that fail first.

### Tool & safety constraints
- Never execute destructive commands without HITL confirmation in `--research` mode.
- Respect tool permissions provided via `TOOL PERMISSIONS`.

### Output discipline
- Return structured JSON outputs when requested by agent templates.
