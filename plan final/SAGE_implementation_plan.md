# SAGE
## Self-improving Autonomous Generation Engine
### Implementation Plan — v1.0
#### Status: Active — Phases 1–4 implemented; polish + Phase 5+ per roadmap

---

> **Tagline:** *prompt → production*
>
> SAGE converts a natural language goal into a tested, documented software repository
> through coordinated AI agents — running locally by default, with optional cloud fallback.
> It is the first open-source agent system with two compounding self-improvement loops:
> prompt intelligence and fix pattern memory.

---

## Table of Contents

1. [Project Vision](#1-project-vision)
2. [What Makes SAGE Different](#2-what-makes-sage-different)
3. [Prompt Intelligence Middleware](#3-prompt-intelligence-middleware)
4. [Design Philosophy](#4-design-philosophy)
5. [High-Level Architecture](#5-high-level-architecture)
6. [Model Router](#6-model-router)
7. [Task Graph Engine](#7-task-graph-engine)
8. [Task Scheduler](#8-task-scheduler)
9. [Agent Orchestrator — LangGraph State Machine](#9-agent-orchestrator--langgraph-state-machine)
10. [Event Bus](#10-event-bus)
11. [Inter-Agent Communication Protocol](#11-inter-agent-communication-protocol)
12. [Agent Roster](#12-agent-roster)
13. [Tool Execution Engine + Safety Limits](#13-tool-execution-engine--safety-limits)
14. [Memory System — 5-Layer Architecture](#14-memory-system--5-layer-architecture)
15. [Debug Loop + Circuit Breaker](#15-debug-loop--circuit-breaker)
16. [Human-in-the-Loop Checkpoints](#16-human-in-the-loop-checkpoints)
17. [Session Continuity + Handoff Protocol](#17-session-continuity--handoff-protocol)
18. [User Rules Layer](#18-user-rules-layer)
19. [Reinforcement Learning Strategy](#19-reinforcement-learning-strategy--3-tier-routing)
20. [System Execution Flow](#20-system-execution-flow)
21. [Observability System](#21-observability-system)
22. [Benchmark System](#22-benchmark-system)
23. [Technology Stack](#23-technology-stack)
24. [Repository Structure](#24-repository-structure)
25. [Development Roadmap](#25-development-roadmap)
26. [Minimum Viable System](#26-minimum-viable-system)
27. [Self-Improvement Loops](#27-self-improvement-loops)
28. [Open Source Strategy](#28-open-source-strategy)
29. [Long-Term Vision](#29-long-term-vision)

---

## 1. Project Vision

SAGE behaves like a **software engineering team composed of AI agents**. Give it an idea.
It plans, codes, executes, debugs, and delivers a working repository — without you writing
a single line.

```
User Idea
    ↓
Prompt Intelligence
    ↓
Planning
    ↓
Coding
    ↓
Execution
    ↓
Debugging
    ↓
Tested Repository
```

**Example**

Input:
```
sage run "Build a FastAPI backend with authentication and PostgreSQL"
```

Output:
```
backend/
  main.py
  auth.py
  database.py
requirements.txt
Dockerfile
README.md
tests/
  test_auth.py
  test_api.py
.sage-memory.md          ← auto-generated project memory
memory/system_state.json ← persistent session state
```

SAGE picks up exactly where it left off every session. It knows what it built,
what failed, what it fixed, and what comes next — without being told.

---

## 2. What Makes SAGE Different

Every other open-source agent system fails on at least one of these.
SAGE is designed to pass all five.

| Property | Most agent systems | SAGE |
|----------|--------------------|------|
| Prompt quality | Raw user input → LLM | Every call optimised by middleware |
| Memory | Starts from zero each session | 5-layer persistent memory |
| Inter-agent communication | Free-form text | Strict JSON protocol |
| Failure handling | Loops forever or crashes | Circuit breaker + fix pattern store |
| Self-improvement | Static | Two compounding improvement loops |

The two self-improvement loops are what make SAGE research-grade:

- **Prompt learning loop** — successful prompts rank higher in future retrieval
- **Fix pattern loop** — known errors are resolved instantly, skipping the debug agent entirely

Both loops are measurable. Both are publishable.

---

## 3. Prompt Intelligence Middleware

The most architecturally novel component of SAGE.

Every LLM call — from every agent — passes through this layer without exception.
It transforms raw, under-specified inputs into precision-engineered, model-specific prompts
before they reach any model.

### Pipeline

```
Raw Input (from user or any agent)
        ↓
  Prompt Intelligence Middleware
    ├─ 1. Semantic search → knowledge base
    ├─ 2. Agent-role template injection
    ├─ 3. Recency-weighted successful prompt retrieval
    └─ 4. Keyword fallback
        ↓
  Enhanced Prompt
        ↓
  Model Router
        ↓
  Agent / LLM
```

### Knowledge Base (RAG Sources)

- Anthropic Claude prompting documentation
- OpenAI prompting guide
- Google Gemini documentation
- Prompt engineering research papers (academic + DeepMind)
- Internal agent performance logs (ranked by output quality score)
- Agent-role-specific prompt templates

### Retrieval Strategy

| Priority | Method |
|----------|--------|
| 1 | Semantic similarity against knowledge base |
| 2 | Recency-weighted: recently successful prompts rank higher |
| 3 | Agent-role template injection (planner ≠ coder ≠ debugger) |
| 4 | Keyword fallback |

### Universal Prompt Template

Every agent receives its prompt in this exact format. No exceptions, no free-form strings.

```
SYSTEM:
You are the SAGE {agent_role} agent.
Your output must be valid JSON matching the {output_schema} schema.
Never explain your reasoning in prose. Return structured output only.

TASK:
{task_description}

PROJECT CONTEXT:
{project_memory_summary}

RECENT SESSION STATE:
{system_state_summary}

TOOL PERMISSIONS:
{allowed_tools_for_this_task}

KNOWN PATTERNS:
{relevant_fix_patterns_if_applicable}

EPISTEMIC RULES:
- Tag inferred decisions with [INFERRED]
- Tag untested outputs with [UNVERIFIED]
- Tag ambiguous inputs with [UNCLEAR] and surface them in your output

OUTPUT FORMAT:
{output_schema_example}
```

### Agent-Specific Templates

Each template is a markdown file automatically injected by the middleware —
no explicit invocation required. The template fires when the agent role matches.

```
prompt_engine/templates/
  planner.md            ← structured task decomposition, delta DAG mode
                           tasks broken into 2–5 min chunks with exact file
                           paths and verification steps — no vague task cards
  architect.md          ← folder structure + tech decisions
  coder.md              ← PatchRequest output, matches existing conventions
                           enforces TDD: write failing test first, then minimal
                           code — any code written before a test is deleted
  debugger.md           ← error analysis, suspected_cause required
                           4-phase root cause process before any patching
  reviewer.md           ← security + logic checks
                           reports issues by severity, blocks on critical
  memory_optimizer.md   ← compression rules, no hallucination
```

### Brainstorming Checkpoint

Before the Planner generates a Task DAG, SAGE runs a lightweight spec-refinement
loop. The Planner asks targeted clarification questions, shows the spec in short
sections for validation, then generates the DAG only after the user signs off.
This eliminates wasted work on misunderstood requirements and maps directly to
Human Checkpoint 1.

---

## 4. Design Philosophy

| Priority | Principle |
|----------|-----------|
| 1 | **Deterministic workflows** — no chaotic autonomous loops |
| 2 | **Structured communication** — strict JSON between all agents |
| 3 | **Observability** — every decision, action, and failure is logged |
| 4 | **Reproducibility** — same prompt produces same result |
| 5 | **Tool-first agents** — agents request actions, never execute directly |
| 6 | **Self-improving memory** — system learns measurably from its failures |
| 7 | **Safety by default** — all execution is bounded and sandboxed |
| 8 | **Context-aware** — works on existing codebases, not just blank slates |

Architecture style:
```
Goal-Driven Planning
+ Task Graph Execution
+ Event-Driven Recovery
+ Persistent Session Memory
+ Compounding Self-Improvement
```

---

## 5. High-Level Architecture

```
User Prompt
      ↓
sage-context.sh ─────────────────────── load system_state + git context
      ↓
Prompt Intelligence Middleware ──────── wraps every LLM call
      ↓
Model Router ────────────────────────── correct model per task type
      ↓
Planner Agent ───────────────────────── produces Task DAG
      ↓
Human Checkpoint ────────────────────── approve / edit / reject
      ↓
Task Scheduler ──────────────────────── MAX_PARALLEL = 3, dep resolution
      ↓
Agent Orchestrator (LangGraph) ──────── state machine
      ↓            ↕
Memory Manager   Async Event Bus
      ↓
Parallel Agent Workers ──────────────── Coder / Architect / Reviewer
      ↓
Tool Execution Engine ───────────────── sandboxed + safety limits
      ↓
Fix Pattern Store check ─────────────── skip debug if pattern known
      ↓ (no match)
Debug Loop ──────────────────────────── patch → retry
      ↓ (max retries)
Circuit Breaker ─────────────────────── escalate / skip / halt
      ↓
SESSION_END ─────────────────────────── update memory + git hook
      ↓
Output Repository + Benchmark Log
```

---

## 6. Model Router

SAGE never lets agents randomly select models. Every task type has a designated model
with an explicit fallback chain and trigger conditions.

### Routing Table

| Agent | Primary (Local) | Fallback (Cloud) | Reason |
|-------|----------------|-----------------|--------|
| Planner | Llama 3 | Claude | Reasoning-heavy, instruction following |
| Architect | Llama 3 | Claude | Design decisions, structured output |
| Coder | DeepSeek-Coder | GPT-4o | Code generation specialist |
| Debugger | Codestral | GPT-4o | Code repair specialist |
| Reviewer | DeepSeek-Coder | Claude | Code analysis |
| Test Engineer | DeepSeek-Coder | GPT-4o | Test generation |
| Memory Optimizer | Llama 3 | Claude | Compression + summarisation |
| Documentation | Llama 3 | Claude | Natural language generation |

### Routing Config (`config/models.yaml`)

```yaml
routing:
  planner:
    primary: "llama3:8b"
    fallback: "claude-sonnet-4-5"
    fallback_triggers:
      - task_complexity_score > 0.8
      - primary_failure_count >= 2
  coder:
    primary: "deepseek-coder:6.7b"
    fallback: "gpt-4o"
    fallback_triggers:
      - language not in ["python", "javascript", "typescript"]
      - primary_failure_count >= 2
  debugger:
    primary: "codestral:22b"   # must match `ollama list` (e.g. :22b vs :latest)
    fallback: "gpt-4o"
    fallback_triggers:
      - primary_failure_count >= 2
```

---

## 7. Task Graph Engine

All work in SAGE is modelled as a DAG. No agent acts outside the graph.
This single rule prevents 90% of multi-agent chaos.

### Example DAG

```
setup_project
      ↓
create_backend
      ↓
connect_database
      ↓
implement_auth
      ↓
add_tests
```

### TaskNode Schema

```json
{
  "id": "string",
  "description": "string",
  "dependencies": ["task_id"],
  "assigned_agent": "coder | architect | reviewer",
  "status": "pending | running | blocked | failed | completed",
  "retry_count": 0,
  "model_used": "deepseek-coder:6.7b",
  "epistemic_flags": ["[INFERRED]", "[UNCLEAR]", "[UNVERIFIED]"]
}
```

### Epistemic Flags

Agents self-flag their own uncertainty. Every flag is logged and surfaced in observability.

| Flag | Meaning |
|------|---------|
| `[INFERRED]` | Agent assumed something not explicitly specified |
| `[UNVERIFIED]` | Output produced but not yet tested |
| `[UNCLEAR]` | Input was ambiguous — human review recommended |

---

## 8. Task Scheduler

Controls execution order and enforces parallelism limits.
Without this, all tasks start simultaneously and the system collapses.

### Algorithm

```python
class TaskScheduler:
    MAX_PARALLEL = 3       # never exceed this
    MAX_QUEUE_SIZE = 10    # prevents runaway task explosion

    def get_ready_tasks(self, dag: TaskGraph) -> list[TaskNode]:
        """Return tasks whose dependencies are all completed."""
        return [
            task for task in dag.nodes
            if task.status == "pending"
            and all(dag.get(dep).status == "completed"
                    for dep in task.dependencies)
        ]

    def schedule_next(self, dag, running) -> list[TaskNode]:
        """Schedule up to MAX_PARALLEL tasks."""
        slots = self.MAX_PARALLEL - len(running)
        return self.get_ready_tasks(dag)[:slots]
```

### Parallelism Rules

| Scenario | Behaviour |
|----------|-----------|
| Independent tasks | Run in parallel, up to MAX_PARALLEL=3 |
| Dependent tasks | Wait for upstream completion |
| Failed dependency | Downstream tasks → BLOCKED (not FAILED) |
| All tasks blocked | Emit `PIPELINE_BLOCKED` → human checkpoint |

Blocking downstream tasks (not failing them) is critical — it means one broken
task doesn't cascade into a full pipeline crash.

---

## 9. Agent Orchestrator — LangGraph State Machine

The central nervous system. Coordinates all agents, manages state, routes events.

### State Object

```python
class SAGEState(TypedDict):
    user_prompt: str
    enhanced_prompt: str        # after middleware
    task_dag: dict
    current_task: TaskNode
    agent_output: dict
    execution_result: dict
    debug_attempts: int
    session_memory: dict
    events: list[Event]
```

### Graph Definition

```python
workflow = StateGraph(SAGEState)

# Nodes
workflow.add_node("load_memory",         load_session_memory)
workflow.add_node("prompt_middleware",   run_prompt_intelligence)
workflow.add_node("route_model",         run_model_router)
workflow.add_node("planner",             run_planner_agent)
workflow.add_node("human_checkpoint",    run_human_checkpoint)
workflow.add_node("scheduler",           run_task_scheduler)
workflow.add_node("execute_agent",       run_assigned_agent)
workflow.add_node("tool_executor",       run_tool_execution)
workflow.add_node("check_fix_patterns",  check_fix_pattern_store)
workflow.add_node("debug_agent",         run_debug_agent)
workflow.add_node("circuit_breaker",     run_circuit_breaker)
workflow.add_node("save_memory",         save_session_state)

# Linear edges
workflow.set_entry_point("load_memory")
workflow.add_edge("load_memory",       "prompt_middleware")
workflow.add_edge("prompt_middleware", "route_model")
workflow.add_edge("route_model",       "planner")
workflow.add_edge("planner",           "human_checkpoint")
workflow.add_edge("human_checkpoint",  "scheduler")
workflow.add_edge("scheduler",         "execute_agent")
workflow.add_edge("execute_agent",     "tool_executor")

# Conditional edges (decision points)
workflow.add_conditional_edges(
    "tool_executor",
    decide_after_execution,
    {
        "success":      "scheduler",            # advance to next task
        "test_failed":  "check_fix_patterns",
        "build_error":  "check_fix_patterns",
        "all_done":     "save_memory",
    }
)

workflow.add_conditional_edges(
    "check_fix_patterns",
    decide_after_pattern_check,
    {
        "pattern_found": "tool_executor",       # apply known fix, re-execute
        "no_pattern":    "debug_agent",
    }
)

workflow.add_conditional_edges(
    "debug_agent",
    decide_after_debug,
    {
        "patched":      "tool_executor",        # retry
        "max_retries":  "circuit_breaker",
    }
)

workflow.add_conditional_edges(
    "circuit_breaker",
    decide_after_circuit_break,
    {
        "skip":      "scheduler",
        "escalate":  "human_checkpoint",
        "halt":      "save_memory",
    }
)
```

---

## 10. Event Bus

All orchestration is event-driven. No agent polls. Everything reacts to events.

### Implementation (MVP — async queue, zero infrastructure)

```python
# orchestrator/event_bus.py
import asyncio
from dataclasses import dataclass
from typing import Callable

@dataclass
class Event:
    type: str
    task_id: str
    payload: dict
    timestamp: str

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}
        self._queue = asyncio.Queue()

    def subscribe(self, event_type: str, handler: Callable):
        self._handlers.setdefault(event_type, []).append(handler)

    async def emit(self, event: Event):
        await self._queue.put(event)

    async def process(self):
        while True:
            event = await self._queue.get()
            for handler in self._handlers.get(event.type, []):
                await handler(event)
```

Upgrade path: Python async queue → Redis pub/sub when SAGE runs distributed.

### Event Registry

| Event | Emitted By | Handled By | Action |
|-------|-----------|-----------|--------|
| `TASK_COMPLETED` | Executor | Scheduler | Advance DAG |
| `TASK_FAILED` | Circuit Breaker | Orchestrator | Escalate / skip |
| `TEST_FAILED` | Executor | Debug Agent | Start debug loop |
| `BUILD_ERROR` | Executor | Debug Agent | Start debug loop |
| `PATCH_APPLIED` | Tool Engine | Executor | Re-run tests |
| `PIPELINE_BLOCKED` | Scheduler | Orchestrator | Human checkpoint |
| `MEMORY_CHECKPOINT` | Orchestrator | Memory Manager | Write session log |
| `SESSION_END` | Orchestrator | Memory Manager | Update system_state.json |
| `PATTERN_LEARNED` | Debug Agent | Fix Pattern Store | Write new pattern |
| `CIRCUIT_BREAKER_FIRED` | Debug Loop | Orchestrator | Escalate / skip / halt |
| `ORCHESTRATOR_INTERVENTION` | Intel Feed | Orchestrator | Reassign / checkpoint |
| `AGENT_INSIGHT` | Any Agent | Intel Feed | Ingest + evaluate |
| `SESSION_INTERRUPTED` | Any unclean exit | SessionManager | Write handoff.json |
| `SESSION_RESUMED` | Startup (handoff detected) | SessionManager | Load full context |
| `HANDOFF_CLEARED` | Clean SESSION_END | SessionManager | Delete handoff.json |

---

## 11. Inter-Agent Communication Protocol

All agents communicate through a strict JSON protocol. No free-form text between agents.
This is the single rule that prevents hallucinated formats from breaking the pipeline.

### TaskResult

```json
{
  "task_id": "string",
  "status": "completed | failed",
  "summary": "string",
  "artifacts": ["file paths"],
  "epistemic_flags": ["[INFERRED]", "[UNVERIFIED]"],
  "model_used": "deepseek-coder:6.7b",
  "tokens_used": 1240,
  "logs": "optional stdout/stderr"
}
```

### PatchRequest

```json
{
  "file": "path/to/file",
  "operation": "edit | create | delete",
  "patch": "unified diff or full content",
  "reason": "why this change is necessary",
  "epistemic_flags": ["[INFERRED]"]
}
```

### ErrorReport

```json
{
  "task_id": "string",
  "error_type": "runtime | test | dependency | logic",
  "logs": "full stack trace",
  "suspected_cause": "agent analysis",
  "suggested_fix": "optional patch direction",
  "pattern_match": "error_signature if known fix exists"
}
```

### AgentInsight

Emitted continuously by every agent during execution.
Received and evaluated by the Orchestrator Intelligence Feed.

```json
{
  "agent": "coder | planner | architect | debugger | reviewer",
  "task_id": "string",
  "insight_type": "uncertainty | risk | decision | observation",
  "content": "JWT secret key is hardcoded in main.py — flagging before commit",
  "severity": "low | medium | high",
  "epistemic_flag": "[INFERRED] | [UNCLEAR] | [UNVERIFIED]",
  "timestamp": "2026-03-16T14:22:00Z",
  "requires_orchestrator_action": false
}
```

---

## 12. Agent Roster

### MVP Agents (build first)

| Agent | Input | Output Schema | Primary Model |
|-------|-------|--------------|---------------|
| Planner | User prompt | Task DAG + project spec | Llama 3 |
| Architect | Task DAG | Folder structure + tech decisions | Llama 3 |
| Coder | TaskNode | PatchRequest | DeepSeek-Coder |
| Executor | PatchRequest | ExecutionResult | — (tool call) |
| Debugger | ErrorReport | PatchRequest | Codestral |

### Phase 2 Agents

| Agent | Role | Adds |
|-------|------|------|
| Reviewer | Code quality + security (ruff, bandit, mypy) | Research-grade output |
| Test Engineer | Generate pytest + integration tests | Benchmark coverage |
| Memory Optimizer | Weekly compression + pattern promotion | Self-improving memory |
| Documentation | README + API docs | Open source readiness |

---

## 13. Tool Execution Engine + Safety Limits

All agent actions route through this engine. Nothing touches the host system directly.

### Safety Config (`config/pipeline.yaml`)

```yaml
safety:
  max_command_time_seconds: 30       # kill any command running > 30s
  max_file_write_bytes: 5242880      # 5MB max per write
  max_patch_lines: 200               # reject oversized patches
  max_pip_install_packages: 10       # prevent dependency explosion
  blocked_commands:
    - "rm -rf /"
    - "sudo"
    - "curl | bash"
    - "wget | sh"
  max_concurrent_processes: 3        # matches MAX_PARALLEL
  docker_memory_limit: "512m"
  docker_cpu_limit: "1.0"
```

### Execution Handler

```python
class ToolExecutionEngine:
    def execute(self, req: PatchRequest) -> ExecutionResult:
        self._safety_check(req)                          # validate limits first

        if req.operation in ["edit", "create", "delete"]:
            return self._filesystem_handler(req)

        elif req.operation == "run_command":
            return self._terminal_handler(req)           # sandboxed

    def _terminal_handler(self, req):
        result = subprocess.run(
            req.command,
            timeout=self.safety.max_command_time_seconds,
            capture_output=True,
            shell=False,                                  # never shell=True
        )
        return ExecutionResult(stdout=result.stdout, returncode=result.returncode)
```

### Supported Operations

| Category | Operations | Isolation |
|----------|-----------|-----------|
| Filesystem | read, write, patch, delete | subprocess |
| Terminal | install, run, build, test | Docker |
| Git | init, commit, branch, diff | subprocess |
| Runtime | pytest, npm test, docker build | Docker |
| Memory | read/write state, append logs | direct |

---

## 14. Memory System — 5-Layer Architecture

The memory system is what separates SAGE from every agent system that starts from zero.

```
memory/
  system_state.json         ← Layer 1: Active brain (read every session)
  sessions/
    2026-03-16.log          ← Layer 2: Append-only execution journals
  projects/
    project-name.md         ← Layer 3: Scoped project context
  fixes/
    error_patterns.json     ← Layer 4: Self-learned fix patterns
  weekly/
    2026-W11.md             ← Layer 5: Compressed weekly digests
.sage-memory.md             ← Per-repo: auto-updated by git hook
.sage/                      ← Per-repo: codebase intelligence cache
```

### 5 Lifecycle Hooks

The event bus is driven by 5 hooks that fire automatically — no agent
needs to explicitly call memory:

| Hook | Fires When | SAGE Action |
|------|------------|-------------|
| `SessionStart` | `sage run` begins | Load `system_state.json` + check for `handoff.json` |
| `UserPromptSubmit` | User prompt enters pipeline | Inject project memory + fix patterns into prompt |
| `PostToolUse` | Any tool execution completes | Log result to session journal |
| `Stop` | Agent task ends (success or fail) | Write `MEMORY_CHECKPOINT` if 5th completed task |
| `SessionEnd` | Pipeline finishes or is interrupted | Update `system_state.json`, clear or write handoff |

```json
{
  "last_updated": "2026-03-16T14:30:00Z",
  "active_project": "fastapi-auth-backend",
  "last_completed_task": "connect_database",
  "next_unblocked_task": "implement_auth",
  "open_blockers": ["PostgreSQL connection string not set"],
  "session_count": 4,
  "overall_success_rate": 0.78,
  "fix_pattern_hit_rate": 0.34
}
```

---

### Layer 2 — Session Journals

Append-only execution logs. Written by `MEMORY_CHECKPOINT` event every 5 completed tasks.

```
[2026-03-16 14:22] CHECKPOINT
  Completed: setup_project, create_backend
  In progress: connect_database
  Last file: backend/database.py
  Last command: pip install sqlalchemy
  Model: deepseek-coder:6.7b
  Flags: [UNVERIFIED] database connection not tested yet
```

These logs are the backbone of the observability system and the source material
for the Memory Optimizer Agent.

---

### Layer 3 — Project Memory

Scoped per project. Stores architecture decisions, file structure, and known issues.

```markdown
## Architecture Decisions
- Framework: FastAPI
- Database: PostgreSQL via SQLAlchemy
- Auth: JWT tokens (python-jose)

## File Structure
backend/
  main.py      ← entry point, FastAPI app
  auth.py      ← JWT logic
  database.py  ← SQLAlchemy models + connection

## Known Issues
- Connection pooling not yet configured
- No rate limiting on auth endpoints
```

---

### Layer 4 — Self-Learned Fix Patterns (Novel)

The most novel memory component. When the debug agent successfully fixes an error,
it writes the pattern. Future identical errors are resolved instantly — the debug loop
is skipped entirely.

```json
{
  "error_signature": "ModuleNotFoundError: No module named 'sqlalchemy'",
  "fix": "pip install sqlalchemy psycopg2-binary",
  "success_rate": 0.95,
  "times_applied": 7,
  "last_used": "2026-03-15",
  "source": "debug_agent | human"
}
```

**Matching strategy:** Exact signature match first → semantic similarity fallback.
**Result:** System gets measurably faster and more reliable with every run.

---

### Layer 5 — Weekly Digest

The Memory Optimizer Agent runs weekly (cron). It:
1. Reads all session logs from the past 7 days
2. Updates `system_state.json`
3. Promotes patterns with `success_rate > 0.8` to permanent store
4. Removes stale entries untouched for 14+ days
5. Writes compressed weekly digest
6. Ensures `system_state.json` stays under 200 lines

---

### Git Hook — Automatic Commit Memory

`.git/hooks/post-commit`
```bash
#!/bin/bash
echo "$(date '+%Y-%m-%d %H:%M') | $(git log -1 --oneline)" >> .sage-memory.md
```

Zero effort. Every commit is permanently recorded for agent context.

---

### Context Injection Script

`sage-context.sh` — runs before every session, injects full project context:

```bash
#!/bin/bash
CONTEXT=$(cat <<EOF
$(cat memory/system_state.json 2>/dev/null || echo "No prior state")

Recent commits:
$(git log --oneline -5 2>/dev/null)

Modified files:
$(git diff --name-only HEAD 2>/dev/null)

Current branch: $(git branch --show-current 2>/dev/null)
EOF
)
PROMPT="${1:-read the context and identify the next unblocked task}"
# Pass $CONTEXT to orchestrator as system context
```

---

### Memory Retrieval Strategy — 3-Layer Workflow

Agents retrieve memory in three token-efficient steps
(~10× token savings vs. fetching full context on every call):

1. **Index search** — compact result list with IDs (~50–100 tokens/result)
2. **Timeline** — chronological context around relevant results
3. **Full fetch** — detailed content for filtered IDs only (~500–1000 tokens/result)

| Query Type | Strategy |
|------------|----------|
| Recent context | Recency-weighted (last N sessions) |
| Similar errors | Semantic vector search (Qdrant) |
| Architecture decisions | Keyword lookup in project memory |
| Fix patterns | Exact signature match → semantic fallback |
| Prompt templates | Agent role lookup → semantic similarity |

**Stack:** Qdrant (vectors) + SQLite (metadata) + flat files (state + journals)

### Privacy Convention

Agents respect `<private>` tags in any source file or context.
Content wrapped in `<private>...</private>` is excluded from memory storage
and Qdrant indexing — the user's escape hatch for sensitive logic, API keys
referenced in context, or proprietary business rules.

---

## 15. Debug Loop + Circuit Breaker

### Debug Loop

```
Execute code
      ↓
Observe result (stdout + stderr + pytest output)
      ↓
Check fix pattern store ─── match found → apply fix, emit PATTERN_LEARNED, re-execute
      ↓ (no match)
Debug Agent analyzes ErrorReport
  └─ suspected_cause required in output schema
      ↓
PatchRequest emitted
      ↓
Tool Execution Engine applies patch (with safety checks)
      ↓
Re-execute
      ↓
Write to session journal
      ↓
retry_count++
If retry_count >= 5 → Circuit Breaker
```

### Circuit Breaker

```
max_retries_per_task = 5

retry < 5   → continue debug loop

retry >= 5  → emit CIRCUIT_BREAKER_FIRED

Decision tree:
  IF fix_pattern_exists AND not yet tried
      → apply pattern, reset count
  ELIF human_checkpoint_enabled
      → escalate to human
  ELIF mode == "auto"
      → skip task, mark BLOCKED, continue pipeline
  ELSE
      → halt pipeline
```

All circuit breaker activations are written to the session journal with full context,
error sequence, and attempted fixes. This becomes training data for the fix pattern store.

---

## 16. Human-in-the-Loop Checkpoints

| Checkpoint | Trigger | Human Options |
|------------|---------|---------------|
| 1 — Post-scan | After codebase intel (existing repos) | Confirm understanding / correct |
| 2 — Post-planning | After Planner produces DAG | Approve / Edit / Reject |
| 3 — Post-failure | Circuit breaker fires | Guide / Skip / Abort |
| 4 — Pre-deploy | Before destructive operations | Confirm / Cancel |
| 5 — Insight escalation | Orchestrator Intel Feed raises `requires_action` | Review / Override |

**Run modes:**
- `sage run --research` → all checkpoints mandatory
- `sage run --auto` → checkpoint only on circuit breaker and insight escalation
- `sage run --silent` → no checkpoints, skip failed tasks automatically

## 17. Session Continuity + Handoff Protocol

SAGE maintains context across unexpected interruptions — model overload, timeout, crash,
or manual abort. When a session ends for any reason, a handoff snapshot is written
immediately so a new session resumes at the exact point of interruption.

### Handoff File — `memory/handoff.json`

```json
{
  "interrupted_at": "2026-03-16T14:22:00Z",
  "reason": "model_timeout | user_abort | crash",
  "active_task_id": "implement_auth",
  "dag_snapshot": "...",
  "last_file_written": "backend/auth.py",
  "last_command_run": "pip install python-jose",
  "open_file_handles": [],
  "fix_patterns_applied": ["jwt_secret_missing"],
  "resume_instruction": "Continue from implement_auth. auth.py is partially written \u2014 JWT encode logic done, decode missing."
}
```

### `session_manager.py` Lifecycle

| Event | Action |
|-------|--------|
| `SESSION_INTERRUPTED` | Write `handoff.json` with full snapshot |
| `SESSION_RESUMED` | Read `handoff.json`, restore DAG state, inject resume context |
| `SESSION_END` (clean) | Delete `handoff.json`, write clean `system_state.json` |

On `sage run`, the orchestrator checks for `handoff.json` before anything else.
If present: resume mode. If absent: fresh session.

---

## 18. User Rules Layer

SAGE respects a per-project rules file that governs agent behaviour without
modifying the system prompt. This is the equivalent of Cursor Rules \u2014 applied
globally to every agent call for that project.

### `.sage-rules.md` (per-repo)

```markdown
# SAGE Project Rules

## Code Style
- Always use type hints in Python
- Black formatting enforced
- No print() \u2014 use logging.info()

## Architecture Constraints
- Never use global state
- All DB access through repository pattern only

## Agent Behaviour
- Always run pytest before emitting TASK_COMPLETED
- Never generate placeholder comments (# TODO)
- Require suspected_cause in every ErrorReport

## Safety
- Never write to /etc or /usr
- Always request human checkpoint before deleting files
```

SAGE ships with a default `.sage-rules.md` template. Users override or extend it per project.
The Prompt Intelligence Middleware injects active rules into every agent prompt.

---

## 19. Reinforcement Learning Strategy \u2014 3-Tier Routing

SAGE's model routing evolves across build phases from heuristic to learned.

| Tier | Active | Method | Scope |
|------|--------|---------|-------|
| Tier 1 | Phase 1\u20134 | UCB contextual bandit | Local vs. cloud selection per task type |
| Tier 2 | Phase 5 | Offline RL (Behavior Cloning + CQL) | Full routing policy (model + template + agent) |
| Tier 3 | Phase 6+ | Online fine-tuning | Continuous policy improvement in deployment |

### Tier 1 \u2014 UCB Bandit (Ships in Phase 1)

Runs silently from day one. Explores model choices, exploits winners.
No training required \u2014 updates in milliseconds per call.

```python
# rl/bandit.py \u2014 Upper Confidence Bound
def select_model(self, context: TaskContext) -> str:
    ucb_scores = {
        m: self.means[m] + math.sqrt(2 * math.log(self.n) / self.counts[m])
        for m in self.models
    }
    return max(ucb_scores, key=ucb_scores.get)
```

### Reward Function (all tiers)

```python
reward = (
    0.4 * task_success_binary
  + 0.3 * (1 - normalized_latency)
  + 0.2 * (1 - normalized_cost)
  + 0.1 * epistemic_confidence_score
)
```

---

## 20. System Execution Flow


Complete pipeline from prompt to repository:

```
sage run "your idea"
      ↓
sage-context.sh
  └─ load system_state.json
  └─ read git log, diff, branch
      ↓
Prompt Intelligence Middleware
  └─ RAG retrieval from knowledge base
  └─ inject agent-role template
  └─ recency-weighted prompt selection
      ↓
Model Router → assign Llama 3 to Planner
      ↓
Planner Agent
  └─ produce Task DAG
  └─ generate project spec
      ↓
Human Checkpoint 1 (approve / edit / reject)
      ↓
Task Scheduler
  └─ resolve dependencies
  └─ queue up to MAX_PARALLEL=3 tasks
      ↓
For each task:
  ├─ Memory Manager → load project + session context
  ├─ Prompt Intelligence Middleware → enhance prompt
  ├─ Model Router → assign correct model
  ├─ Assigned Agent (Coder / Architect) → emit PatchRequest
  ├─ Tool Execution Engine → apply patch (safety checked)
  ├─ Execute tests / commands
  ├─ [success] → emit TASK_COMPLETED → scheduler advances
  ├─ [failure] → check fix pattern store
  │     [match] → apply fix, re-execute
  │     [no match] → Debug Agent → patch → retry
  │     [max retries] → Circuit Breaker → escalate / skip / halt
  └─ MEMORY_CHECKPOINT every 5 tasks
      ↓
SESSION_END event
  └─ update system_state.json
  └─ append session journal
  └─ run git post-commit hook
  └─ emit metrics to benchmark log
      ↓
Output Repository
```

---

## 18. Observability System

Every layer of SAGE produces structured logs. This is what makes it research-grade —
you can audit exactly why the system succeeded or failed on any run.

### What Gets Logged

- Prompt before AND after middleware transformation (enables quality delta measurement)
- Model routing decisions with reason
- Task status transitions with timestamps
- All tool calls and outputs
- Debug loop iterations with patch diffs
- Circuit breaker activations with full error context
- Fix pattern store hits and misses
- Memory reads and writes
- Token usage per agent call

### Per-Run Metrics

```json
{
  "run_id": "uuid",
  "prompt": "user input",
  "tasks_total": 8,
  "tasks_completed": 7,
  "tasks_failed": 1,
  "debug_loop_iterations": 3,
  "circuit_breaker_activations": 0,
  "fix_pattern_hits": 2,
  "fix_pattern_misses": 1,
  "total_time_seconds": 142,
  "models_used": {
    "deepseek-coder:6.7b": 6,
    "llama3:8b": 2
  },
  "prompt_quality_delta": 0.23,
  "local_vs_cloud_ratio": 0.9
}
```

### Future: SAGE Dashboard

A visual interface showing:
- Live task graph (nodes colour-coded: pending / running / failed / completed)
- Agent activity timeline
- Debug loop trace with patch diffs
- Memory state inspector
- Prompt before/after comparison with quality score
- Fix pattern learning curve over time (sessions on x-axis, hit rate on y-axis)

This is also the killer demo for the open-source launch video.

---

## 19. Benchmark System

Benchmarks are what separate SAGE from a demo project.

### Standard Task Suite

| Task | Complexity | Success Criteria |
|------|-----------|-----------------|
| Generate REST API | Low | pytest passes, server starts |
| Build CRUD web app | Medium | all endpoints return 200 |
| Fix GitHub issue (given repo) | Medium | tests pass after patch |
| Add feature to existing repo | High | no regressions, new tests pass |
| Build full-stack app | High | frontend + backend + DB running |

### Metrics

| Metric | Definition | Research Value |
|--------|-----------|----------------|
| Build success rate | % of runs producing working code | Primary benchmark |
| Test pass rate | % of generated tests that pass | Code quality |
| Debug loop iterations | Average iterations to fix failures | Efficiency |
| Fix pattern hit rate | % of errors resolved from memory | Self-improvement |
| Prompt quality delta | Output quality before vs after middleware | **Novel contribution** |
| Time to completion | Wall clock per task | Practical utility |
| Local vs cloud ratio | % of calls resolved locally | Privacy/cost story |

The **prompt quality delta** metric is unique to SAGE. It directly measures whether
the middleware makes a measurable difference — and it's the publishable research finding.

---

## 20. Technology Stack

### Local Runtime

| Tool | Role |
|------|------|
| Ollama | Local LLM serving |
| DeepSeek-Coder 6.7B | Primary coding model |
| Codestral | Debugger model |
| Llama 3 8B | Planning + reasoning |

### Cloud Fallback

| Model | Use Case |
|-------|---------|
| Claude | Complex planning, design review |
| GPT-4o | Hard debugging, unfamiliar languages |
| Gemini | Documentation generation |

### Orchestration

| Tool | Role |
|------|------|
| LangGraph | State machine orchestration |
| Skill Templates | Auto-injected workflow discipline (TDD, debug methodology) |

### Memory & Storage

| Tool | Role |
|------|------|
| Qdrant | Vector search (semantic retrieval) |
| SQLite | Task graph state + metadata |
| Flat files | system_state.json, session logs, fix patterns |

### Execution & Safety

| Tool | Role |
|------|------|
| Python subprocess | Fast local execution (non-destructive) |
| Docker | Isolated execution (destructive / untrusted commands) |
| pytest | Test runner |
| git | Version control + commit hooks |

---

## 21. Repository Structure

```
sage/
  agents/
    planner.py
    architect.py
    coder.py
    debugger.py
    reviewer.py
    test_engineer.py
    memory_optimizer.py

  orchestrator/
    workflow.py            ← LangGraph state machine
    task_graph.py          ← DAG + TaskNode
    task_scheduler.py      ← scheduling + parallelism
    event_bus.py           ← async event bus
    model_router.py        ← routing table + fallback logic
    session_manager.py     ← handoff write/read, resume logic

  execution/
    executor.py
    sandbox.py             ← Docker sandbox wrapper
    safety.py              ← safety limits enforcement

  memory/
    manager.py
    vector_store.py        ← Qdrant integration
    session_logger.py
    fix_patterns.py        ← self-learning fix store

  prompt_engine/
    middleware.py          ← RAG + template injection
    rag_retriever.py
    quality_scorer.py      ← prompt quality delta measurement
    templates/
      planner.md
      architect.md
      coder.md
      debugger.md
      reviewer.md
      memory_optimizer.md

  protocol/
    schemas.py             ← TaskResult, PatchRequest, ErrorReport, AgentInsight, Event

  rl/
    bandit.py              ← Tier 1: UCB contextual bandit
    trajectory_logger.py   ← Tier 2: (state, action, reward) logging
    policy.py              ← Tier 2: RoutingPolicy MLP
    reward.py              ← composite reward function
    trainer.py             ← Behavior Cloning + CQL training loop

  tools/
    filesystem.py
    terminal.py
    git_tools.py

  scripts/
    sage-context.sh        ← session context injection
    post-commit.sh         ← git hook → .sage-memory.md
    memory_optimizer.sh    ← weekly cron

  cli/
    main.py                ← sage run | sage status | sage memory | sage bench

  benchmarks/
    tasks/
      rest_api.yaml
      crud_app.yaml
      bug_fix.yaml
      full_stack.yaml
    runner.py
    metrics.py

  config/
    models.yaml            ← model routing + fallback config
    pipeline.yaml          ← safety limits + scheduler config

  docs/
    implementation_plan.md ← this file
    getting_started.md
    contributing.md
    research_notes.md      ← benchmark results, ablation studies
```

---

## 22. Development Roadmap

### Phase 1 — Core Pipeline (Week 1)
**Goal:** `sage run "build FastAPI hello world"` produces working code

- [x] LangGraph workflow skeleton: load_memory → planner → scheduler → coder → save_memory
- [x] `sage-context.sh` + `system_state.json` (memory layer 1)
- [x] Task DAG (sequential + parallel scheduling where enabled)
- [x] Reference-repo skill integration (TDD/debug discipline via SKILL.md injection)
- [x] Git hook + `.sage-memory.md`
- [x] CLI: `sage run "prompt"`

### Phase 2 — Execution + Debug Loop (Week 2)
**Goal:** Self-healing debug loop working on simple projects

- [x] Tool Execution Engine with safety limits
- [x] Executor + pytest integration
- [x] Debug Agent (Codestral-class; configurable in `models.yaml`)
- [x] Fix Pattern Store (memory layer 4)
- [x] Circuit breaker (max 5 retries)
- [x] Session journals (memory layer 2)
- [x] `MEMORY_CHECKPOINT` event every 5 tasks

### Phase 3 — Task Graph + Events (Week 3)
**Goal:** Multi-task project generation end-to-end

- [x] Full DAG with dependency resolution
- [x] Task Scheduler (MAX_PARALLEL=3)
- [x] Async event bus (strict FIFO processing; see `src/sage/orchestrator/event_bus.py`)
- [x] Model Router (full routing table + YAML triggers)
- [x] Human-in-the-loop checkpoints (core types wired; polish for all five)
- [x] Project memory (memory layer 3)
- [x] CLI: `sage status`, `sage memory`

### Phase 4 — Intelligence Layers (Week 4)
**Goal:** Open-source ready, demo video recorded

- [x] Prompt Intelligence Middleware (RAG over docs + fix patterns)
- [x] Qdrant vector store integration
- [x] Prompt quality delta measurement
- [x] Memory Optimizer Agent + weekly cron
- [x] Full benchmark suite: 6 cases, 8 metrics (see `src/sage/benchmarks/runner.py`)
- [x] CLI: `sage bench`
- [x] README, architecture diagram, contributing guide

### Phase 5 — RL Routing (Month 2)
**Goal:** Tier 2 offline RL routing policy operational

- [ ] Trajectory logger: record (state, action, reward) for all routing decisions
- [ ] Train RoutingPolicy MLP via Behavior Cloning on logged data
- [ ] CQL fine-tuning for offline RL safety
- [ ] A/B test: UCB bandit vs. RL policy on benchmark suite
- [ ] Publish routing policy performance results

### Phase 6 — Research + Simulator (Month 3+)
**Goal:** arxiv-publishable benchmark results

- [ ] SAGE Simulator: run benchmark tasks without real execution (for fast ablation)
- [ ] Ablation suite: with/without prompt middleware, with/without fix patterns, with/without RL routing
- [ ] Publish benchmark baselines vs. SAGE on SWE-bench subset
- [ ] Draft arxiv paper: prompt quality delta + fix pattern learning curves

**Detailed Phase 5–6 engineering tasks:** [`SAGE_phase5_6_tasks.md`](SAGE_phase5_6_tasks.md) (trajectory export → BC → CQL → router integration → simulator → PPO).

### 22.1 Next priorities (aligned with SAGE v1 FINAL §26.1)

1. **Models:** Keep `config/models.yaml` tags aligned with `ollama list` (avoid 404 on unpulled tags). Document **plug-and-play** recommended tiers; optional **SAGE-fine-tuned** model ships after stable routing.
2. **Benchmarks:** Stabilize `sage bench` under real Ollama latency (timeout policy or CI profile).
3. **Event bus:** Validate strict ordering under parallel tasks; document lifecycle hooks.
4. **Phase 5+:** Offline RL when trajectory volume warrants it.

---

## 23. Minimum Viable System

The smallest SAGE that is still meaningfully better than anything else:

```
sage-context.sh (load state)
      ↓
Planner (Llama 3) → Task DAG (sequential)
      ↓
Coder (DeepSeek-Coder) → PatchRequest
      ↓
Executor (subprocess, no Docker) → ExecutionResult
      ↓
Fix Pattern Store check
      ↓ (no match)
Debug Agent (Codestral) → PatchRequest → retry
      ↓ (max 5 retries)
Circuit Breaker → skip + log
      ↓
save_memory (system_state.json + session journal + git hook)
```

This MVP is already more robust than most open-source agent systems because it has:
- Circuit breaker (no infinite loops)
- Persistent session state (no starting from zero)
- Structured inter-agent protocol (no hallucinated formats)
- Execution safety limits (no runaway processes)
- Fix pattern learning (gets better over time)

---

## 24. Self-Improvement Loops

The two compounding loops that make SAGE research-grade.

### Loop 1 — Prompt Learning

```
Weak prompt
      ↓
Prompt Intelligence Middleware retrieves best known strategies
      ↓
Structured, model-specific, context-aware prompt
      ↓
Better output
      ↓
Log quality score → successful prompts rank higher in future retrieval
```

Measured by: **prompt quality delta** (output quality before vs after middleware)

### Loop 2 — Debug Learning

```
Error encountered
      ↓
Debug Agent analyzes and fixes (first occurrence)
      ↓
Fix pattern stored: error_signature → fix, success_rate tracked
      ↓
Next identical error: skip debug loop entirely, apply known fix
      ↓
Success rate of each pattern tracked over time
```

Measured by: **fix pattern hit rate** (% of errors resolved from memory, not debug agent)

### Compounding Effect

Session 1: slow, iterative, debug-heavy
Session 10: most common errors auto-fixed, prompts optimised from experience
Session 50: fix pattern hit rate > 60%, prompt quality delta > 0.3

Both loops are measurable. The learning curves are the publishable finding.

---

## 25. Open Source Strategy

### Why Open Source

- Community contributes agents, prompt templates, and model adapters for free
- Research citations when benchmark results are published
- GitHub stars → YouTube views → developer attention → startup optionality
- Forces documentation quality that makes the system credible
- Ablation studies require reproducibility — open source enforces this

### What Makes It Research-Grade

1. Reproducible benchmark suite with published baselines
2. Prompt quality delta measurement (middleware before/after comparison)
3. Fix pattern learning curve over time (does the system actually improve?)
4. Ablation capability: run with/without prompt middleware, with/without fix patterns
5. Structured logging that enables full reproduction of any run

### Release Plan

| Release | Contents | Goal |
|---------|---------|------|
| v0.1 | MVP pipeline (Phases 1-2) | GitHub stars |
| v0.2 | Full multi-agent system (Phases 3-4) | Developer adoption |
| v0.3 | Benchmark results + research notes | Citations |

---

## 26. Long-Term Vision

SAGE becomes an **AI Software Engineering Lab** — not just a tool, but a platform
for researching how multi-agent systems can reliably write software.

**Capabilities:**
- Generate full production applications from a single prompt
- Self-improve measurably across sessions through pattern learning
- Benchmark different local and cloud models on real engineering tasks
- Reproduce and study agent system failures systematically

**Outcomes:**
- Research platform with published benchmarks and an arxiv paper
- Open-source ecosystem with community-contributed agents and templates
- Startup foundation: the infrastructure others build on

SAGE is what you get when you combine Airflow's orchestration discipline,
Cursor's code editing patterns, Devin's execution loop, and a prompt engineering
engine that none of them have.

---

## Quick Start

```bash
# Clone and setup
git clone https://github.com/yourusername/sage
cd sage
pip install -r requirements.txt
ollama pull deepseek-coder:6.7b llama3:8b codestral

# Scaffold memory
mkdir -p memory/{sessions,projects,fixes,weekly}
touch memory/system_state.json

# Install git hook
cp scripts/post-commit.sh .git/hooks/post-commit
chmod +x .git/hooks/post-commit

# Run your first project
sage run "Build a FastAPI backend with JWT authentication and PostgreSQL"
```

---

*SAGE — Self-improving Autonomous Generation Engine*
*prompt → production*

---

END OF SPECIFICATION v1.0
*Architecture finalised. Implementation begins Phase 1.*
