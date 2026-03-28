"""
SAGE State Assessor
--------------------
Analyses a repository's completion and health state.

Provides real implementation of:
  - broken import detection via AST parsing
  - stub function detection (pass / ... / raise NotImplementedError)
  - last active files from git log
  - per-file completion status
  - missing test detection
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Stdlib module names (covers Python 3.10+)
# ---------------------------------------------------------------------------

def _stdlib_names() -> frozenset[str]:
    """Return the set of top-level stdlib module names."""
    # sys.stdlib_module_names is available since Python 3.10
    if hasattr(sys, "stdlib_module_names"):
        return frozenset(sys.stdlib_module_names)  # type: ignore[attr-defined]
    # Fallback: a broad static set covering the most common stdlib modules.
    return frozenset({
        "__future__", "_thread", "abc", "aifc", "argparse", "array", "ast",
        "asynchat", "asyncio", "asyncore", "atexit", "audioop", "base64",
        "bdb", "binascii", "binhex", "bisect", "builtins", "bz2", "calendar",
        "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs", "codeop",
        "collections", "colorsys", "compileall", "concurrent", "configparser",
        "contextlib", "contextvars", "copy", "copyreg", "cProfile", "csv",
        "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal",
        "difflib", "dis", "doctest", "email", "encodings", "enum", "errno",
        "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
        "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob",
        "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http", "idlelib",
        "imaplib", "importlib", "inspect", "io", "ipaddress", "itertools",
        "json", "keyword", "lib2to3", "linecache", "locale", "logging",
        "lzma", "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
        "modulefinder", "multiprocessing", "netrc", "nis", "nntplib", "numbers",
        "operator", "optparse", "os", "ossaudiodev", "pathlib", "pdb", "pickle",
        "pickletools", "pipes", "pkgutil", "platform", "plistlib", "poplib",
        "posix", "posixpath", "pprint", "profile", "pstats", "pty", "pwd",
        "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random", "re",
        "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched",
        "secrets", "select", "selectors", "shelve", "shlex", "shutil",
        "signal", "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
        "spwd", "sqlite3", "sre_compile", "sre_constants", "sre_parse", "ssl",
        "stat", "statistics", "string", "stringprep", "struct", "subprocess",
        "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
        "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap",
        "threading", "time", "timeit", "tkinter", "token", "tokenize", "tomllib",
        "trace", "traceback", "tracemalloc", "tty", "turtle", "turtledemo",
        "types", "typing", "unicodedata", "unittest", "urllib", "uu", "uuid",
        "venv", "warnings", "wave", "weakref", "webbrowser", "wsgiref",
        "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
        "zoneinfo",
    })


_STDLIB = _stdlib_names()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_safe(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def _parse_requirements(repo: Path) -> set[str]:
    """
    Return the set of top-level package names from requirements.txt and
    pyproject.toml [project.dependencies].
    """
    names: set[str] = set()

    req_txt = repo / "requirements.txt"
    if req_txt.exists():
        for line in _read_safe(req_txt).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip version specifiers: requests>=2.0 → requests
            pkg = re.split(r"[><=!;\[#@\s]", line)[0].strip()
            if pkg:
                names.add(pkg.lower().replace("-", "_"))

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        txt = _read_safe(pyproject)
        # Very simple TOML regex: grab strings in [project.dependencies]
        in_section = False
        for line in txt.splitlines():
            stripped = line.strip()
            if stripped.startswith("[project.dependencies]"):
                in_section = True
                continue
            if in_section and stripped.startswith("["):
                in_section = False
            if in_section and stripped.startswith('"') or (in_section and "=" in stripped):
                pkg = re.split(r"[><=!;\[#@\s\"']", stripped)[0].strip().strip('"\'')
                if pkg:
                    names.add(pkg.lower().replace("-", "_"))

    return names


def _collect_local_modules(repo: Path) -> set[str]:
    """Return the set of importable module names rooted in the repo."""
    mods: set[str] = set()
    for p in repo.rglob("*.py"):
        if any(part in {".venv", "venv", ".mypy_cache", "__pycache__", ".git"} for part in p.parts):
            continue
        # Add the stem and the package hierarchy
        mods.add(p.stem)
        try:
            rel = p.relative_to(repo)
            parts = list(rel.parts)
            if parts:
                mods.add(parts[0].removesuffix(".py"))
        except ValueError:
            pass
    return mods


import re as _re  # noqa: E402  (re already imported at top of _parse_requirements)


# ---------------------------------------------------------------------------
# Broken import detection
# ---------------------------------------------------------------------------

def _check_broken_imports(
    repo: Path,
    py_files: list[Path],
    known_packages: set[str],
    local_mods: set[str],
) -> list[dict[str, Any]]:
    """
    For each .py file parse imports via AST and report ones that appear
    to be neither stdlib, a declared dependency, nor a local module.
    """
    broken: list[dict[str, Any]] = []

    for py in py_files:
        try:
            src = py.read_text(errors="ignore")
            tree = ast.parse(src, filename=str(py))
        except SyntaxError:
            continue
        except Exception:
            continue

        rel = str(py.relative_to(repo))

        for node in ast.walk(tree):
            top: str | None = None
            import_str: str = ""

            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    import_str = f"import {alias.name}"
                    _check_top(top, import_str, node.lineno, rel, known_packages, local_mods, broken)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    names_str = ", ".join(a.name for a in node.names[:3])
                    import_str = f"from {node.module} import {names_str}"
                    _check_top(top, import_str, node.lineno, rel, known_packages, local_mods, broken)
                elif node.level and node.level > 0:
                    # Relative import — always local
                    continue

    return broken[:200]


def _check_top(
    top: str,
    import_str: str,
    lineno: int,
    rel: str,
    known_packages: set[str],
    local_mods: set[str],
    broken: list[dict[str, Any]],
) -> None:
    if not top:
        return
    top_norm = top.lower().replace("-", "_")
    if top_norm in _STDLIB:
        return
    if top_norm in known_packages:
        return
    if top in local_mods or top_norm in local_mods:
        return
    broken.append({
        "file": rel,
        "import": import_str,
        "line": lineno,
        "reason": f"'{top}' not in stdlib, requirements, or local modules",
    })


# ---------------------------------------------------------------------------
# Stub function detection
# ---------------------------------------------------------------------------

def _is_stub_body(body: list[ast.stmt]) -> tuple[bool, str]:
    """
    Return (is_stub, stub_type) for a function body.

    Stub patterns:
      - Single `pass`
      - Single `...` (Ellipsis)
      - Single `raise NotImplementedError(...)`
      - Docstring followed by pass / ...
    """
    if not body:
        return False, ""

    # Strip leading docstring
    effective = list(body)
    if (
        effective
        and isinstance(effective[0], ast.Expr)
        and isinstance(effective[0].value, ast.Constant)
        and isinstance(effective[0].value.value, str)
    ):
        effective = effective[1:]

    if not effective:
        return True, "docstring_only"

    if len(effective) == 1:
        stmt = effective[0]
        if isinstance(stmt, ast.Pass):
            return True, "pass"
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is ...:
            return True, "ellipsis"
        if isinstance(stmt, ast.Raise):
            exc = stmt.exc
            if exc is not None:
                if isinstance(exc, ast.Call):
                    func = exc.func
                    name = getattr(func, "id", None) or getattr(func, "attr", None)
                    if name == "NotImplementedError":
                        return True, "raise_not_implemented"
                elif isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                    return True, "raise_not_implemented"

    return False, ""


def _find_stub_functions(
    repo: Path,
    py_files: list[Path],
) -> list[dict[str, Any]]:
    """Walk each file and collect stub function definitions."""
    stubs: list[dict[str, Any]] = []

    for py in py_files:
        try:
            src = py.read_text(errors="ignore")
            tree = ast.parse(src, filename=str(py))
        except Exception:
            continue

        rel = str(py.relative_to(repo))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_stub, stub_type = _is_stub_body(node.body)
            if is_stub:
                stubs.append({
                    "file": rel,
                    "name": node.name,
                    "line": node.lineno,
                    "stub_type": stub_type,
                })

    return stubs[:500]


# ---------------------------------------------------------------------------
# Git log helpers
# ---------------------------------------------------------------------------

def _last_active_files(repo_path: str, n: int = 10) -> list[str]:
    """Return the top-N most recently touched files from git log."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--name-only", "-20"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_path,
        )
        if result.returncode != 0:
            return []
        seen: dict[str, None] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or " " in line:
                # Lines with spaces are the "hash subject" lines
                continue
            seen[line] = None
            if len(seen) >= n:
                break
        return list(seen.keys())[:n]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Completion status
# ---------------------------------------------------------------------------

def _count_stubs_in_file(rel: str, stubs: list[dict[str, Any]]) -> int:
    return sum(1 for s in stubs if s["file"] == rel)


def _has_todos(txt: str) -> bool:
    return bool(_re.search(r"\b(TODO|FIXME|HACK|XXX)\b", txt, _re.IGNORECASE))


def _derive_completion_status(
    codebase_map: dict[str, Any],
    stubs: list[dict[str, Any]],
    missing_tests: list[str],
    repo: Path,
) -> dict[str, str]:
    """
    Classify each file in codebase_map["file_summaries"] as:
    skeleton / partial / complete
    """
    file_summaries: dict[str, Any] = codebase_map.get("file_summaries", {})
    incomplete_files: set[str] = set(codebase_map.get("incomplete_files", []))
    stub_map: dict[str, int] = {}
    for s in stubs:
        stub_map[s["file"]] = stub_map.get(s["file"], 0) + 1

    missing_test_set = set(missing_tests)
    status: dict[str, str] = {}

    for rel, info in file_summaries.items():
        total_funcs = len(info.get("functions", []))
        stub_count = stub_map.get(rel, 0)

        # skeleton: >50% of functions are stubs
        if total_funcs > 0 and stub_count / total_funcs > 0.5:
            status[rel] = "skeleton"
            continue

        # Check for TODOs in source
        try:
            txt = (repo / rel).read_text(errors="ignore")
            has_todo = _has_todos(txt)
        except Exception:
            has_todo = False

        has_stubs = stub_count > 0
        is_incomplete = rel in incomplete_files

        if has_stubs or is_incomplete or has_todo:
            status[rel] = "partial"
        elif rel not in missing_test_set:
            status[rel] = "complete"
        else:
            status[rel] = "partial"

    return status


# ---------------------------------------------------------------------------
# Missing test detection
# ---------------------------------------------------------------------------

def _find_missing_tests(repo: Path, py_files: list[Path]) -> list[str]:
    """
    Return list of .py files that have no corresponding test_*.py in tests/.
    Skips test files themselves and __init__.py.
    """
    tests_dir = repo / "tests"
    test_stems: set[str] = set()

    # Collect all test file stems
    for pattern in ("test_*.py", "*_test.py"):
        for tf in repo.rglob(pattern):
            if any(p in {".venv", "venv", ".mypy_cache", "__pycache__", ".git"} for p in tf.parts):
                continue
            stem = tf.stem.removeprefix("test_").removesuffix("_test")
            test_stems.add(stem)

    missing: list[str] = []
    for py in py_files:
        rel = str(py.relative_to(repo))
        # Skip test files, __init__, conftest
        if py.stem.startswith("test_") or py.stem.endswith("_test"):
            continue
        if py.stem in ("__init__", "conftest", "setup"):
            continue
        if py.stem not in test_stems:
            missing.append(rel)

    return sorted(missing)[:200]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assess_state(codebase_map: dict[str, Any], repo_path: str = ".") -> dict[str, Any]:
    """
    Analyse repository health and completion state.

    Args:
        codebase_map: Output from ``scan_repo`` (must contain ``file_summaries``).
        repo_path:    Root of the repository to inspect.

    Returns a dict with:
        completion_status   – per-file "complete" | "partial" | "skeleton"
        open_threads        – TODO/FIXME items from the scan
        broken_imports      – imports that look unresolvable
        stub_functions      – functions with placeholder bodies
        last_active_files   – recently touched files from git log
        missing_tests       – source files without a test counterpart
    """
    repo = Path(repo_path).resolve()

    # Gather Python files (respecting the same skip rules as scanner)
    py_files: list[Path] = []
    for p in repo.rglob("*.py"):
        if any(part in {".venv", "venv", ".mypy_cache", "__pycache__", ".git"} for part in p.parts):
            continue
        py_files.append(p)

    # Known packages from dependency files
    try:
        known_packages = _parse_requirements(repo)
    except Exception:
        known_packages = set()

    # Local module names
    try:
        local_mods = _collect_local_modules(repo)
    except Exception:
        local_mods = set()

    # Broken imports
    try:
        broken_imports = _check_broken_imports(repo, py_files, known_packages, local_mods)
    except Exception:
        broken_imports = []

    # Stub functions
    try:
        stub_functions = _find_stub_functions(repo, py_files)
    except Exception:
        stub_functions = []

    # Last active files from git
    try:
        last_active_files = _last_active_files(str(repo))
    except Exception:
        last_active_files = []

    # Missing tests
    try:
        missing_tests = _find_missing_tests(repo, py_files)
    except Exception:
        missing_tests = []

    # Completion status
    try:
        completion_status = _derive_completion_status(codebase_map, stub_functions, missing_tests, repo)
    except Exception:
        completion_status = {}
        for f in codebase_map.get("incomplete_files", []):
            completion_status[f] = "partial"

    return {
        "completion_status": completion_status,
        "open_threads": codebase_map.get("open_threads", []),
        "broken_imports": broken_imports,
        "stub_functions": stub_functions,
        "last_active_files": last_active_files,
        "missing_tests": missing_tests,
    }
