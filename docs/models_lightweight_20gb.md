# Lightweight Ollama models (~15–20 GB total)

Rough disk use varies by quant and Ollama version. This set fits a **~15–18 GB** budget and matches `sage setup suggest` defaults for **balanced** machines.

## Recommended pull order

```bash
ollama pull nomic-embed-text:latest
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5-coder:7b-instruct-q4_K_M
```

Optional (only if you have VRAM/disk headroom — adds ~9 GiB):

```bash
ollama pull qwen2.5-coder:14b-instruct-q4_K_M
```

## Apply SAGE routing from hardware

From the repo (editable install):

```bash
sage setup scan
sage setup suggest
sage setup apply
sage setup pull   # runs ollama pull for the suggested tag set
```

`src/sage/config/models.yaml` is updated by `sage setup apply` (package path when developing from source).
