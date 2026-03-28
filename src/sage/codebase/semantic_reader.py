"""
SAGE Semantic Reader
---------------------
Extracts a rich semantic index of symbols from a repository using Tree-sitter.

Each function/class is extracted as an individual chunk with:
  - name, file, line range, docstring, source preview, dependency references,
    complexity estimate, and whether a test file exists for the module.

Embeddings are stored in an in-memory Qdrant collection ("codebase_chunks").
Falls back to a hash-based embedding when Ollama is unavailable.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

try:
    from tree_sitter import Parser  # type: ignore
    from tree_sitter_languages import get_language  # type: ignore
except Exception:  # pragma: no cover
    Parser = None  # type: ignore[assignment]
    get_language = None  # type: ignore[assignment]

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # pragma: no cover
    QdrantClient = None  # type: ignore[assignment]
    qmodels = None  # type: ignore[assignment]

_SKIP_DIRS = frozenset({".venv", "venv", ".git", "__pycache__", ".mypy_cache", "node_modules", ".tox"})
_EMBED_MODEL = "nomic-embed-text:latest"
_COLLECTION = "codebase_chunks"
_EMBED_DIM = 64
_MAX_FILES = 200
_MAX_SYMBOLS_PER_FILE = 50

# Module-level Qdrant client and index, populated by build_semantic_map.
_qdrant_client: QdrantClient | None = None  # type: ignore[type-arg]
_chunk_index: list[dict[str, Any]] = []
_qdrant_built: bool = False


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _embed_text(text: str, timeout_s: float = 2.0) -> list[float]:
    """Embed text via Ollama nomic-embed-text or fall back to hash embedding."""
    try:
        from sage.llm.ollama_safe import embeddings_with_timeout
        vec = embeddings_with_timeout(model=_EMBED_MODEL, prompt=text, timeout_s=timeout_s)
        if isinstance(vec, list) and len(vec) == _EMBED_DIM:
            return vec
    except Exception:
        pass
    return _hash_embed(text)


def _hash_embed(text: str) -> list[float]:
    """Deterministic bag-of-hashed-tokens embedding (no Ollama required)."""
    vec = [0.0] * _EMBED_DIM
    for tok in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % _EMBED_DIM] += 1.0
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Tree-sitter symbol extraction
# ---------------------------------------------------------------------------

def _get_node_text(node, src_bytes: bytes) -> str:
    return src_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_docstring_from_node(node, src_bytes: bytes) -> str:
    """Extract the first string literal in a function/class body as docstring."""
    body = node.child_by_field_name("body")
    if body is None:
        return ""
    for child in body.children:
        # expression_statement wrapping a string
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type in ("string", "concatenated_string"):
                    raw = _get_node_text(sub, src_bytes)
                    # Strip quotes
                    try:
                        return ast.literal_eval(raw)
                    except Exception:
                        return raw.strip("\"'` \n")
        break  # docstring must be first statement
    return ""


def _complexity_label(line_count: int) -> str:
    if line_count <= 10:
        return "low"
    if line_count <= 30:
        return "medium"
    return "high"


def _extract_import_refs_from_body(node, src_bytes: bytes) -> list[str]:
    """Walk the function/class body and collect referenced names from imports."""
    refs: list[str] = []

    def walk(n) -> None:
        if n.type in ("import_statement", "import_from_statement"):
            text = _get_node_text(n, src_bytes)
            refs.append(text.strip())
        for ch in n.children:
            walk(ch)

    walk(node)
    return refs[:20]


def _extract_method_names(class_node, src_bytes: bytes) -> list[str]:
    """Return list of method names inside a class node."""
    methods: list[str] = []
    body = class_node.child_by_field_name("body")
    if body is None:
        return methods
    for child in body.children:
        if child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            if name_node:
                methods.append(name_node.text.decode("utf-8", errors="replace"))
    return methods[:30]


def _symbols_via_tree_sitter(
    txt: str,
    rel_path: str,
    has_tests: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Parse *txt* with Tree-sitter and return (functions, classes) lists.

    Each function dict:
      name, file, line_start, line_end, docstring, source_preview,
      dependencies, complexity, has_tests

    Each class dict:
      name, file, line_start, line_end, docstring, methods, has_tests
    """
    if Parser is None or get_language is None:
        return _symbols_via_regex(txt, rel_path, has_tests)

    try:
        parser = Parser()
        parser.set_language(get_language("python"))
        src_bytes = txt.encode("utf-8")
        tree = parser.parse(src_bytes)
    except Exception:
        return _symbols_via_regex(txt, rel_path, has_tests)

    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    lines = txt.splitlines()

    def walk(node) -> None:
        if len(functions) >= _MAX_SYMBOLS_PER_FILE and len(classes) >= _MAX_SYMBOLS_PER_FILE:
            return

        if node.type == "function_definition" and len(functions) < _MAX_SYMBOLS_PER_FILE:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode("utf-8", errors="replace")
                line_start = node.start_point[0] + 1
                line_end = node.end_point[0] + 1
                line_count = line_end - line_start + 1
                doc = _extract_docstring_from_node(node, src_bytes)
                src_preview = _get_node_text(node, src_bytes)[:300]
                deps = _extract_import_refs_from_body(node, src_bytes)
                functions.append({
                    "name": name,
                    "file": rel_path,
                    "line_start": line_start,
                    "line_end": line_end,
                    "docstring": doc,
                    "source_preview": src_preview,
                    "dependencies": deps,
                    "complexity": _complexity_label(line_count),
                    "has_tests": has_tests,
                })

        elif node.type == "class_definition" and len(classes) < _MAX_SYMBOLS_PER_FILE:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode("utf-8", errors="replace")
                line_start = node.start_point[0] + 1
                line_end = node.end_point[0] + 1
                doc = _extract_docstring_from_node(node, src_bytes)
                methods = _extract_method_names(node, src_bytes)
                classes.append({
                    "name": name,
                    "file": rel_path,
                    "line_start": line_start,
                    "line_end": line_end,
                    "docstring": doc,
                    "methods": methods,
                    "has_tests": has_tests,
                })

        for ch in node.children:
            walk(ch)

    walk(tree.root_node)
    return functions, classes


def _symbols_via_regex(
    txt: str,
    rel_path: str,
    has_tests: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Regex fallback when Tree-sitter is unavailable."""
    def_re = re.compile(r"^( *)def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.MULTILINE)
    class_re = re.compile(r"^( *)class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:(]", re.MULTILINE)
    lines = txt.splitlines()

    functions: list[dict[str, Any]] = []
    for m in def_re.finditer(txt):
        if len(functions) >= _MAX_SYMBOLS_PER_FILE:
            break
        line_no = txt[:m.start()].count("\n") + 1
        name = m.group(2)
        src_preview = "\n".join(lines[line_no - 1:line_no + 9])[:300]
        functions.append({
            "name": name,
            "file": rel_path,
            "line_start": line_no,
            "line_end": line_no,
            "docstring": "",
            "source_preview": src_preview,
            "dependencies": [],
            "complexity": "low",
            "has_tests": has_tests,
        })

    classes: list[dict[str, Any]] = []
    for m in class_re.finditer(txt):
        if len(classes) >= _MAX_SYMBOLS_PER_FILE:
            break
        line_no = txt[:m.start()].count("\n") + 1
        name = m.group(2)
        classes.append({
            "name": name,
            "file": rel_path,
            "line_start": line_no,
            "line_end": line_no,
            "docstring": "",
            "methods": [],
            "has_tests": has_tests,
        })

    return functions, classes


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def _build_qdrant(chunks: list[dict[str, Any]]) -> tuple[Any, bool]:
    """
    Create an in-memory Qdrant collection and upsert all chunks.
    Returns (client, success).
    """
    if QdrantClient is None or qmodels is None or not chunks:
        return None, False

    try:
        client = QdrantClient(location=":memory:")
        if client.collection_exists(collection_name=_COLLECTION):
            client.delete_collection(collection_name=_COLLECTION)
        client.create_collection(
            collection_name=_COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=_EMBED_DIM,
                distance=qmodels.Distance.COSINE,
            ),
        )
        points: list[Any] = []
        for i, chunk in enumerate(chunks):
            embed_text = f"{chunk['name']} {chunk['file']} {chunk.get('docstring', '')} {chunk.get('source_preview', '')}"
            try:
                vec = _embed_text(embed_text, timeout_s=2.0)
            except Exception:
                vec = _hash_embed(embed_text)
            payload = {
                "name": chunk["name"],
                "file": chunk["file"],
                "line": chunk.get("line_start", 0),
                "source_preview": chunk.get("source_preview", "")[:300],
                "kind": chunk.get("kind", "function"),
                "complexity": chunk.get("complexity", "low"),
                "has_tests": chunk.get("has_tests", False),
            }
            points.append(qmodels.PointStruct(id=i, vector=vec, payload=payload))
            if len(points) >= 64:
                client.upsert(collection_name=_COLLECTION, points=points)
                points = []
        if points:
            client.upsert(collection_name=_COLLECTION, points=points)
        return client, True
    except Exception:
        return None, False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_semantic_map(repo_path: str) -> dict[str, Any]:
    """
    Build a semantic index of all Python symbols in a repository.

    Scans up to 200 files and 50 functions/classes per file. If Ollama is
    available, embeds each chunk into an in-memory Qdrant collection named
    ``codebase_chunks``; otherwise uses a hash-based fallback embedding.

    Returns:
        {
          "symbols": {
            "path/to/file.py": {
              "functions": [{"name", "line", "docstring", "complexity", "has_tests", "source_preview"}, ...],
              "classes":   [{"name", "line", "docstring", "methods", "has_tests"}, ...]
            }
          },
          "qdrant_built": bool,
          "chunks_indexed": int,
        }
    """
    global _qdrant_client, _chunk_index, _qdrant_built

    repo = Path(repo_path).resolve()
    symbols: dict[str, Any] = {}
    all_chunks: list[dict[str, Any]] = []

    # Collect all test file stems for has_tests detection
    test_stems: set[str] = set()
    for tf in repo.rglob("test_*.py"):
        if any(p in _SKIP_DIRS for p in tf.parts):
            continue
        # e.g. test_scanner.py → scanner
        stem = tf.stem.removeprefix("test_")
        test_stems.add(stem)
    for tf in repo.rglob("*_test.py"):
        if any(p in _SKIP_DIRS for p in tf.parts):
            continue
        stem = tf.stem.removesuffix("_test")
        test_stems.add(stem)

    file_count = 0
    for py_file in sorted(repo.rglob("*.py")):
        if any(p in _SKIP_DIRS for p in py_file.parts):
            continue
        if file_count >= _MAX_FILES:
            break
        file_count += 1

        try:
            txt = py_file.read_text(errors="ignore")
        except Exception:
            continue

        rel = str(py_file.relative_to(repo))
        has_tests = py_file.stem in test_stems

        funcs, classes = _symbols_via_tree_sitter(txt, rel, has_tests)

        if funcs or classes:
            symbols[rel] = {
                "functions": [
                    {
                        "name": f["name"],
                        "line": f["line_start"],
                        "docstring": f["docstring"],
                        "complexity": f["complexity"],
                        "has_tests": f["has_tests"],
                        "source_preview": f["source_preview"],
                    }
                    for f in funcs
                ],
                "classes": [
                    {
                        "name": c["name"],
                        "line": c["line_start"],
                        "docstring": c["docstring"],
                        "methods": c["methods"],
                        "has_tests": c["has_tests"],
                    }
                    for c in classes
                ],
            }
            for f in funcs:
                all_chunks.append({**f, "kind": "function"})
            for c in classes:
                all_chunks.append({**c, "kind": "class"})

    # Build Qdrant index
    client, ok = _build_qdrant(all_chunks)
    _qdrant_client = client
    _chunk_index = all_chunks
    _qdrant_built = ok

    return {
        "symbols": symbols,
        "qdrant_built": ok,
        "chunks_indexed": len(all_chunks),
    }


def query_codebase(question: str, k: int = 5) -> list[dict[str, Any]]:
    """
    Semantic search over indexed codebase chunks.

    Must call ``build_semantic_map`` first (or the index will be empty).

    Returns list of dicts: {name, file, line, source_preview, score}
    Falls back to keyword search when Qdrant is not available.
    """
    global _qdrant_client, _chunk_index, _qdrant_built

    if not _chunk_index:
        return []

    try:
        q_vec = _embed_text(question, timeout_s=2.0)
    except Exception:
        q_vec = _hash_embed(question)

    # Qdrant path
    if _qdrant_built and _qdrant_client is not None:
        try:
            resp = _qdrant_client.query_points(
                collection_name=_COLLECTION,
                limit=k,
                query=q_vec,
            )
            out: list[dict[str, Any]] = []
            for hit in getattr(resp, "points", None) or []:
                payload = getattr(hit, "payload", None) or {}
                out.append({
                    "name": payload.get("name", ""),
                    "file": payload.get("file", ""),
                    "line": payload.get("line", 0),
                    "source_preview": payload.get("source_preview", ""),
                    "score": float(getattr(hit, "score", 0.0) or 0.0),
                })
            return out
        except Exception:
            pass

    # Cosine fallback
    scored: list[dict[str, Any]] = []
    for chunk in _chunk_index:
        embed_text_str = (
            f"{chunk['name']} {chunk['file']} "
            f"{chunk.get('docstring', '')} {chunk.get('source_preview', '')}"
        )
        try:
            vec = _embed_text(embed_text_str, timeout_s=2.0)
        except Exception:
            vec = _hash_embed(embed_text_str)
        score = _cosine(q_vec, vec)
        scored.append({
            "name": chunk["name"],
            "file": chunk["file"],
            "line": chunk.get("line_start", 0),
            "source_preview": chunk.get("source_preview", ""),
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]
