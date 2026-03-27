"""
Docs RAG Retriever (Phase 4+)
-------------------------------
In-memory docs retriever backed by Qdrant (no external vector DB server).

This is a lightweight MVP to satisfy the "Qdrant vector store" + "Prompt
Intelligence Middleware (RAG over docs)" requirements without relying on
Ollama embeddings.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels


_DOCS_COLLECTION = "sage_docs_rag"
_EMBED_DIM = 64

_CACHE: dict[str, Any] = {
    "built": False,
    "client": None,
    "chunks": [],  # list[str]
}


def _embed(text: str, *, size: int = _EMBED_DIM) -> list[float]:
    # Deterministic hashed-token embeddings (fast, offline).
    vec = [0.0] * size
    for tok in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % size] += 1.0
    # L2 normalize for cosine similarity.
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def _chunk_md(text: str, *, max_chunk_chars: int = 900) -> list[str]:
    # Chunk on paragraph boundaries; keep chunk sizes bounded.
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 > max_chunk_chars and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        chunks.append(buf)
    return chunks[:120]


def _gather_sources() -> list[Path]:
    sources: list[Path] = []
    if Path("docs").exists() and Path("docs").is_dir():
        sources.extend(sorted(Path("docs").rglob("*.md"))[:50])
    if Path("README.md").exists():
        sources.append(Path("README.md"))
    return sources


def _build_index() -> None:
    if _CACHE["built"]:
        return

    chunks: list[str] = []
    sources = _gather_sources()
    for sp in sources:
        try:
            txt = sp.read_text(errors="ignore")
        except Exception:
            continue
        chunks.extend(_chunk_md(txt))
        if len(chunks) >= 200:
            break

    client = QdrantClient(location=":memory:")
    # Recreate collection each run in this process.
    try:
        client.recreate_collection(
            collection_name=_DOCS_COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=_EMBED_DIM,
                distance=qmodels.Distance.COSINE,
            ),
        )
    except Exception:
        # If recreate fails, just proceed; query will fall back in workflow.
        pass

    points = [
        qmodels.PointStruct(
            id=i,
            vector=_embed(ch),
            payload={"text": ch},
        )
        for i, ch in enumerate(chunks)
    ]
    if points:
        client.upsert(collection_name=_DOCS_COLLECTION, points=points)

    _CACHE["client"] = client
    _CACHE["chunks"] = chunks
    _CACHE["built"] = True


def get_docs_rag_context(prompt: str, *, k: int = 3) -> str:
    """
    Return a markdown snippet for the top-k relevant docs chunks.
    """
    try:
        _build_index()
        client: QdrantClient | None = _CACHE.get("client")
        if client is None:
            return ""
        hits = client.query_points(
            collection_name=_DOCS_COLLECTION,
            query=_embed(prompt),
            limit=k,
        )
        top_texts: list[str] = []
        for h in getattr(hits, "points", None) or []:
            payload = h.payload or {}
            txt = payload.get("text") or ""
            if txt.strip():
                top_texts.append(str(txt))
        if not top_texts:
            return ""

        return "\n\nRELEVANT DOCS CONTEXT (RAG over docs):\n" + "\n\n".join(
            [f"### DOC SNIPPET {i + 1}\n{t[:900]}" for i, t in enumerate(top_texts)]
        )
    except Exception:
        return ""
