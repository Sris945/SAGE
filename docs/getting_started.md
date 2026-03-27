## Getting started (Spec-parity)

See `README.md` for setup and quickstart.

Useful commands:

- `sage run "prompt"`
- `sage bench`
- Phase 5:
  - `sage rl collect-synth --rows 650`
  - `sage rl export --output datasets/routing_v1.jsonl`
  - `sage rl analyze-rewards --data datasets/routing_v1.jsonl`
  - `sage rl train-bc --data datasets/routing_v1.jsonl`
  - `sage rl train-cql --data datasets/routing_v1.jsonl`
  - `sage rl eval-offline --data datasets/routing_v1.jsonl --checkpoint memory/rl/policy_cql.joblib`
- Phase 6:
  - `sage sim generate --count 1000 --out datasets/sim_tasks.jsonl`
  - `sage sim run --tasks datasets/sim_tasks.jsonl --workers 4`
  - `docker build -f sim/Dockerfile -t sage-sim:latest .`
  - `sage sim run --tasks datasets/sim_tasks.jsonl --workers 4 --docker`

