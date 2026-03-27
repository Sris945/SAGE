# Stage 4 Feature Harvest (from `simialr stuff/`)

This document captures a curated import plan from the reference projects under `simialr stuff/`.

## Selection Method

- Score candidates by impact, implementation effort, and architectural fit with SAGE.
- Land small, high-value imports first.
- Avoid framework-level rewrites.

## Top 5 Curated Imports

- **Import 1 (landed):** reusable retry/backoff helper for flaky external checks.
  - Source pattern: `simialr stuff/ruflo/v3/plugins/teammate-plugin/src/utils/retry.ts`
  - SAGE landing: `src/sage/utils/retry.py`, used by `sage doctor` command checks.
  - User impact: fewer false negatives in environment readiness diagnostics.

- **Import 2 (landed):** health-style readiness scoring in `sage doctor`.
  - Source pattern: `.../utils/health-checker.ts`
  - Target: add aggregate health score and degraded/unhealthy statuses.

- **Import 3 (landed):** command help ergonomics and grouped CLI guidance (quickstart).
  - Updated `sage --help` epilog to include quickstart commands.

- **Import 4 (landed):** benchmark quick-run helper script pattern.
  - Source pattern: `simialr stuff/ruflo/v3/scripts/quick-benchmark.mjs`
  - Target: `scripts/quick_benchmark.py` wrapper around `sage bench`.

- **Import 5 (landed):** publish/readiness preflight script.
  - Source pattern: `simialr stuff/ruflo/v3/scripts/prepare-publish.js`
  - Target: `scripts/prepare_release.sh` checking docs/tests/artifacts.

## Current Status

- Landed: 5/5
