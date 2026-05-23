"""
SAGE Codebase Indexer
---------------------
Builds a Qdrant vector index over the project's source files for semantic
retrieval by the context compressor.

Usage
-----
    from sage.memory.code_indexer import build_index, incremental_update

    build_index(root=Path.cwd())           # full rebuild
    incremental_update(root, changed_files) # update changed files only

CLI entry point: ``sage index`` (wired in main.py).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_COLLECTION = "code_chunks"
_CHUNK_LINES = 40
_STRIDE_LINES = 30
_CODE_EXTS = {".py", ".ts", ".js", ".jsx", ".tsx", ".go", ".rs", ".java",
              ".cpp", ".c", ".h", ".md", ".yaml", ".yml", ".toml", ".json"}
_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules",
              ".sage", "dist", "build", ".mypy_cache", ".pytest_cache"}


def _chunk_file(fpath: Path, root: Path) -> list[dict[str, Any]]:
    try:
        text = fpath.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    rel = str(fpath.relative_to(root))
    chunks = []
    for i in range(0, max(len(lines), 1), _STRIDE_LINES):
        chunk_lines = lines[i: i + _CHUNK_LINES]
        content = "\n".join(chunk_lines).strip()
        if not content:
            continue
        uid = hashlib.sha256(f"{rel}:{i}:{content[:200]}".encode()).hexdigest()
        chunks.append({
            "id": uid,
            "file": rel,
            "start_line": i + 1,
            "content": content,
        })
    return chunks


def _embed(text: str) -> list[float]:
    from sage.llm.embeddings import embed_text
    return embed_text(text, timeout_s=10.0)


def _iter_source_files(root: Path):
    for fpath in root.rglob("*"):
        if fpath.is_file() and fpath.suffix in _CODE_EXTS:
            if not any(part in _SKIP_DIRS for part in fpath.parts):
                yield fpath


def _qdrant_path(root: Path) -> Path:
    return root / ".sage" / "qdrant_code_index"


def build_index(root: Path = Path("."), *, verbose: bool = True) -> dict[str, Any]:
    """Full index rebuild. Returns stats dict."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
    except ImportError:
        return {"ok": False, "error": "qdrant-client not installed — run: pip install qdrant-client"}

    sample_vec = _embed("hello world")
    dim = len(sample_vec)

    qpath = _qdrant_path(root)
    client = QdrantClient(path=str(qpath))

    # Recreate collection
    try:
        client.delete_collection(_COLLECTION)
    except Exception:
        pass
    client.create_collection(
        collection_name=_COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    files = list(_iter_source_files(root))
    if verbose:
        print(f"[SAGE index] Indexing {len(files)} files …")

    total_chunks = 0
    batch: list[PointStruct] = []

    def _flush():
        if batch:
            client.upsert(collection_name=_COLLECTION, points=batch)
            batch.clear()

    for fpath in files:
        chunks = _chunk_file(fpath, root)
        for ch in chunks:
            vec = _embed(ch["content"])
            batch.append(PointStruct(
                id=abs(hash(ch["id"])) % (2 ** 63),
                vector=vec,
                payload=ch,
            ))
            total_chunks += 1
            if len(batch) >= 64:
                _flush()

    _flush()

    if verbose:
        print(f"[SAGE index] Done — {total_chunks} chunks from {len(files)} files → {qpath}")

    return {"ok": True, "files": len(files), "chunks": total_chunks, "dim": dim,
            "index_path": str(qpath)}


def incremental_update(root: Path, changed_files: list[Path], *, verbose: bool = False) -> None:
    """Re-index only changed files. No-ops if index doesn't exist yet."""
    qpath = _qdrant_path(root)
    if not qpath.exists():
        return
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
    except ImportError:
        return

    client = QdrantClient(path=str(qpath))

    for fpath in changed_files:
        if not fpath.is_file() or fpath.suffix not in _CODE_EXTS:
            continue
        rel = str(fpath.relative_to(root))
        # Delete all existing points for this file
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            client.delete(
                collection_name=_COLLECTION,
                points_selector=Filter(
                    must=[FieldCondition(key="file", match=MatchValue(value=rel))]
                ),
            )
        except Exception:
            pass
        # Re-insert chunks
        chunks = _chunk_file(fpath, root)
        points = []
        for ch in chunks:
            vec = _embed(ch["content"])
            points.append(PointStruct(
                id=abs(hash(ch["id"])) % (2 ** 63),
                vector=vec,
                payload=ch,
            ))
        if points:
            client.upsert(collection_name=_COLLECTION, points=points)
        if verbose:
            logger.info("Re-indexed %s (%d chunks)", rel, len(points))
