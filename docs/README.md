# Documentation

The **authoritative overview** for contributors and users is the repository **[`README.md`](../README.md)** at the repo root (install, features, architecture summary).

**Implementation truth vs the long architecture spec:** **[`ARCHITECTURE_STATUS.md`](ARCHITECTURE_STATUS.md)**.  
**Locked design reference (PDF-style):** [`../sage plan/SAGE_ARCHITECTURE_V1_FINAL.md`](../sage%20plan/SAGE_ARCHITECTURE_V1_FINAL.md).

---

## Primary guides

| File | Topic |
|------|--------|
| [INSTALL.md](INSTALL.md) | Clone, `startup.sh` / `startup.ps1`, venv |
| [CLI.md](CLI.md) | `sage run`, shell, setup/config/prep, session, eval, rules, memory, env vars |
| [getting_started.md](getting_started.md) | Init + run flow; `bench`, `rl`, `sim`, training script |
| [models.md](models.md) | `models.yaml`, Ollama tags, VRAM, bench timeouts |
| [models_lightweight_20gb.md](models_lightweight_20gb.md) | Lightweight model tiers (~20 GB disk budget) |

---

## Architecture & spec

| File | Topic |
|------|--------|
| [ARCHITECTURE_STATUS.md](ARCHITECTURE_STATUS.md) | **Shipped vs spec** — source of truth for parity |
| [architecture.md](architecture.md) | Design entrypoints |
| [architecture_diagram.md](architecture_diagram.md) | Diagrams |
| [event_bus.md](event_bus.md) | Event bus semantics |
| [token_efficiency.md](token_efficiency.md) | Token budget notes |

---

## Security, trust, operations

| File | Topic |
|------|--------|
| [TRUST_AND_SCALE.md](TRUST_AND_SCALE.md) | Policy and scale |
| [path_threat_model.md](path_threat_model.md) | Path / workspace threat model |
| [LIVE_TESTING.md](LIVE_TESTING.md) | Live Ollama, `scripts/live_verify.sh` |
| [runbook_failures.md](runbook_failures.md) | Failure runbook |
| [verification_matrix.md](verification_matrix.md) | Command / scenario matrix |
| [LOCAL_PROJECT_PREP.md](LOCAL_PROJECT_PREP.md) | Preparing external project dirs |

---

## Benchmarks, research, release

| File | Topic |
|------|--------|
| [final_checklist.md](final_checklist.md) | Phase 5–6 RL / sim artifacts and reproduction |
| [research_notes.md](research_notes.md) | Research track notes |
| [release_checklist.md](release_checklist.md) | Release candidate checklist |
| [PRODUCTION_AND_SKILLS_ROADMAP.md](PRODUCTION_AND_SKILLS_ROADMAP.md) | Production / skills roadmap |

---

## Greenfield & staging notes

| File | Topic |
|------|--------|
| [GREENFIELD.md](GREENFIELD.md) | Greenfield workflow notes |
| [stage4_feature_harvest.md](stage4_feature_harvest.md) | Staging / harvest notes (historical context) |

---

## Contributing

Repository root **[`../CONTRIBUTING.md`](../CONTRIBUTING.md)** — tests, **Ruff**, Mypy (CI allowlist), live Ollama bar.

**Tip:** Set `SAGE_REPO_URL` so the `sage` shell’s `/commands` footer links to your GitHub fork.
