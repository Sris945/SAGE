# Models (plug-and-play)

SAGE does **not** require a single vendor model. You choose **primary** and **fallback** models per agent role in:

`src/sage/config/models.yaml`

Ollama model names must match what you have locally — run `ollama list`. If the API returns **404 model not found**, the tag was never pulled (`ollama pull <name>`) or the name is wrong.

## Why model choice matters more now

SAGE runs an **agentic ReAct tool-use loop** (Phase 1+). The coder agent now calls tools iteratively across many turns (`read_file → grep_code → edit_file → run_command → done`) instead of emitting a single-shot JSON patch. This requires:

- **Reliable JSON output** across multiple turns (not just once)
- **Enough context** to hold a multi-turn conversation + codebase snippets
- **Instruction following** fidelity under tool-call pressure

Small models (≤3B) will frequently hallucinate tool names or emit malformed JSON, causing the loop to exhaust its 24-turn budget. **14B+ is the practical floor for the coder role**.

## Recommended models by VRAM tier

| Tier | VRAM | Model | Best for |
|------|------|-------|----------|
| Minimum | ~8 GB | `qwen2.5-coder:7b` | planner, shell, docs |
| Good | ~10 GB | `deepseek-coder-v2:16b-lite-base-q4_K_M` | coder primary on 12 GB GPU |
| Recommended | ~12 GB | `qwen2.5-coder:14b-instruct-q4_K_M` | coder, reviewer, debugger |
| Best offline | ~20 GB | `qwen2.5-coder:32b-instruct-q4_K_M` | coder/debugger on 24 GB GPU |
| Strongest reasoning | ~28 GB | `deepseek-coder-v2:236b-instruct-q2_K` | CPU+GPU offload, slow but capable |

### Pulling models

```bash
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b-instruct-q4_K_M
ollama pull qwen2.5-coder:32b-instruct-q4_K_M
# Optional: alternate strong coder
ollama pull deepseek-coder-v2:16b-lite-base-q4_K_M
```

## Role guide

| Role | Default primary | Why |
|------|-----------------|-----|
| `planner` | `qwen2.5-coder:7b` | Task decomposition; fast iteration preferred |
| `architect` | `qwen2.5-coder:14b-instruct-q4_K_M` | Needs stronger reasoning for system design |
| `coder` | `qwen2.5-coder:14b-instruct-q4_K_M` | Tool-use loop; 14B+ for JSON fidelity |
| `debugger` | `qwen2.5-coder:32b-instruct-q4_K_M` | Hard bug analysis; use the biggest model that fits |
| `reviewer` | `qwen2.5-coder:14b-instruct-q4_K_M` | Per-file + cross-file review; needs structured JSON output |
| `test_engineer` | `qwen2.5-coder:14b-instruct-q4_K_M` | pytest generation; moderate load |
| `documentation` | `qwen2.5-coder:7b` | Prose; small model fine |
| `memory_optimizer` | `qwen2.5-coder:7b` | Session summarisation; light load |

## Disabling the agentic loop

Set `SAGE_TOOL_LOOP=0` to revert to the legacy single-shot PatchRequest mode (one file written per task, no iterative tool calls). Useful for debugging or for very small models that cannot handle multi-turn tool use:

```bash
SAGE_TOOL_LOOP=0 sage run "add logging to auth.py"
```

## Internal vs user-chosen models

- **Agent chat** (planner, architect, coder, debugger, …): **you** configure in `models.yaml`.
- **Embeddings** (fix-pattern RAG, Qdrant code index): typically `nomic-embed-text`. Swap only if you know the dimension constraints of your vector store path.

## Context window sizing

SAGE's context compressor (`sage.memory.context_compressor`) limits codebase context injection to `MAX_CONTEXT_CHARS = 16 000` characters (~4K tokens). Combined with the tool-loop history this comfortably fits inside a 32K context window. If you use a model with a smaller context window (e.g. 8K), consider lowering `MAX_CONTEXT_CHARS` or `MAX_CHUNKS` in that file.

## Benchmarks and timeouts

`sage bench` sets **`SAGE_BENCH=1`**, which scales Ollama client timeouts. Override if needed:

| Variable | Meaning |
|----------|---------|
| `SAGE_BENCH_TIMEOUT_MULT` | Multiply per-call timeouts (default `3`) |
| `SAGE_BENCH_CHAT_MAX_S` | Cap for chat calls (default `180`) |
| `SAGE_BENCH_EMBED_MAX_S` | Cap for embedding calls during bench (default `15`) |

Normal `sage run` does **not** set `SAGE_BENCH` unless you export it yourself.
