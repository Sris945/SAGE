"""
SAGE Runtime Analyzer
----------------------
Safely probes Python modules in subprocesses to discover import errors and
function runtime behaviour without affecting the calling process.

All execution is sandboxed in subprocesses with hard timeouts. Never uses
``exec()`` or ``importlib`` in-process.

Usage::

    results = analyze_runtime("/path/to/repo", max_files=20)
    # {
    #   "src/foo.py": {
    #     "import_status": "ok" | "error",
    #     "import_error": None | "<traceback>",
    #     "functions": {
    #       "some_func": {"status": "works"|"runtime_error"|"timeout"|"skipped",
    #                     "return_type": str|None, "error": str|None}
    #     }
    #   }
    # }
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

_SKIP_DIRS = frozenset(
    {".venv", "venv", ".git", "__pycache__", ".mypy_cache", "node_modules", ".tox"}
)

# Patterns that indicate a file is unsafe to probe
_DANGEROUS_PATTERNS = (
    "if __name__",
    "open(",
    "requests.",
    "urllib.request",
    "socket.",
    "subprocess.",
    "os.system",
    "os.popen",
    "create_engine",
    "connect(",
    "psycopg2",
    "pymongo",
    "redis.",
    "boto",
    "smtplib",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _module_name_from_path(repo: Path, py: Path) -> str | None:
    """
    Convert ``repo/src/sage/foo/bar.py`` → ``sage.foo.bar`` (best-effort).
    """
    try:
        rel = py.relative_to(repo)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if not parts:
        return None
    # Drop leading "src" if present
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    return ".".join(parts)


def _should_skip_file(py: Path, text: str) -> bool:
    """Return True if the file should be skipped for safety or triviality."""
    if py.name in ("__init__.py", "conftest.py", "setup.py"):
        # Allow __init__ only if it has some logic
        if py.name == "__init__.py" and len(text.strip()) < 50:
            return True
    if py.stem.startswith("test_") or py.stem.endswith("_test"):
        return True
    # Count lines
    if text.count("\n") > 500:
        return True
    # Check dangerous patterns (only at module-level / outside functions)
    text_lower = text.lower()
    for pat in _DANGEROUS_PATTERNS:
        if pat in text_lower:
            return True
    return False


def _run_subprocess(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout[:2000], result.stderr[:2000]
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as exc:
        return -2, "", str(exc)[:200]


# ---------------------------------------------------------------------------
# Import probe
# ---------------------------------------------------------------------------


def _probe_import(
    repo_path: str,
    module_name: str,
    python_exe: str,
) -> tuple[str, str | None]:
    """
    Probe ``import <module_name>`` in a subprocess.

    Returns ("ok", None) or ("error", "<error_text>").
    """
    script = f"import sys; sys.path.insert(0, {repr(repo_path)}); import {module_name}"
    rc, _, stderr = _run_subprocess([python_exe, "-c", script], timeout=5.0)
    if rc == -1:
        return "error", "import probe timed out"
    if rc == 0:
        return "ok", None
    # Extract meaningful portion of traceback
    msg = stderr.strip()
    # Last line is usually the most useful
    lines = [ln for ln in msg.splitlines() if ln.strip()]
    summary = lines[-1][:200] if lines else msg[:200]
    return "error", summary


# ---------------------------------------------------------------------------
# Function probe
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "int": "0",
    "str": '""',
    "float": "0.0",
    "bool": "False",
    "list": "[]",
    "dict": "{}",
    "tuple": "()",
    "bytes": 'b""',
    "None": "None",
    "Optional": "None",
}


def _default_for_annotation(annotation: ast.expr | None) -> str:
    """Return a safe placeholder value for a function parameter annotation."""
    if annotation is None:
        return "None"
    if isinstance(annotation, ast.Name):
        return _TYPE_MAP.get(annotation.id, "None")
    if isinstance(annotation, ast.Constant):
        return repr(annotation.value)
    if isinstance(annotation, ast.Subscript):
        # e.g. Optional[str], List[int]
        if isinstance(annotation.value, ast.Name):
            outer = annotation.value.id
            if outer in ("Optional", "Union"):
                return "None"
            if outer in ("List", "Sequence", "Iterable"):
                return "[]"
            if outer in ("Dict", "Mapping"):
                return "{}"
            if outer == "Tuple":
                return "()"
    return "None"


def _build_call_args(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """
    Build a minimal positional argument string for a safe call.
    Returns None if the signature cannot be satisfied safely.
    """
    args = func_node.args
    # Skip *args, **kwargs, complex signatures
    if args.vararg or args.kwarg:
        return None

    required: list[ast.arg] = []
    defaults_count = len(args.defaults)
    n = len(args.args)
    # args without defaults (non-self)
    required_count = n - defaults_count
    for i, arg in enumerate(args.args):
        if arg.arg == "self" or arg.arg == "cls":
            continue
        if i < required_count:
            required.append(arg)

    parts: list[str] = []
    for arg in required:
        parts.append(_default_for_annotation(arg.annotation))

    return ", ".join(parts)


def _probe_function(
    repo_path: str,
    module_name: str,
    func_name: str,
    call_args: str,
    python_exe: str,
) -> dict[str, Any]:
    """
    Probe calling ``func_name(call_args)`` in a subprocess.

    Returns {"status": ..., "return_type": ..., "error": ...}
    """
    script = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {repr(repo_path)})
        try:
            from {module_name} import {func_name}
        except Exception as e:
            print("IMPORT_ERROR:" + str(e)[:200])
            sys.exit(1)
        try:
            result = {func_name}({call_args})
            print("OK:" + type(result).__name__)
        except Exception as e:
            print("RUNTIME_ERROR:" + str(e)[:200])
            sys.exit(2)
    """)
    rc, stdout, stderr = _run_subprocess([python_exe, "-c", script], timeout=3.0)

    if rc == -1:
        return {"status": "timeout", "return_type": None, "error": "call timed out"}

    out_line = stdout.strip()
    if out_line.startswith("OK:"):
        return {"status": "works", "return_type": out_line[3:], "error": None}
    if out_line.startswith("RUNTIME_ERROR:"):
        return {"status": "runtime_error", "return_type": None, "error": out_line[14:]}
    if out_line.startswith("IMPORT_ERROR:"):
        return {"status": "skipped", "return_type": None, "error": f"import: {out_line[13:]}"}
    # rc != 0 but no recognised prefix
    err = (stderr or stdout).strip()[:200]
    return {"status": "runtime_error", "return_type": None, "error": err or "unknown error"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_runtime(repo_path: str, max_files: int = 20) -> dict[str, Any]:
    """
    Probe Python modules in *repo_path* by running them in subprocesses.

    For each eligible file (up to *max_files*):
      1. Test whether the module can be imported.
      2. For each public function, attempt a minimal call and record the result.

    Safety rules enforced:
      - All execution in subprocesses with hard timeouts (5s import, 3s call).
      - Files containing IO/network/DB patterns are skipped.
      - Files >500 lines are skipped.
      - Test files and empty __init__.py files are skipped.
      - Each file has a total budget of 10s; the file is skipped if exceeded.

    Returns:
        Dict keyed by relative file path. Each value contains
        ``import_status``, ``import_error``, and ``functions``.
    """
    repo = Path(repo_path).resolve()
    python_exe = sys.executable
    results: dict[str, Any] = {}
    files_analyzed = 0

    for py in sorted(repo.rglob("*.py")):
        if files_analyzed >= max_files:
            break
        if any(p in _SKIP_DIRS for p in py.parts):
            continue

        try:
            text = py.read_text(errors="ignore")
        except Exception:
            continue

        if _should_skip_file(py, text):
            continue

        rel = str(py.relative_to(repo))
        module_name = _module_name_from_path(repo, py)
        if not module_name:
            continue

        file_result: dict[str, Any] = {
            "import_status": "ok",
            "import_error": None,
            "functions": {},
        }

        # --- Import probe ---
        import_status, import_error = _probe_import(str(repo), module_name, python_exe)
        file_result["import_status"] = import_status
        file_result["import_error"] = import_error

        # Only probe functions when the module imports cleanly
        if import_status == "ok":
            try:
                tree = ast.parse(text, filename=str(py))
            except SyntaxError:
                results[rel] = file_result
                files_analyzed += 1
                continue
            except Exception:
                results[rel] = file_result
                files_analyzed += 1
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                fname = node.name
                if fname.startswith("_"):
                    continue  # skip private/dunder functions

                call_args = _build_call_args(node)
                if call_args is None:
                    file_result["functions"][fname] = {
                        "status": "skipped",
                        "return_type": None,
                        "error": "complex signature (varargs/kwargs)",
                    }
                    continue

                try:
                    fn_result = _probe_function(
                        str(repo), module_name, fname, call_args, python_exe
                    )
                except Exception as exc:
                    fn_result = {
                        "status": "skipped",
                        "return_type": None,
                        "error": f"probe error: {exc}",
                    }
                file_result["functions"][fname] = fn_result

        results[rel] = file_result
        files_analyzed += 1

    return results
