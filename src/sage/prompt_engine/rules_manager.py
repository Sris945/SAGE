"""
User rules loading and light-weight validation (spec §18).

Merge order matches ``prefix_builder`` behaviour: global → project →
agent-specific → legacy project file. Conflicts are not resolved
automatically; layers are concatenated with blank lines (later text wins
only by model attention, not programmatic override).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RulesLayer:
    label: str
    path: Path
    text: str


def discover_rule_paths(*, agent_role: str, base_dir: Path) -> list[tuple[str, Path]]:
    """Ordered (label, path) tuples for existing rule files."""
    role = (agent_role or "coder").strip().lower()
    global_rules = Path.home() / ".sage" / "rules.md"
    project_rules = base_dir / ".sage" / "rules.md"
    agent_rules = base_dir / ".sage" / f"rules.{role}.md"
    legacy = base_dir / ".sage-rules.md"
    out: list[tuple[str, Path]] = []
    if global_rules.is_file():
        out.append(("global ~/.sage/rules.md", global_rules))
    if project_rules.is_file():
        out.append(("project .sage/rules.md", project_rules))
    if agent_rules.is_file():
        out.append((f"agent .sage/rules.{role}.md", agent_rules))
    if legacy.is_file():
        out.append(("legacy .sage-rules.md", legacy))
    return out


def load_rule_layers(*, agent_role: str, base_dir: Path) -> list[RulesLayer]:
    layers: list[RulesLayer] = []
    for label, path in discover_rule_paths(agent_role=agent_role, base_dir=base_dir):
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if txt:
            layers.append(RulesLayer(label=label, path=path, text=txt))
    return layers


def merge_rules_markdown(layers: list[RulesLayer]) -> str:
    return "\n\n".join(layer.text for layer in layers).strip()


def load_merged_rules(*, agent_role: str, base_dir: Path) -> str:
    return merge_rules_markdown(load_rule_layers(agent_role=agent_role, base_dir=base_dir))


def validate_rule_layers(layers: list[RulesLayer]) -> list[str]:
    """
    Heuristic warnings (not errors): contradictory always/never pairs,
    unsafe phrases, empty layers.
    """
    warnings: list[str] = []
    combined_lower = "\n".join(layer.text.lower() for layer in layers)
    if re.search(r"\bnever use requests\b", combined_lower) and re.search(
        r"\b(always|must).*\brequests\b", combined_lower
    ):
        warnings.append(
            "Possible contradiction: 'never use requests' vs 'always/must ... requests'."
        )
    if re.search(r"\balways use requests\b", combined_lower) and re.search(
        r"\bnever use requests\b", combined_lower
    ):
        warnings.append("Contradiction: both 'always use requests' and 'never use requests'.")

    if re.search(r"\bnever write tests\b", combined_lower) and re.search(
        r"\b(always|must).{0,40}\btest", combined_lower
    ):
        warnings.append("Possible contradiction between mandatory testing and 'never write tests'.")

    # Pairwise layer scan: imperative vs prohibition on overlapping content words.
    must_never_pat = re.compile(r"\b(must|always|required to)\b.{0,120}", re.I)
    never_pat = re.compile(r"\b(never|do not|don't)\b.{0,120}", re.I)
    stop = {
        "must",
        "always",
        "never",
        "not",
        "do",
        "to",
        "the",
        "a",
        "an",
        "use",
        "call",
        "write",
    }
    pair_seen: set[tuple[int, int, str]] = set()
    for i, la in enumerate(layers):
        for j, lb in enumerate(layers):
            if j <= i:
                continue
            for a in la.text.splitlines()[:48]:
                for b in lb.text.splitlines()[:48]:
                    am = must_never_pat.search(a)
                    bn = never_pat.search(b)
                    if am and bn:
                        ta = re.sub(r"\W+", " ", am.group(0).lower())
                        tb = re.sub(r"\W+", " ", bn.group(0).lower())
                        toks = set(ta.split()) & set(tb.split()) - stop
                        if len(toks) >= 2:
                            key = tuple(sorted(toks))[:5]
                            sig = (i, j, str(key))
                            if sig not in pair_seen:
                                pair_seen.add(sig)
                                warnings.append(
                                    f"Possible contradiction between layers ({la.label} vs {lb.label}): "
                                    f"must/always vs never on overlapping terms {key}."
                                )
                    an = never_pat.search(a)
                    bm = must_never_pat.search(b)
                    if an and bm:
                        ta = re.sub(r"\W+", " ", an.group(0).lower())
                        tb = re.sub(r"\W+", " ", bm.group(0).lower())
                        toks = set(ta.split()) & set(tb.split()) - stop
                        if len(toks) >= 2:
                            key = tuple(sorted(toks))[:5]
                            sig = (i, j, str(key))
                            if sig not in pair_seen:
                                pair_seen.add(sig)
                                warnings.append(
                                    f"Possible contradiction between layers ({la.label} vs {lb.label}): "
                                    f"never vs must/always on overlapping terms {key}."
                                )

    never_kw = set(re.findall(r"never\s+(?:use|call|import)\s+([a-z0-9_./-]+)", combined_lower))
    must_kw = set(
        re.findall(
            r"(?:must|always|required to)\s+(?:use|call|import)\s+([a-z0-9_./-]+)", combined_lower
        )
    )
    for w in sorted(never_kw & must_kw):
        warnings.append(f"Possible contradiction: both 'never {w}' and 'must/always {w}' appear.")

    if "eval(" in combined_lower or re.search(r"\beval\s*\(", combined_lower):
        warnings.append("Rule mentions eval(...) — risky in agent-executed environments.")

    if re.search(
        r"\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{6,}['\"]",
        combined_lower,
    ):
        warnings.append(
            "Rule may embed literal secrets — prefer environment variables or secret stores."
        )

    if "chmod 777" in combined_lower:
        warnings.append("Rule mentions chmod 777 — overly permissive for typical projects.")

    if re.search(r"\b(skip|disable).{0,48}\b(ci|tests?)\b", combined_lower):
        warnings.append("Rule may suggest skipping CI or tests — review carefully.")

    unsafe = (
        (
            "ignore security",
            "Rule text mentions ignoring security — conflicts with SAGE safety posture.",
        ),
        ("disable ssl", "Rule may disable SSL verification — high risk."),
        (
            "curl \\| bash",
            "Rule suggests curl|sh style installs — often disallowed by tool policy.",
        ),
        ("rm -rf /", "Destructive rm pattern mentioned in rules."),
    )
    for needle, msg in unsafe:
        if needle in combined_lower:
            warnings.append(msg)

    return warnings
