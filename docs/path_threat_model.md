# Path and workspace threat model

## Workspace jail (filesystem tools)

`ToolExecutionEngine` resolves each target path with `Path.resolve()` and requires the result to lie under one of the allowed workspace roots (`SAGE_WORKSPACE_ROOT`, default: current working directory).

### Symlinks

If `path` is a symlink, `resolve()` follows it to the final path. A symlink **inside** the workspace that points **outside** the allowed roots will be **rejected** (good).

If a path is constructed so that `resolve()` leaves the tree (e.g. unusual mount layouts), treat the check as best-effort: prefer running SAGE with a dedicated project directory and avoid pointing `SAGE_WORKSPACE_ROOT` at overly broad paths (e.g. `$HOME`).

### Relative paths

Relative `file` values are resolved against the process current working directory, which `sage run` aligns with the target repo when `--repo` is set.

## Commands

Commands are split with `shell=False` (no shell injection). Blocking is substring-based on the raw patch string; this is not a full parser for chained or encoded payloads.
