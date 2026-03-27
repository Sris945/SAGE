# Changelog

All notable changes to this project should be documented in this file.

## Unreleased

- CLI / docs:
  - `docs/CLI.md`, `docs/INSTALL.md`, `docs/README.md`; `startup.sh` / `startup.ps1` bootstrap.
  - `/commands` footer prints repo + doc deep links (`SAGE_REPO_URL`, optional `git` origin).
  - Removed draft **`plan final/`** specs from the tree; README and `docs/architecture.md` now point at in-repo documentation only.
- Phase 5/6 closure work:
  - Session-scoped RL export with provenance labels.
  - Offline RL artifact pipeline (BC + conservative policy + offline eval).
  - Simulator maturity: 1000+ tasks, docker runner, PPO smoke.
  - Benchmark artifacts (`sage bench --out`) and YAML task suite parity.
  - Verification matrix + local verification script.
- Project readiness:
  - CI workflow and docker sim smoke workflow.
  - Release checklist and final status reconciliation docs.
