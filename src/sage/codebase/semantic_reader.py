"""
SAGE Semantic Reader (Phase 4+)
--------------------------------
Extracts a minimal semantic index of symbol names from a repository.

MVP: functions + classes per file.

If `tree-sitter` is unavailable or parsing fails, we fall back to regex.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

try:
    from tree_sitter import Parser  # type: ignore
    from tree_sitter_languages import get_language  # type: ignore
except Exception:  # pragma: no cover
    Parser = None  # type: ignore[assignment]
    get_language = None  # type: ignore[assignment]


_DEF_RE = re.compile(r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:(]", re.MULTILINE)


def _fallback_symbols_from_regex(txt: str) -> tuple[list[str], list[str]]:
    funcs = _DEF_RE.findall(txt)[:50]
    classes = _CLASS_RE.findall(txt)[:30]
    return funcs, classes


def _symbols_from_tree_sitter(txt: str) -> tuple[list[str], list[str]]:
    if Parser is None or get_language is None:
        return _fallback_symbols_from_regex(txt)

    try:
        parser = Parser()
        parser.set_language(get_language("python"))
        tree = parser.parse(bytes(txt, "utf-8"))
    except Exception:
        return _fallback_symbols_from_regex(txt)

    funcs: list[str] = []
    classes: list[str] = []

    def walk(node) -> None:
        nonlocal funcs, classes
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                funcs.append(name_node.text.decode("utf-8"))
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                classes.append(name_node.text.decode("utf-8"))

        # Stop early to keep output bounded.
        if len(funcs) >= 50 and len(classes) >= 30:
            return
        for ch in node.children:
            walk(ch)

    walk(tree.root_node)
    return funcs[:50], classes[:30]


def build_semantic_map(repo_path: str) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
    result: dict[str, Any] = {"symbols": {}}

    for py_file in repo.rglob("*.py"):
        if any(
            part in {".venv", "venv", ".mypy_cache", "__pycache__", ".git"}
            for part in py_file.parts
        ):
            continue
        try:
            txt = py_file.read_text(errors="ignore")
        except Exception:
            continue

        rel = str(py_file.relative_to(repo))
        funcs, classes = _symbols_from_tree_sitter(txt)
        if funcs or classes:
            result["symbols"][rel] = {"functions": funcs, "classes": classes}

    return result
