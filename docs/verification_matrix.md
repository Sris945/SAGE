# Verification matrix (local, reproducible)

This is a pragmatic “CI-style” matrix you can run locally to regenerate the key artifacts and verify the system stays healthy.

## 0) Tests

```bash
python -m pytest tests/ -q
```

## 1) Phase 5 — Offline RL evidence (mixed provenance)

Collect synthetic bootstrap (optional) and export:

```bash
sage rl collect-synth --rows 650
sage rl export --output datasets/routing_v1.jsonl
```

Separate provenance exports (recommended for strict evidence runs):

```bash
sage rl export --output datasets/routing_real_v1.jsonl --data-source real
sage rl export --output datasets/routing_synth_v1.jsonl --data-source synthetic
```

Validate provenance and reward distribution:

```bash
sage rl analyze-rewards --data datasets/routing_v1.jsonl --out datasets/reward_report.json
```

Train policies:

```bash
sage rl train-bc --data datasets/routing_v1.jsonl --out memory/rl/policy_bc.joblib
sage rl train-cql --data datasets/routing_v1.jsonl --out memory/rl/policy_cql.joblib
```

Offline evaluation artifact:

```bash
sage rl eval-offline --data datasets/routing_v1.jsonl --checkpoint memory/rl/policy_cql.joblib --out datasets/offline_eval_cql.json
```

## 2) Bench artifacts

```bash
sage bench --out memory/benchmarks/bench.json
```

Reproducible run-pack (result + manifest protocol metadata):

```bash
sage bench --compare-policy --run-pack-dir memory/benchmarks/run_pack_compare
```

Optional compare mode (LLM-dependent):

```bash
sage bench --compare-policy --out memory/benchmarks/bench_compare.json
```

## 3) Phase 6 — Simulator (non-docker + docker)

Generate tasks and run a subset:

```bash
sage sim generate --count 1000 --out datasets/sim_tasks.jsonl
sage sim run --tasks datasets/sim_tasks.jsonl --workers 4 --limit 50
```

Docker mode (requires Docker):

```bash
docker build -f sim/Dockerfile -t sage-sim:latest .
sage sim run --tasks datasets/sim_tasks.jsonl --workers 4 --limit 20 --docker
```

## 4) PPO smoke

```bash
python -c "from sage.sim.ppo import train_ppo; import json; print(json.dumps(train_ppo(steps=500, seed=1), indent=2))"
```
