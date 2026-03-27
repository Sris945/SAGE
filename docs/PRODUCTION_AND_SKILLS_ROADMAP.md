# Production readiness + skills roadmap (detailed todo plan)

This document merges **(A)** the skills feature status, **(B)** gaps vs a “production” bar, and **(C)** a phased checklist you can execute in order.

**See also:** [path threat model](path_threat_model.md), [failure runbook](runbook_failures.md), CLI `sage permissions`, `sage config paths|migrate`.

---

## Part A — Skills feature: status update

### What is implemented today (bundled first-party tree)

| Item | Status | Where |
| --- | --- | --- |
| Skill markdown loaded from disk | Done | [`src/sage/prompt_engine/skill_injector.py`](../src/sage/prompt_engine/skill_injector.py) |
| Bundled skills directory | Done | [`src/sage/assets/skills/`](../src/sage/assets/skills/) (packaged via `pyproject.toml` `package-data`) |
| Per-role + error-keyword selection | Done | `_select_skills()` |
| Lightweight `task_description` keywords | Done | e.g. `test`, `pytest`, `debug`, `traceback` |
| Truncation + total cap + in-process cache | Done | `SAGE_MAX_SKILL_CHARS_TOTAL`, `_load_skill_text` + `lru_cache` |
| `SKILL_INJECTION` logging (no raw bodies) | Done | `structured_logger.log_event` + stdlib `logging` |
| Optional override root | Done | `SAGE_SKILLS_ROOT` (same layout: `discipline/`, `workflow/`, `planning/`) |
| Injection into agent prefix | Done | [`workflow.py`](../src/sage/orchestrator/workflow.py) (`SKILL DISCIPLINE CONTEXT`) |

**Runtime does not read `simialr stuff/`.** That folder may remain in the repo for reference; the injector uses only the bundled tree (or `SAGE_SKILLS_ROOT`).

### Remaining gaps

| Gap | Why it matters |
| --- | --- |
| **YAML manifests per skill** | Optional: metadata (roles, triggers) separate from markdown for cleaner routing. |
| **User skill merge dir** | `.sage/imported_skills/*.md` not yet merged (rules exist separately). |
| **Stricter command policy** | Executor still uses substring blocks; expand allowlist/denylist (see Part C Phase 3). |

---

## Part B — Adding more skills (maintainer workflow)

1. Add or edit `SKILL.md` under `src/sage/assets/skills/{discipline,workflow,planning}/<name>/SKILL.md`.
2. Reference the relative path in `_select_skills()` with a `_SkillSpec("discipline/.../SKILL.md")` (or `workflow/`, `planning/`).
3. Keep `max_chars` and total caps tight; add/extend a unit test in `tests/test_skill_injector_unit.py`.

Feature-harvest philosophy (ideas without bulk-copying): [`docs/stage4_feature_harvest.md`](stage4_feature_harvest.md).

---

## Part C — Detailed todo list (production + skills + audit follow-through)

Use checkboxes as you complete items. Order is **recommended**, not mandatory.

### Phase 0 — Baseline (same day)

- [x] **P0.1** Confirm run: `pip install -e ".[dev]"`, `pytest`, `scripts/verify_local.sh`.
- [x] **P0.2** Skills ship bundled under `src/sage/assets/skills/` (no dependency on `simialr stuff/`).
- [x] **P0.3** Operator notes: [`docs/runbook_failures.md`](runbook_failures.md).

### Phase 1 — Skills: close the MVP gaps

- [x] **S1.1** Structured `SKILL_INJECTION` event with `skill_ids`, SHA256 prefixes, char counts.
- [x] **S1.2** `task_description` keyword routing (deterministic).
- [x] **S1.3** Unit tests for non-empty injection.
- [ ] **S1.4** Optional skill manifests (YAML) + curated new skills as needed.

### Phase 2 — Skills: packaging & portability

- [x] **S2.1** Default: skills bundled in package (`package-data` glob for `assets/skills/**/*.md`).
- [x] **S2.2** `SAGE_SKILLS_ROOT` override.
- [ ] **S2.3** Optional user skills dir merge.

### Phase 3 — Security & trust (production blocker tier)

- [x] **SEC3.1** Workspace jail for filesystem ops (`SAGE_WORKSPACE_ROOT`; `sage run` sets cwd root).
- [ ] **SEC3.2** Stronger `run_command` policy (allowlist / tiers).
- [ ] **SEC3.3** Redact API keys in logs.

### Phase 4 — Reliability & debuggability

- [ ] **R4.1** Replace bare `except` on critical paths (partially: Docker fallback in executor logs).
- [x] **R4.2** Exit codes documented in CLI epilog (`0` / `1` / `2`).
- [ ] **R4.3** `sage run --trace` (optional).

### Phase 5 — CI & quality gates

- [x] **Q5.1** `ruff check` + `ruff format --check` in CI.
- [x] **Q5.2** `mypy --follow-imports=skip` on new modules (full-tree mypy deferred).
- [ ] **Q5.3** Pin upper bounds for critical deps on release branches.

### Phase 6 — Configuration & operations

- [x] **O6.1** User-level `models.yaml` via `~/.config/sage/models.yaml` or `SAGE_MODELS_YAML`; `sage config migrate` + `sage config paths`.
- [ ] **O6.2** Document retention/redaction for session logs (PII).
- [ ] **O6.3** Versioning policy for JSON artifacts.

### Phase 7 — Observability (service-grade)

- [x] **OB7.1** Optional JSON log mirror: `SAGE_JSON_LOG_EXTRA_PATH`.
- [ ] **OB7.2** OpenTelemetry hooks.

### Phase 8 — Architecture maintainability

- [ ] **A8.1** Split [`workflow.py`](../src/sage/orchestrator/workflow.py) into smaller modules.
- [ ] **A8.2** Integration test: full `app.invoke` with LLM mocked.

### Phase 9 — Token & cost controls

- [x] **T9.1** `SAGE_MAX_SKILL_CHARS_TOTAL`, `SAGE_MAX_PROMPT_CHARS_TOTAL` (chat path).
- [ ] **T9.2** Summarize long context for second-hop agents (policy-driven).

---

## References

- Skills injector: [`src/sage/prompt_engine/skill_injector.py`](../src/sage/prompt_engine/skill_injector.py)
- Workspace policy: [`src/sage/execution/workspace_policy.py`](../src/sage/execution/workspace_policy.py)
- Config paths: [`src/sage/config/paths.py`](../src/sage/config/paths.py)
