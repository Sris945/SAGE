"""
SAGE RAG Retriever
------------------
Provides semantic search over fix_patterns.json using:
  - nomic-embed-text:latest (via local Ollama) for embeddings
  - qdrant-client in-memory mode (no server needed)

Usage:
    retriever = RagRetriever()
    retriever.build_index()                      # call once per session
    results = retriever.query("import error", k=3)
    # → [{"suspected_cause": ..., "fix_file": ..., "score": 0.92}, ...]

The retriever is stateless across sessions — it rebuilds from fix_patterns.json
each time (fast, patterns are small). Phase 5 upgrades to persistent Qdrant server.
"""

import json
from pathlib import Path
import hashlib
import re

try:
    import ollama  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ollama = None

from sage.llm.ollama_safe import embeddings_with_timeout

FIX_PATTERNS_FILE = Path("memory") / "fixes" / "error_patterns.json"
EMBED_MODEL = "nomic-embed-text:latest"
COLLECTION = "fix_patterns"

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # pragma: no cover
    QdrantClient = None  # type: ignore[assignment]
    qmodels = None  # type: ignore[assignment]


def _load_patterns() -> list[dict]:
    if FIX_PATTERNS_FILE.exists():
        try:
            return json.loads(FIX_PATTERNS_FILE.read_text())
        except Exception:
            pass
    return []


def _embed(text: str) -> list[float]:
    """Get embedding vector from local Ollama nomic-embed-text."""
    if ollama is not None:
        try:
            # Use a short timeout: if Ollama is slow/unresponsive we
            # immediately fall back to deterministic embeddings so indexing
            # remains bounded.
            # Keep this low because the retriever is called frequently inside
            # the workflow retry loop (benchmarks must not stall on embeddings).
            vec = embeddings_with_timeout(model=EMBED_MODEL, prompt=text, timeout_s=0.25)
            # Enforce fixed dimension so vector-store indexing doesn't
            # fail when Ollama returns a different embedding size.
            if isinstance(vec, list) and len(vec) == 64:
                return vec
        except Exception:
            pass

    # Fallback: cheap deterministic "bag of hashed tokens" embedding.
    # This enables the retriever to remain usable without the ollama package.
    size = 64
    vec = [0.0] * size
    for tok in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % size] += 1.0
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity (no numpy needed)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RagRetriever:
    """
    Lightweight in-memory RAG over fix_patterns.json.
    Falls back to keyword search if Qdrant is unavailable.
    """

    def __init__(self):
        self._index: list[dict] = []  # [{pattern, vector}, ...]
        self._built = False
        self._qdrant = None
        self._use_qdrant = False

    def build_index(self) -> int:
        """
        Load patterns and embed them. Returns number of patterns indexed.
        Skips patterns that already failed to embed.
        """
        patterns = _load_patterns()
        if not patterns:
            self._built = True
            return 0

        print(f"[RAG] Building index from {len(patterns)} fix pattern(s)...")
        self._index = []

        for p in patterns:
            # Build a rich query text from the pattern fields
            text = " ".join(
                filter(
                    None,
                    [
                        p.get("suspected_cause", ""),
                        p.get("error_signature", ""),
                        p.get("fix_file", ""),
                        p.get("fix_operation", ""),
                        p.get("fix_patch", "")[:500],  # cap to limit embedding prompt size
                    ],
                )
            )
            if not text.strip():
                continue
            try:
                vec = _embed(text)
                self._index.append({"pattern": p, "vector": vec})
            except Exception as e:
                print(f"[RAG] Warning: embed failed for pattern — {e}")

        self._built = True

        # Optional Phase 4: Qdrant vector store (in-memory).
        # If qdrant is unavailable or collection creation fails, we fall back
        # to the existing pure-Python cosine scoring.
        try:
            if QdrantClient is not None and qmodels is not None and self._index:
                dim = len(self._index[0]["vector"])
                client = QdrantClient(location=":memory:")
                client.recreate_collection(
                    collection_name=COLLECTION,
                    vectors_config=qmodels.VectorParams(
                        size=dim,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
                points = [
                    qmodels.PointStruct(
                        id=i,
                        vector=item["vector"],
                        payload={"pattern": item["pattern"]},
                    )
                    for i, item in enumerate(self._index)
                ]
                client.upsert(collection_name=COLLECTION, points=points)
                self._qdrant = client
                self._use_qdrant = True
        except Exception as e:
            print(f"[RAG] Qdrant unavailable/fallback to cosine scoring: {e}")
            self._qdrant = None
            self._use_qdrant = False

        print(f"[RAG] Index ready — {len(self._index)} pattern(s) embedded.")
        return len(self._index)

    def query(self, query_text: str, k: int = 3) -> list[dict]:
        """
        Semantic search. Returns top-K patterns with similarity score.
        Falls back to substring keyword match if index is empty.
        """
        if not self._built:
            self.build_index()

        if not self._index:
            return self._keyword_fallback(query_text, k)

        try:
            query_vec = _embed(query_text)
        except Exception as e:
            print(f"[RAG] Embed query failed: {e} — using keyword fallback")
            return self._keyword_fallback(query_text, k)

        if self._use_qdrant and self._qdrant is not None:
            try:
                resp = self._qdrant.query_points(
                    collection_name=COLLECTION,
                    limit=k,
                    query=query_vec,
                )
                out: list[dict] = []
                for h in getattr(resp, "points", None) or []:
                    payload = getattr(h, "payload", None) or {}
                    pattern = payload.get("pattern") or {}
                    score_val = float(getattr(h, "score", 0.0) or 0.0)
                    out.append({**pattern, "score": score_val})
                return out
            except Exception as e:
                print(f"[RAG] Qdrant query failed — fallback to cosine scoring: {e}")

        scored = [
            {**item["pattern"], "score": _cosine(query_vec, item["vector"])} for item in self._index
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    def _keyword_fallback(self, query: str, k: int) -> list[dict]:
        """Substring match on suspected_cause / fix_file fields."""
        patterns = _load_patterns()
        q = query.lower()
        matched = [
            {**p, "score": 0.5}
            for p in patterns
            if q in (p.get("suspected_cause", "") + p.get("fix_file", "")).lower()
        ]
        return matched[:k]


def format_patterns_for_prompt(patterns: list[dict]) -> str:
    """Render retrieved fix patterns as a concise prompt snippet."""
    if not patterns:
        return ""
    lines = ["RELEVANT FIX PATTERNS (auto-learned from past sessions):"]
    for p in patterns:
        cause = p.get("suspected_cause", p.get("error_signature", "unknown"))
        fix = p.get("fix_file", p.get("fix_operation", p.get("fix_patch", "")))
        count = p.get("times_applied", p.get("success_count", 0))
        sr = p.get("success_rate", p.get("success_rate_ema", 0))
        score = p.get("score", 0)
        lines.append(
            f"  - Error: {cause} → Fix: {fix} (used {count}×, success_rate={sr:.2f}, score={score:.2f})"
        )
    return "\n".join(lines)
