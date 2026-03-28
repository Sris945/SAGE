"""``sage rules`` — inspect merged USER_RULES and run heuristics (spec §18)."""

from __future__ import annotations

import os
import re
import string
from argparse import Namespace
from pathlib import Path
from typing import Any

from sage.cli.exit_codes import EX_USAGE


def _normalize_rule(rule: str) -> str:
    """Lowercase, strip punctuation, deduplicate whitespace."""
    rule = rule.lower()
    rule = rule.translate(str.maketrans("", "", string.punctuation))
    rule = re.sub(r"\s+", " ", rule).strip()
    return rule


def _word_overlap_ratio(a: str, b: str) -> float:
    """Ratio of shared words to union of words (Jaccard similarity)."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _detect_conflicts(rules: list[str]) -> list[str]:
    """
    Detect contradictory or problematic rules.
    Returns list of human-readable conflict descriptions.
    """
    conflicts: list[str] = []
    normalized = [_normalize_rule(r) for r in rules]

    # 1. Always/Never contradictions
    always_pat = re.compile(r"always\s+(\w+(?:\s+\w+){0,2})")
    never_pat = re.compile(r"never\s+(\w+(?:\s+\w+){0,2})")

    always_phrases: list[tuple[int, str]] = []
    never_phrases: list[tuple[int, str]] = []
    for idx, norm in enumerate(normalized):
        for m in always_pat.finditer(norm):
            always_phrases.append((idx + 1, m.group(1).strip()))
        for m in never_pat.finditer(norm):
            never_phrases.append((idx + 1, m.group(1).strip()))

    for a_idx, a_phrase in always_phrases:
        for n_idx, n_phrase in never_phrases:
            a_words = set(a_phrase.split())
            n_words = set(n_phrase.split())
            overlap = a_words & n_words
            if overlap:
                conflicts.append(
                    f"CONFLICT: Rule {a_idx} says 'always {a_phrase}' but "
                    f"Rule {n_idx} says 'never {n_phrase}'"
                )

    # 2. Numeric impossible constraints (same keyword, incompatible values).
    # Run on original rules (not normalized) so punctuation like ':' is preserved.
    numeric_pat = re.compile(r"(\w+)\s*[:<>=]+\s*(\d+)")
    keyword_values: dict[str, list[tuple[int, int]]] = {}
    for idx, norm in enumerate(rules):
        for m in numeric_pat.finditer(norm):
            kw = m.group(1)
            val = int(m.group(2))
            keyword_values.setdefault(kw, []).append((idx + 1, val))

    checked_pairs: set[tuple[int, int]] = set()
    for kw, entries in keyword_values.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                idx_a, val_a = entries[i]
                idx_b, val_b = entries[j]
                pair = (min(idx_a, idx_b), max(idx_a, idx_b))
                if pair in checked_pairs:
                    continue
                if val_a != val_b:
                    checked_pairs.add(pair)
                    conflicts.append(
                        f"CONFLICT: Rule {idx_a} and Rule {idx_b} have incompatible "
                        f"numeric values for '{kw}': {val_a} vs {val_b}"
                    )

    # 3. Duplicate rules (>90% word-overlap after normalization)
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            ratio = _word_overlap_ratio(normalized[i], normalized[j])
            if ratio > 0.90:
                conflicts.append(
                    f"CONFLICT: Rule {i + 1} and Rule {j + 1} are near-identical "
                    f"(overlap={ratio:.0%}): '{rules[i][:80]}'"
                )

    # 4. Negation pairs: "do X" / "use X" vs "do not X" / "do not use X"
    do_pat = re.compile(r"\bdo\s+(?!not\b)(\w+(?:\s+\w+){0,2})")
    do_not_pat = re.compile(r"\bdo\s+not\s+(\w+(?:\s+\w+){0,2})")
    use_pat = re.compile(r"\buse\s+(?!not\b)(\w+(?:\s+\w+){0,2})")
    do_not_use_pat = re.compile(r"\bdo\s+not\s+use\s+(\w+(?:\s+\w+){0,2})")

    do_phrases: list[tuple[int, str]] = []
    do_not_phrases: list[tuple[int, str]] = []
    use_phrases: list[tuple[int, str]] = []
    do_not_use_phrases: list[tuple[int, str]] = []

    for idx, norm in enumerate(normalized):
        for m in do_pat.finditer(norm):
            do_phrases.append((idx + 1, m.group(1).strip()))
        for m in do_not_pat.finditer(norm):
            do_not_phrases.append((idx + 1, m.group(1).strip()))
        for m in use_pat.finditer(norm):
            use_phrases.append((idx + 1, m.group(1).strip()))
        for m in do_not_use_pat.finditer(norm):
            do_not_use_phrases.append((idx + 1, m.group(1).strip()))

    for d_idx, d_phrase in do_phrases:
        for dn_idx, dn_phrase in do_not_phrases:
            d_words = set(d_phrase.split())
            dn_words = set(dn_phrase.split())
            if d_words & dn_words:
                conflicts.append(
                    f"CONFLICT: Rule {d_idx} says 'do {d_phrase}' but "
                    f"Rule {dn_idx} says 'do not {dn_phrase}'"
                )

    for u_idx, u_phrase in use_phrases:
        for dnu_idx, dnu_phrase in do_not_use_phrases:
            u_words = set(u_phrase.split())
            dnu_words = set(dnu_phrase.split())
            if u_words & dnu_words:
                conflicts.append(
                    f"CONFLICT: Rule {u_idx} says 'use {u_phrase}' but "
                    f"Rule {dnu_idx} says 'do not use {dnu_phrase}'"
                )

    return conflicts


def cmd_rules(args: Namespace) -> None:
    from sage.prompt_engine.rules_manager import (
        discover_rule_paths,
        load_rule_layers,
        merge_rules_markdown,
        validate_rule_layers,
    )

    base = Path(args.path or ".").resolve()
    if args.repo:
        base = Path(args.repo).expanduser().resolve()
    os.chdir(base)
    os.environ["SAGE_WORKSPACE_ROOT"] = str(base)

    agent = (args.agent or "coder").strip().lower()

    if args.rules_command == "add":
        use_global = bool(getattr(args, "global_rules", False))
        target = (
            (Path.home() / ".sage" / "rules.md") if use_global else (base / ".sage" / "rules.md")
        )
        bits = getattr(args, "rule_text", None) or []
        line = " ".join(str(x) for x in bits).strip()
        if not line:
            print("[SAGE rules] add: empty text.")
            raise SystemExit(EX_USAGE)
        target.parent.mkdir(parents=True, exist_ok=True)
        prefix = "\n" if target.exists() and target.stat().st_size > 0 else ""
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write(prefix + line + "\n")
        except OSError as e:
            print(f"[SAGE rules] add: could not write {target}: {e}")
            raise SystemExit(EX_USAGE)
        print(f"[SAGE rules] Appended to {target.resolve()}")
        return

    if args.rules_command == "validate":
        layers = load_rule_layers(agent_role=agent, base_dir=base)
        heuristic_warnings = validate_rule_layers(layers)

        # Extract individual rules from all layers for conflict detection
        all_rules: list[str] = []
        for layer in layers:
            for line in layer.text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    all_rules.append(line)

        conflict_issues = _detect_conflicts(all_rules)

        all_issues = heuristic_warnings + conflict_issues

        if not all_issues:
            print("[SAGE rules] validate: no heuristic issues detected.")
            return

        # Rich formatting if available, plain text fallback
        try:
            from rich.console import Console

            console = Console()
            console.print(
                "[bold yellow][SAGE rules] validate: issues found (review recommended):[/bold yellow]"
            )
            for issue in all_issues:
                if issue.startswith("CONFLICT:"):
                    console.print(f"  [red]- {issue}[/red]")
                else:
                    console.print(f"  [yellow]- {issue}[/yellow]")
        except ImportError:
            print("[SAGE rules] validate: issues found (review recommended):")
            for issue in all_issues:
                print(f"  - {issue}")

        if getattr(args, "strict", False):
            raise SystemExit(EX_USAGE)
        return

    # default: show
    paths = discover_rule_paths(agent_role=agent, base_dir=base)
    if args.layers:
        print(f"[SAGE rules] agent_role={agent}  base_dir={base}")
        if not paths:
            print("  (no rule files found)")
            return
        for label, p in paths:
            print(f"  - {label}: {p}")
        print()
    merged = merge_rules_markdown(load_rule_layers(agent_role=agent, base_dir=base))
    if not merged:
        print("[SAGE rules] (empty — no rule files matched)")
        return
    print(merged)


def register_rules_parser(sub: Any) -> None:
    rules_p = sub.add_parser(
        "rules",
        help="Show merged USER_RULES or validate rule files (spec §18)",
    )
    rules_sub = rules_p.add_subparsers(dest="rules_command", required=False)
    add = rules_sub.add_parser(
        "add",
        help="Append a rule line to .sage/rules.md (or ~/.sage/rules.md with --global)",
    )
    add.add_argument(
        "rule_text",
        nargs="+",
        help="Rule sentence(s) to append",
    )
    add.add_argument(
        "--global",
        dest="global_rules",
        action="store_true",
        help="Append to ~/.sage/rules.md instead of project .sage/rules.md",
    )
    val = rules_sub.add_parser(
        "validate",
        help="Heuristic check for unsafe or contradictory rule phrases",
    )
    val.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any warning",
    )
    rules_p.add_argument(
        "--agent",
        default="coder",
        help="Agent role for .sage/rules.{agent}.md (default: coder)",
    )
    rules_p.add_argument(
        "--path",
        default=".",
        help="Project root for resolving .sage/ (default: cwd)",
    )
    rules_p.add_argument(
        "--repo",
        default="",
        help="Same as sage run --repo: chdir before resolving rules",
    )
    rules_p.add_argument(
        "--layers",
        action="store_true",
        help="List contributing file paths before merged markdown",
    )
