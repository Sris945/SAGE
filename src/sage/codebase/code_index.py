"""
Vector-backed code chunk index (spec §3 Stage 2).

Persists Qdrant storage under ``<repo>/.sage/qdrant_code_index/`` and retrieves
top-k chunks for planner/coder prefixes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sage.llm.embeddings import embed_text

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # pragma: no cover
    QdrantClient = None  # type: ignore[assignment]
    qmodels = None  # type: ignore[assignment]

_COLLECTION = "code_chunks"
_VECTOR_SIZE = 64
_SKIP_DIRS = frozenset(
    {".venv", "venv", ".git", "__pycache__", ".mypy_cache", "node_modules", ".tox"}
)


def _qdrant_path(repo: Path) -> Path:
    return repo / ".sage" / "qdrant_code_index"


def _manifest_path(repo: Path) -> Path:
    return repo / ".sage" / "code_index_manifest.json"


def _file_hash(p: Path) -> str:
    try:
        data = p.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()


def _iter_py_files(repo: Path) -> list[Path]:
    out: list[Path] = []
    for p in repo.rglob("*.py"):
        if any(x in _SKIP_DIRS for x in p.parts):
            continue
        out.append(p)
    return sorted(out)


def _chunk_text(rel: str, text: str) -> list[tuple[str, str]]:
    """Return list of (chunk_id, snippet) — cap size per chunk."""
    max_len = 4000
    if len(text) <= max_len:
        return [(rel + ":0", text)]
    chunks: list[tuple[str, str]] = []
    for i, start in enumerate(range(0, len(text), max_len)):
        chunks.append((f"{rel}:{i}", text[start : start + max_len]))
    return chunks


def _stable_point_id(rel: str, chunk_key: str) -> int:
    h = hashlib.sha256(f"{rel}\0{chunk_key}".encode()).digest()
    return int.from_bytes(h[:8], "big") % (2**63)


def index_repo(repo_path: str, *, incremental: bool = True) -> int:
    """
    Embed Python file chunks and upsert into local Qdrant. Returns chunk count indexed this run.
    """
    if QdrantClient is None or qmodels is None:
        return 0
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        return 0
    sage = repo / ".sage"
    sage.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}
    mp = _manifest_path(repo)
    if incremental and mp.exists():
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    client = QdrantClient(path=str(_qdrant_path(repo)))
    try:
        client.get_collection(_COLLECTION)
    except Exception:
        try:
            client.create_collection(
                collection_name=_COLLECTION,
                vectors_config=qmodels.VectorParams(
                    size=_VECTOR_SIZE, distance=qmodels.Distance.COSINE
                ),
            )
        except Exception:
            return 0

    indexed = 0
    points: list[qmodels.PointStruct] = []
    new_manifest: dict[str, str] = {}

    for py in _iter_py_files(repo):
        rel = str(py.relative_to(repo))
        fh = _file_hash(py)
        new_manifest[rel] = fh
        if incremental and manifest.get(rel) == fh:
            continue
        try:
            raw = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for cid, snippet in _chunk_text(rel, raw):
            vec = embed_text(f"{rel}\n{snippet[:2000]}", timeout_s=1.5)
            pid = _stable_point_id(rel, cid)
            points.append(
                qmodels.PointStruct(
                    id=pid,
                    vector=vec,
                    payload={"path": rel, "chunk_id": cid, "text": snippet[:6000]},
                )
            )
            indexed += 1
            if len(points) >= 64:
                client.upsert(collection_name=_COLLECTION, points=points)
                points = []

    if points:
        client.upsert(collection_name=_COLLECTION, points=points)

    try:
        mp.write_text(json.dumps(new_manifest, indent=2), encoding="utf-8")
    except OSError:
        pass
    return indexed


def retrieve_code_context(query: str, repo_path: str, k: int = 5) -> str:
    """Return a markdown-ish string of top-k code snippets for prompts."""
    if QdrantClient is None or qmodels is None:
        return ""
    repo = Path(repo_path).resolve()
    qp = _qdrant_path(repo)
    if not qp.exists():
        return ""
    client = QdrantClient(path=str(qp))
    try:
        client.get_collection(_COLLECTION)
    except Exception:
        return ""
    qv = embed_text(query, timeout_s=2.0)
    try:
        qr = client.query_points(collection_name=_COLLECTION, query=qv, limit=k)
        hits = getattr(qr, "points", None) or []
    except Exception:
        return ""
    lines: list[str] = []
    for h in hits:
        pl = (h.payload or {}) if hasattr(h, "payload") else {}
        path = pl.get("path", "")
        txt = (pl.get("text") or "")[:1200]
        score = getattr(h, "score", None)
        sc = f"{float(score):.3f}" if score is not None else "n/a"
        lines.append(f"- **{path}** (score={sc})\n```\n{txt}\n```")
    return "\n\n".join(lines) if lines else ""


def ensure_index_for_brief(repo_path: str, brief: dict[str, Any]) -> dict[str, Any]:
    """Call from ``build_codebase_brief``: index + attach retrieval snippet."""
    try:
        n = index_repo(repo_path, incremental=True)
        brief = dict(brief)
        brief["code_index_chunks_indexed"] = n
        q = (
            brief.get("codebase_summary", "")
            or " ".join(str(x) for x in brief.get("suggested_next_tasks", [])[:5])
        )[:500]
        brief["retrieved_code_chunks"] = retrieve_code_context(q, repo_path, k=5)
    except Exception:
        brief = dict(brief)
        brief.setdefault("retrieved_code_chunks", "")
    return brief
