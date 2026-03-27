# Runbook: common failures

## Ollama timeouts (`OLLAMA_TIMEOUT` in session log)

- **Symptom:** Agents stop with timeout errors; log shows `OLLAMA_TIMEOUT`.
- **Checks:** `ollama list`, model pulled, GPU/CPU load. Increase role timeout in agent code or set `SAGE_BENCH` scaling only for benchmarks.
- **Mitigation:** Use a smaller primary model in `models.yaml` routing; ensure `sage doctor` is healthy.

## Skill injection empty

- **Symptom:** No `SKILL_INJECTION` events or empty discipline block.
- **Checks:** Bundled skills exist under `src/sage/assets/skills/` after install (`discipline/`, `workflow/`, `planning/`); optional override `SAGE_SKILLS_ROOT` must mirror that layout.

## Workspace `SafetyViolation` / path outside roots

- **Symptom:** Tool execution returns error about workspace roots.
- **Checks:** Run `sage permissions`; set `SAGE_WORKSPACE_ROOT` to your repo root (comma-separated for multiple). Run `sage run` from the intended directory or pass `--repo`.

## Config not found

- **Symptom:** Wrong routing or missing file.
- **Checks:** `sage config paths`; run `sage config migrate` to install user `models.yaml`; or set `SAGE_MODELS_YAML` to an explicit file.

## JSON log export

- Set `SAGE_JSON_LOG_EXTRA_PATH` to a file path to mirror structured JSON-lines events (in addition to `memory/sessions/*.log`).

## Session log growth (`memory/sessions/*.log`)

- **Symptom:** Daily JSON-lines logs grow without bound on busy sessions.
- **Mitigation:** Set `SAGE_SESSION_LOG_MAX_MB` to a positive float (megabytes). When the next append would exceed that size for the current day’s file, SAGE renames it to `YYYY-MM-DD.1.log` (then `.2.log`, etc.) and starts a fresh `YYYY-MM-DD.log`.
