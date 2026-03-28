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
from datetime import date
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
            patterns = json.loads(FIX_PATTERNS_FILE.read_text())
            # Filter out patterns explicitly marked private
            return [p for p in patterns if not p.get("private")]
        except Exception as e:
            print(f"[RAG] Failed to load fix patterns from {FIX_PATTERNS_FILE}: {e}")
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
            # Accept any non-empty list returned by Ollama — model dimension
            # varies (nomic-embed-text=768, mxbai-embed-large=1024, etc.).
            # Qdrant collection size is set dynamically from the first vector
            # in build_index(), so all vectors will be consistent within a
            # session.  The old `== 64` guard incorrectly rejected every real
            # embedding and silently forced the hash fallback.
            if isinstance(vec, list) and vec:
                return vec
        except Exception as e:
            print(f"[RAG] Ollama embed failed ({EMBED_MODEL}): {e} — using hash fallback")

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


def _recency_weight(last_used: str) -> float:
    """Decay: 1.0 for today, ~0.5 at 30 days, asymptotic to 0."""
    if not last_used:
        return 0.5  # unknown recency — neutral
    try:
        d = date.fromisoformat(last_used)
        days = max(0, (date.today() - d).days)
        return 1.0 / (1.0 + days / 30.0)
    except (ValueError, TypeError):
        return 0.5


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
            # Skip private patterns (double-check here in case _load_patterns is bypassed)
            if p.get("private"):
                continue
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
                if client.collection_exists(collection_name=COLLECTION):
                    client.delete_collection(collection_name=COLLECTION)
                client.create_collection(
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
                # Fetch k*3 candidates for re-ranking with blended score
                resp = self._qdrant.query_points(
                    collection_name=COLLECTION,
                    limit=k * 3,
                    query=query_vec,
                )
                candidates: list[dict] = []
                for h in getattr(resp, "points", None) or []:
                    payload = getattr(h, "payload", None) or {}
                    pattern = payload.get("pattern") or {}
                    cosine_score = float(getattr(h, "score", 0.0) or 0.0)
                    success_rate = float(pattern.get("success_rate", 0.0) or 0.0)
                    recency = _recency_weight(pattern.get("last_used", ""))
                    blended = 0.70 * cosine_score + 0.20 * success_rate + 0.10 * recency
                    candidates.append({**pattern, "score": blended})
                candidates.sort(key=lambda x: x["score"], reverse=True)
                return candidates[:k]
            except Exception as e:
                print(f"[RAG] Qdrant query failed — fallback to cosine scoring: {e}")

        scored = []
        for item in self._index:
            cosine_score = _cosine(query_vec, item["vector"])
            pattern = item["pattern"]
            success_rate = float(pattern.get("success_rate", 0.0) or 0.0)
            recency = _recency_weight(pattern.get("last_used", ""))
            blended = 0.70 * cosine_score + 0.20 * success_rate + 0.10 * recency
            scored.append({**pattern, "score": blended})
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
