#!/usr/bin/env python3
"""
Quick benchmark runner.

This is a small quality-of-life wrapper around `sage bench` intended to
support rapid, consistent local iterations.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _sage_executable() -> str:
    # Prefer the local venv's `sage` for reproducibility.
    local = Path(".venv/bin/sage")
    if local.exists():
        return str(local)
    return "sage"


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick wrapper around `sage bench`.")
    parser.add_argument(
        "--compare-policy",
        action="store_true",
        help="Run `sage bench --compare-policy` (static vs learned routing).",
    )
    parser.add_argument(
        "--out",
        default="memory/benchmarks/quick_bench.json",
        help="Where to write the JSON artifact (passed to `sage bench --out`).",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [_sage_executable(), "bench"]
    if args.compare_policy:
        cmd.append("--compare-policy")
    cmd += ["--out", str(out_path)]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Surface stdout/stderr for quick debugging.
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        raise SystemExit(res.returncode)

    # If `sage bench` wrote the file, print a minimal summary for humans.
    if out_path.exists():
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            status = payload.get("status")
            print(f"[SAGE quick_benchmark] status={status} out={out_path}")
        except Exception:
            print(f"[SAGE quick_benchmark] out={out_path}")
    else:
        print(f"[SAGE quick_benchmark] (bench output missing) out={out_path}")


if __name__ == "__main__":
    main()

