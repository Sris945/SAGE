# Models (plug-and-play)

SAGE does **not** require a single vendor model. You choose **primary** and **fallback** models per agent role in:

`src/sage/config/models.yaml`

Ollama model names must match what you have locally — run `ollama list`. If the API returns **404 model not found**, the tag was never pulled (`ollama pull <name>`) or the name is wrong.

## Recommended tiers (rough VRAM guide)

These are **rules of thumb** for **single-GPU** local inference; CPU-only will be much slower. Use smaller primaries on limited hardware; keep **fallback** as a stronger model for hard tasks if it fits your VRAM.

| Tier | Approx VRAM | Example roles | Notes |
|------|-------------|---------------|--------|
| Small | ~4–8 GB | planner/coder primary, reviewer | Fast iteration; may need fallback for hard bugs |
| Medium | ~8–16 GB | coder fallback, debugger fallback | Good balance for many desktops |
| Large | ~16–24+ GB | debugger primary (e.g. Codestral 22B), heavy codegen | Match tags to `ollama list` (e.g. `codestral:22b`) |

Default repo settings evolve with `models.yaml`; treat this table as **documentation**, not a hard requirement.

## Internal vs user-chosen models

- **Agent chat** (planner, architect, coder, debugger, …): **you** configure in `models.yaml`.
- **Embeddings** (fix-pattern RAG, etc.): typically a **small** embedding model (e.g. `nomic-embed-text` in code paths that call Ollama embeddings). Swap only if you know the dimension constraints of your vector store path.

## Benchmarks and timeouts

`sage bench` sets **`SAGE_BENCH=1`**, which scales Ollama client timeouts (see `sage.llm.ollama_safe.effective_ollama_timeout`). Override if needed:

| Variable | Meaning |
|----------|---------|
| `SAGE_BENCH_TIMEOUT_MULT` | Multiply per-call timeouts (default `3`) |
| `SAGE_BENCH_CHAT_MAX_S` | Cap for chat calls (default `180`) |
| `SAGE_BENCH_EMBED_MAX_S` | Cap for embedding calls during bench (default `15`) |

Normal `sage run` does **not** set `SAGE_BENCH` unless you export it yourself.
