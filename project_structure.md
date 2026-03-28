# SAGE repository layout

High-level map for contributors and readers. Source of truth for behavior is the **`src/sage/`** package and **`docs/`**.

```
.
├── README.md                 # Project overview
├── CONTRIBUTING.md           # Tests, Ruff, Mypy (see CI), contributing workflow
├── pyproject.toml            # Package metadata, [tool.ruff], sage console script
├── startup.sh / startup.ps1  # Optional venv + editable install
├── docs/                     # User and developer docs — index: docs/README.md
├── sage plan/                # SAGE_ARCHITECTURE_V1_FINAL.md (locked design spec)
├── scripts/                  # Local verification, release helpers
├── tests/                    # pytest unit + integration + e2e
├── sim/                      # Simulator / Docker assets (Phase 6)
└── src/sage/
    ├── agents/               # Planner, coder, reviewer, debugger, …
    ├── benchmarks/           # Bench runner + YAML task suites
    ├── cli/                  # sage CLI, shell, chat, branding
    ├── config/               # bundled models.yaml, paths
    ├── execution/            # Tool execution, verification
    ├── llm/                  # Ollama wrappers, timeouts
    ├── memory/               # Memory layers, RAG helpers
    ├── orchestrator/         # LangGraph workflow, model router, event bus
    ├── prompt_engine/        # Skills injection, templates
    ├── rl/                   # Offline RL export, BC, CQL, …
    ├── sim/                  # Oracle tasks, Docker runner, PPO
    └── assets/skills/        # Bundled SKILL.md files for agents
```

## Runtime artifacts (not in git)

- **`.sage/`** — Local policy, workspace state, chat session JSONL (`chat_sessions/`).
- **`memory/`** — Session memory, benchmarks, RL checkpoints (as produced by commands).
- **`.venv/`** — Virtual environment (use `.gitignore`).

## Entry point

- Console script: **`sage`** → `sage.cli.main:main` (`pyproject.toml` `[project.scripts]`).
