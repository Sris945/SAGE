"""
NL intent routing for the interactive shell: avoid sending greetings / meta chatter
through the full ``sage run`` pipeline.

Heuristics include casual phrases (e.g. “do me a favor”), thanks, and non-technical
lines that end with ``?`` unless they mention obvious coding signals (pytest, API,
``src/``, etc.). For harder cases, set ``SAGE_SHELL_INTENT=ollama``.

Env:
  SAGE_SHELL_INTENT — ``off`` (always pipeline), ``heuristic`` (rules only),
  ``ollama`` (heuristics, then small local classifier).
  SAGE_SHELL_INTENT_TIMEOUT_S — cap for the classifier chat call (default 15s; 0 = use global ollama timeout).
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Optional


class ShellIntentKind(str, Enum):
    CODE = "code"
    CHAT = "chat"
    HELP = "help"


_GREETING_TOKENS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "howdy",
        "greetings",
        "hiya",
        "hai",
    }
)

# Substrings → treat as small talk / meta (not repo work).
_CHAT_PHRASES: tuple[str, ...] = (
    "do me a favor",
    "do me a favour",
    "thank you",
    "thanks",
    "much appreciated",
    "humor me",
    "humour me",
    "just curious",
    "off topic",
    "small talk",
    "never mind",
    "nevermind",
    "you're welcome",
    "youre welcome",
    "very well",
)

# If a line ends with "?" and contains none of these *word* signals, assume chat (not coding).
_CODE_SIGNAL_PATTERN = re.compile(
    r"(?i)\b("
    r"implement|refactor|pytest|docker|dockerfile|endpoint|traceback|fastapi|flask|kubernetes|"
    r"unittest|ollama|commit|merge|branch|pull\s*request|greenfield|dag|planner|"
    r"bug\b|exception|stack\s*trace|deploy|build\b|compile|lint|mypy|ruff|"
    r"function|class\b|module|import\b|api\b|route\b|endpoint|middleware|"
    r"\.py\b|\.ts\b|\.tsx\b|\.js\b|src/|tests/|test_\w+|"
    r"add\s+a\s+(route|test|file|endpoint)|create\s+a\s+(new\s+)?(file|app|route|test)|"
    r"fix\s+(the|a)\s+|write\s+tests|debug|error:|traceback"
    r")\b"
)


def _normalize_words(line: str) -> list[str]:
    s = (line or "").strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return [w for w in s.split() if w]


def heuristic_intent(line: str) -> Optional[ShellIntentKind]:
    """
    Fast path: obvious greetings and short help/meta queries → chat/help.
    Returns None when the line should be classified as code or passed to the SLM.
    """
    raw = (line or "").strip()
    if not raw:
        return ShellIntentKind.CHAT

    words = _normalize_words(raw)
    if not words:
        return ShellIntentKind.CHAT

    if len(words) <= 2 and all(w in _GREETING_TOKENS for w in words):
        return ShellIntentKind.CHAT
    if len(words) == 1 and words[0] in _GREETING_TOKENS:
        return ShellIntentKind.CHAT

    joined = " ".join(words)
    help_patterns = (
        "what can you do",
        "what can sage",
        "what does sage",
        "how do i use",
        "how to use sage",
        "list commands",
        "show commands",
        "help me",
        "where are",
    )
    if any(p in joined for p in help_patterns):
        return ShellIntentKind.HELP
    if raw.strip() in ("?", "help", "h", "/help", "hellp", "hel"):
        return ShellIntentKind.HELP

    low = raw.lower()
    for phrase in _CHAT_PHRASES:
        if phrase in low:
            # "very well" alone is weak; pair with favor / thanks / etc. or short line.
            if phrase == "very well":
                if any(
                    x in low
                    for x in ("favor", "favour", "thanks", "then", "okay", "ok")
                ):
                    return ShellIntentKind.CHAT
                continue
            return ShellIntentKind.CHAT

    # Rhetorical / personal questions without technical vocabulary → chat.
    if raw.rstrip().endswith("?"):
        if not _CODE_SIGNAL_PATTERN.search(raw):
            return ShellIntentKind.CHAT

    # Polite one-liners (no code signals).
    if len(words) <= 8 and not _CODE_SIGNAL_PATTERN.search(raw):
        polite = (
            "please",
            "thanks",
            "thank",
            "appreciate",
            "sorry",
            "cool",
            "nice",
            "awesome",
            "great",
            "good",
            "wow",
            "lol",
            "haha",
        )
        if any(w in polite for w in words) and not _CODE_SIGNAL_PATTERN.search(raw):
            return ShellIntentKind.CHAT

    return None


def _parse_json_object(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if "```" in t:
        parts = t.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            if inner.lstrip().lower().startswith("json"):
                inner = inner.split("\n", 1)[-1]
            t = inner.strip()
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _ollama_classify_intent(line: str) -> ShellIntentKind:
    """
    Small local model returns JSON: {"intent":"code"|"chat"|"help","confidence":0..1}
    On any failure, returns CODE.
    """
    try:
        from sage.llm.ollama_safe import chat_with_timeout
        from sage.orchestrator.model_router import ModelRouter

        router = ModelRouter()
        model = router.select("shell_router", task_complexity_score=0.0, failure_count=0)
    except Exception:
        return ShellIntentKind.CODE

    raw_timeout = (os.environ.get("SAGE_SHELL_INTENT_TIMEOUT_S") or "").strip()
    timeout_s: float | None
    if raw_timeout == "":
        timeout_s = 15.0
    else:
        try:
            v = float(raw_timeout)
            timeout_s = None if v <= 0 else v
        except ValueError:
            timeout_s = 15.0

    system = (
        "You classify a single user line for a coding assistant shell (SAGE).\n"
        'Reply with ONLY a JSON object: {"intent":"code"|"chat"|"help","confidence":0.0}.\n'
        "- code: user wants repo edits, features, bugs, tests, refactors, or technical work.\n"
        "- chat: casual conversation, thanks, greetings not already handled, small talk.\n"
        "- help: user asks what SAGE can do, how to use commands, or meta help.\n"
        "No markdown, no prose."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": line},
    ]
    try:
        resp = chat_with_timeout(model=model, messages=messages, timeout_s=timeout_s)
    except Exception:
        return ShellIntentKind.CODE

    content = ""
    try:
        content = (resp.get("message") or {}).get("content") or ""
    except Exception:
        pass
    data = _parse_json_object(content) if content else None
    if not isinstance(data, dict):
        return ShellIntentKind.CODE
    intent_raw = str(data.get("intent", "code")).lower().strip()
    try:
        return ShellIntentKind(intent_raw)
    except ValueError:
        return ShellIntentKind.CODE


def intent_mode() -> str:
    return (os.environ.get("SAGE_SHELL_INTENT") or "heuristic").strip().lower()


def classify_shell_line_ex(line: str) -> tuple[ShellIntentKind, bool]:
    """
    Returns ``(intent, matched_heuristic)``. The second flag is True when
    :func:`heuristic_intent` decided (no SLM call).
    """
    if intent_mode() == "off":
        return ShellIntentKind.CODE, False

    h = heuristic_intent(line)
    if h is not None:
        return h, True

    if intent_mode() == "heuristic":
        return ShellIntentKind.CODE, False

    if intent_mode() == "ollama":
        return _ollama_classify_intent(line), False

    return ShellIntentKind.CODE, False


def classify_shell_line(line: str) -> ShellIntentKind:
    """
    Decide how to route a non-command shell line.
    ``off`` → always CODE (legacy NL → pipeline).
    """
    return classify_shell_line_ex(line)[0]
