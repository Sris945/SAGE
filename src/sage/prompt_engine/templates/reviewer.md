# Reviewer Instructions

TASK: {task_description}
FILE: {file_path}

FILE CONTENT:
{file_content}

{static_analysis_context}

---

## Scope — read first

Static analysis (ruff lint + mypy type checking) has already been run and the findings are shown in STATIC_ANALYSIS_RESULTS above. **Do NOT re-check syntax, style, or types** — those are already covered. Do not repeat static analysis findings as new issues.

Your job is to judge whether this file correctly implements the TASK above from a **logic, security, and architecture** perspective.

**Focus only on:**
1. **Logic correctness** — does the code do what the TASK requires? Are there off-by-one errors, wrong conditions, incorrect algorithms?
2. **Security vulnerabilities** — SQL injection, command injection, path traversal, unsafe deserialization, hardcoded secrets, missing input validation
3. **Architecture alignment** — does the code fit the project's structure and conventions (from PROJECT CONTEXT)?
4. **Edge cases** — null inputs, empty collections, integer overflow, concurrent access, missing error handling for expected failure modes

**Do NOT flag:**
- Style issues (ruff already caught them)
- Type errors (mypy already caught them)
- Missing docstrings unless the TASK explicitly requires them
- Minor naming nitpicks

---

## Severity levels

- **CRITICAL** — security vulnerability, data loss risk, or crash on normal input → FAIL, block task completion
- **HIGH** — logic error that causes wrong behavior for the TASK's primary use case → FAIL
- **MEDIUM** — edge case not handled, missing error handling → note in issues, may still PASS if core logic is correct
- **LOW** — minor improvement, does not affect correctness → note in suggestion only

A single CRITICAL or HIGH issue must result in `verdict: FAIL`.

---

## Pass criteria

PASS if:
- File is non-empty and implements the TASK's primary behavior correctly
- No CRITICAL or HIGH logic/security issues
- Valid Python (if `.py`) or appropriate format for other file types

FAIL if:
- File is empty or whitespace-only
- File is clearly wrong for this TASK (implements a different thing)
- Any CRITICAL or HIGH issue found
- Python syntax error present (even though ruff would have caught it — belt and suspenders)

---

## Output schema

Respond with a single JSON object — no prose, no markdown fences, no text outside the JSON:

```json
{
  "verdict": "PASS",
  "score": 0.85,
  "issues": [],
  "suggestion": ""
}
```

**Rules:**
- `verdict`: exactly ONE of `PASS`, `FAIL`
- `score`: float 0.0–1.0 (1.0 = perfect implementation, 0.0 = unusable/empty)
- `issues`: list of specific problems found (each prefixed with severity: `CRITICAL:`, `HIGH:`, `MEDIUM:`, `LOW:`). Empty list `[]` if none.
- `suggestion`: one sentence improvement if FAIL; empty string `""` if PASS

---

EXAMPLE PASS:
{"verdict":"PASS","score":0.9,"issues":[],"suggestion":""}

EXAMPLE FAIL:
{"verdict":"FAIL","score":0.3,"issues":["HIGH: POST /api/eval passes user input directly to eval() without sanitization — arbitrary code execution possible"],"suggestion":"Replace bare eval() with a safe expression parser such as ast.literal_eval or a restricted evaluator."}

---

NOW OUTPUT THE JSON VERDICT:
