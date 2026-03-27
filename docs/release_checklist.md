# Release checklist

Use this checklist before cutting a release candidate.

## 1) Quality gates

- [ ] `python -m pytest tests/ -q` passes locally.
- [ ] `scripts/verify_local.sh` completes successfully.
- [ ] `scripts/prepare_release.sh` passes (`--dry-run` for preview, full run before RC).
- [ ] CI workflows are green:
  - `.github/workflows/ci.yml`
  - `.github/workflows/docker-sim-smoke.yml` (when applicable)

## 2) Evidence artifacts

- [ ] `docs/final_checklist.md` reflects current artifacts and commands.
- [ ] `docs/research_notes.md` Implemented vs Deferred section is up to date.
- [ ] `docs/verification_matrix.md` command matrix is still accurate.

## 3) Documentation

- [ ] `README.md` quickstart/commands are current.
- [ ] `CONTRIBUTING.md` references current testing and release workflow.

## 4) Versioning / changelog

- [ ] Add an entry to `CHANGELOG.md`.
- [ ] Tag release version according to project policy.

## 5) Final sanity checks

- [ ] `sage run` smoke (with available local models) succeeds.
- [ ] `sage bench --out ...` writes JSON artifact.
- [ ] `sage sim run --docker` smoke succeeds (if Docker available).
