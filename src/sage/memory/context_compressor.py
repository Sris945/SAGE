"""
SAGE Context Compressor
-----------------------
Retrieves only the most relevant code chunks for a given task description,
keeping the prompt within local model context limits (~8K–32K tokens).

Strategy (degrading gracefully with available infrastructure):
  1. Qdrant semantic search if code_index is built (best quality)
  2. BM25-style TF-IDF keyword matching (no embeddings needed, fast)
  3. Grep-based exact token match (always available, last resort)

The compressor is called from CoderAgent.run_loop() and injects a lean
"CODEBASE CONTEXT" block instead of dumping all referenced files verbatim.

Key parameters:
  MAX_CONTEXT_CHARS: total chars injected (~4K tokens for a 14B model)
  MAX_CHUNKS: how many code chunks to include
  CHUNK_SIZE: chars per code chunk
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SKIP_DIRS = frozenset({".venv", "venv", ".git", "__pycache__", ".mypy_cache",
                         "node_modules", ".tox", ".sage"})
_CODE_EXTS = frozenset({".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs",
                         ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".php"})

MAX_CONTEXT_CHARS = 16_000   # ~4K tokens — safe for 14B model at 32K ctx
MAX_CHUNKS = 12
CHUNK_SIZE = 1_400            # ~350 tokens per chunk


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class CodeChunk:
    file: str          # relative path
    start_line: int
    content: str
    score: float = 0.0


@dataclass
class CompressionResult:
    chunks: list[CodeChunk] = field(default_factory=list)
    total_chars: int = 0
    strategy: str = "none"

    def to_prompt_block(self) -> str:
        if not self.chunks:
            return ""
        lines = [f"CODEBASE CONTEXT [{self.strategy}, {len(self.chunks)} chunks]:"]
        for c in self.chunks:
            lines.append(f"\n### {c.file} (line {c.start_line})")
            lines.append(f"```\n{c.content.strip()}\n```")
        return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def compress_context(
    task_description: str,
    repo_root: Path | str | None = None,
    max_chars: int = MAX_CONTEXT_CHARS,
    max_chunks: int = MAX_CHUNKS,
) -> CompressionResult:
    """
    Return the most relevant code chunks for *task_description*.
    Falls back gracefully through 3 strategies.
    """
    root = Path(repo_root or Path.cwd()).resolve()

    # Strategy 1: Qdrant semantic search
    result = _try_qdrant_search(task_description, root, max_chars, max_chunks)
    if result is not None:
        return result

    # Strategy 2: TF-IDF keyword matching
    result = _tfidf_search(task_description, root, max_chars, max_chunks)
    if result.chunks:
        return result

    # Strategy 3: Grep exact token match
    return _grep_search(task_description, root, max_chars, max_chunks)


# ── Strategy 1: Qdrant ────────────────────────────────────────────────────────

def _try_qdrant_search(
    query: str, root: Path, max_chars: int, max_chunks: int
) -> CompressionResult | None:
    """Use the existing Qdrant code index if available. Returns None on any failure."""
    try:
        from qdrant_client import QdrantClient  # type: ignore
        from sage.llm.embeddings import embed_text

        qdrant_path = root / ".sage" / "qdrant_code_index"
        if not qdrant_path.exists():
            return None

        client = QdrantClient(path=str(qdrant_path))
        query_vec = embed_text(query)
        if not query_vec:
            return None

        hits = client.search(
            collection_name="code_chunks",
            query_vector=query_vec,
            limit=max_chunks * 2,
        )
        if not hits:
            return None

        chunks: list[CodeChunk] = []
        total = 0
        for hit in hits:
            payload = hit.payload or {}
            content = str(payload.get("text") or payload.get("content") or "")
            if not content.strip():
                continue
            file_path = str(payload.get("file") or payload.get("rel") or "")
            start_line = int(payload.get("start_line") or 0)
            if total + len(content) > max_chars:
                content = content[: max_chars - total]
            chunk = CodeChunk(
                file=file_path,
                start_line=start_line,
                content=content,
                score=float(hit.score),
            )
            chunks.append(chunk)
            total += len(content)
            if len(chunks) >= max_chunks or total >= max_chars:
                break

        if not chunks:
            return None

        result = CompressionResult(chunks=chunks, total_chars=total, strategy="qdrant")
        return result

    except Exception:
        return None


# ── Strategy 2: TF-IDF keyword matching ──────────────────────────────────────

def _tfidf_search(
    query: str, root: Path, max_chars: int, max_chunks: int
) -> CompressionResult:
    """
    Lightweight BM25-style search over code files.
    No embeddings, no external dependencies.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return CompressionResult(strategy="tfidf")

    # Gather all code files
    code_files: list[Path] = []
    for ext in _CODE_EXTS:
        for f in root.rglob(f"*{ext}"):
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            code_files.append(f)

    if not code_files:
        return CompressionResult(strategy="tfidf")

    # Build chunk frequency (BM25-style IDF over chunks, not files — intentional approximation)
    chunk_freq: dict[str, int] = defaultdict(int)
    file_chunks: list[tuple[Path, int, str]] = []  # (path, start_line, content)

    for fpath in code_files:
        try:
            text = fpath.read_text(errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        for i in range(0, len(lines), 30):  # 30-line chunks
            chunk_lines = lines[i: i + 40]
            chunk_text = "\n".join(chunk_lines)
            tokens = set(_tokenize(chunk_text))
            for tok in tokens:
                chunk_freq[tok] += 1
            file_chunks.append((fpath, i + 1, chunk_text))

    n_chunks = max(len(file_chunks), 1)

    # Score each chunk
    scored: list[tuple[float, Path, int, str]] = []
    for fpath, start_line, chunk_text in file_chunks:
        chunk_tokens = _tokenize(chunk_text)
        if not chunk_tokens:
            continue
        tf_counts: dict[str, int] = defaultdict(int)
        for t in chunk_tokens:
            tf_counts[t] += 1
        score = 0.0
        for qt in query_tokens:
            if qt not in tf_counts:
                continue
            tf = tf_counts[qt] / len(chunk_tokens)
            idf = math.log((n_chunks + 1) / (chunk_freq.get(qt, 0) + 1)) + 1.0
            score += tf * idf
        if score > 0:
            scored.append((score, fpath, start_line, chunk_text))

    scored.sort(key=lambda x: x[0], reverse=True)

    chunks: list[CodeChunk] = []
    total = 0

    for score, fpath, start_line, content in scored:
        rel = str(fpath.relative_to(root))
        # Limit to 2 chunks per file (avoid flooding with one big file)
        file_count = sum(1 for c in chunks if c.file == rel)
        if file_count >= 2:
            continue
        if total + len(content) > max_chars:
            content = content[: max_chars - total]
        chunks.append(CodeChunk(file=rel, start_line=start_line, content=content, score=score))
        total += len(content)
        if len(chunks) >= max_chunks or total >= max_chars:
            break

    return CompressionResult(chunks=chunks, total_chars=total, strategy="tfidf")


# ── Strategy 3: Grep ─────────────────────────────────────────────────────────

def _grep_search(
    query: str, root: Path, max_chars: int, max_chunks: int
) -> CompressionResult:
    """Last-resort: find files containing query tokens, return head of each."""
    tokens = [t for t in _tokenize(query) if len(t) >= 4][:8]
    if not tokens:
        return CompressionResult(strategy="grep")

    chunks: list[CodeChunk] = []
    total = 0

    for ext in _CODE_EXTS:
        for fpath in sorted(root.rglob(f"*{ext}")):
            if any(part in _SKIP_DIRS for part in fpath.parts):
                continue
            try:
                text = fpath.read_text(errors="replace")
            except OSError:
                continue
            text_lower = text.lower()
            hits = sum(1 for t in tokens if t in text_lower)
            if hits == 0:
                continue
            content = text[:CHUNK_SIZE]
            rel = str(fpath.relative_to(root))
            chunks.append(CodeChunk(file=rel, start_line=1, content=content, score=float(hits)))
            total += len(content)
            if len(chunks) >= max_chunks or total >= max_chars:
                break
        if len(chunks) >= max_chunks or total >= max_chars:
            break

    chunks.sort(key=lambda c: c.score, reverse=True)
    return CompressionResult(chunks=chunks, total_chars=total, strategy="grep")


# ── Helpers ───────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")


def _tokenize(text: str) -> list[str]:
    """Extract identifier-like tokens, lowercase, deduplicated."""
    raw = _TOKEN_RE.findall(text or "")
    seen: set[str] = set()
    result: list[str] = []
    for t in raw:
        lt = t.lower()
        if lt not in seen and lt not in _STOPWORDS:
            seen.add(lt)
            result.append(lt)
    return result


_STOPWORDS = frozenset({
    "def", "class", "return", "import", "from", "self", "none", "true", "false",
    "and", "or", "not", "in", "is", "if", "else", "elif", "for", "while",
    "with", "try", "except", "finally", "raise", "pass", "break", "continue",
    "lambda", "yield", "async", "await", "str", "int", "bool", "list", "dict",
    "set", "tuple", "type", "any", "the", "a", "an", "to", "of", "that",
    "this", "it", "as", "be", "by", "at", "on", "all", "each", "when",
})
