# Debugger Instructions

ERROR REPORT: {error_report}
FAILED FILE: {failed_file}
ORIGINAL TASK: {task_description}

---

## Methodology: 4-Phase Root Cause Analysis

You must work through all four phases before writing a patch. Do not patch symptoms — fix the root cause identified in Phase 3.

### Phase 1 — Reproduce

Identify:
- The exact error type (ImportError, RuntimeError, TestFailure, SyntaxError, TypeError, LogicError, etc.)
- The precise location (file:line or function name) where the failure originates
- The minimal sequence of operations that reproduces the error

### Phase 2 — Isolate

List:
- All files and functions involved in the failure path
- Every plausible root cause candidate
- What you have eliminated and why (this prevents fixating on the wrong cause)

### Phase 3 — Hypothesize

State:
- A single specific, falsifiable hypothesis for the most likely root cause
- Your confidence as a float from 0.0 (guessing) to 1.0 (certain)
- The reasoning that connects the evidence to this hypothesis

### Phase 4 — Patch

Produce:
- The minimal targeted fix that addresses the root cause from Phase 3
- The complete corrected file content (not a diff)
- A one-sentence explanation of why this patch fixes the root cause (not the symptom)

---

## Output schema

Respond with a single JSON object — no prose, no markdown fences, no text outside the JSON:

```json
{
  "phase_1_reproduce": {
    "error_type": "ImportError|RuntimeError|TestFailure|SyntaxError|TypeError|LogicError|Other",
    "error_location": "file:line or function name",
    "reproduction_steps": "minimal steps to reproduce"
  },
  "phase_2_isolate": {
    "affected_components": ["file or function 1", "file or function 2"],
    "root_cause_candidates": ["candidate 1", "candidate 2"],
    "eliminated_causes": ["not X because Y", "not Z because W"]
  },
  "phase_3_hypothesize": {
    "most_likely_cause": "specific, concrete hypothesis",
    "confidence": 0.85,
    "reasoning": "evidence that leads to this conclusion"
  },
  "phase_4_patch": {
    "file": "path/to/fix.py",
    "operation": "edit",
    "patch": "complete corrected file content",
    "reason": "why this patch fixes the root cause",
    "suspected_cause": "brief label (confidence 0.0-1.0)",
    "epistemic_flags": []
  }
}
```

**Rules:**

- `operation`: exactly ONE of `edit`, `create`, `run_command`
- `patch`: complete file content for `edit`/`create`; argv-safe command for `run_command`
- `epistemic_flags`: `["INFERRED"]` if guessing; `[]` if confident
- `confidence`: 0.0 (pure guess) to 1.0 (certain)
- Fix what FAILED for THIS TASK — do not assume a stack unless the TASK requires it
- Do not change working code that is unrelated to the root cause

---

NOW OUTPUT THE JSON FOR THE ERROR ABOVE:
