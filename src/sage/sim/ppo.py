"""
PPO-style online RL shell (Phase 6). Full training requires a simulator rollout loop.

Use after ``oracle_tasks`` + ``parallel_runner`` produce reward-labelled trajectories.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any


@dataclass
class PPOConfig:
    learning_rate: float = 3e-4
    gamma: float = 0.99
    clip_range: float = 0.2
    n_epochs: int = 4
    batch_size: int = 64


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _policy_prob_fallback(w: list[float], x: list[float]) -> float:
    # logistic: p = sigmoid(w0 + w1*x0 + w2*x1)
    z = w[0] + w[1] * x[0] + w[2] * x[1]
    return _sigmoid(z)


def train_ppo(
    *,
    steps: int = 2000,
    seed: int = 42,
    config: PPOConfig | None = None,
) -> dict[str, Any]:
    """
    Minimal working PPO on a toy contextual-bandit simulator.

    This is a correctness-focused implementation to satisfy Phase 6 wiring; it is not
    intended to be research-grade PPO.
    """
    cfg = config or PPOConfig()
    rng = random.Random(seed)

    # Policy weights for 2-feature context: [bias, w_complexity, w_failures]
    w = [0.0, 0.0, 0.0]

    # Value baseline as a scalar (bandit); updated with EMA.
    v = 0.0
    v_alpha = 0.05

    def sample_context() -> list[float]:
        # complexity in [0,1], failures in {0..4} scaled
        c = rng.random()
        f = rng.randint(0, 4) / 4.0
        return [c, f]

    def env_reward(x: list[float], a_fb: int) -> float:
        # Same shape as synthetic collection: fallback helps on hard tasks.
        c, f = x
        base = 0.85 - 0.45 * c - 0.25 * f
        if a_fb == 1:
            base += 0.35 * c + 0.10 * f
        noise = rng.uniform(-0.05, 0.05)
        r = base + noise
        return max(-1.0, min(1.0, r))

    def grad_logp(w_: list[float], x: list[float], a_fb: int) -> list[float]:
        p = _policy_prob_fallback(w_, x)
        # Bernoulli logistic regression gradient:
        # d/dw log pi(a|x) = (a - p) * [1, x0, x1]
        a = float(a_fb)
        g0 = a - p
        return [g0, g0 * x[0], g0 * x[1]]

    # Rollout buffer
    buf_x: list[list[float]] = []
    buf_a: list[int] = []
    buf_oldp: list[float] = []
    buf_adv: list[float] = []
    buf_r: list[float] = []

    for t in range(int(steps)):
        x = sample_context()
        p_fb = _policy_prob_fallback(w, x)
        a_fb = 1 if rng.random() < p_fb else 0
        r = env_reward(x, a_fb)
        adv = r - v

        # Update baseline
        v = (1.0 - v_alpha) * v + v_alpha * r

        buf_x.append(x)
        buf_a.append(a_fb)
        buf_oldp.append(p_fb if a_fb == 1 else (1.0 - p_fb))
        buf_adv.append(adv)
        buf_r.append(r)

        # Train in mini-batches
        if len(buf_x) >= cfg.batch_size:
            for _epoch in range(cfg.n_epochs):
                # simple shuffle
                idxs = list(range(len(buf_x)))
                rng.shuffle(idxs)
                for i in idxs:
                    xi = buf_x[i]
                    ai = buf_a[i]
                    oldpi = max(1e-6, float(buf_oldp[i]))
                    advi = float(buf_adv[i])

                    p = _policy_prob_fallback(w, xi)
                    pi = p if ai == 1 else (1.0 - p)
                    pi = max(1e-6, float(pi))

                    ratio = pi / oldpi
                    clip_lo = 1.0 - cfg.clip_range
                    clip_hi = 1.0 + cfg.clip_range
                    clipped = min(max(ratio, clip_lo), clip_hi)
                    obj = min(ratio * advi, clipped * advi)

                    g = grad_logp(w, xi, ai)
                    # Gradient ascent on objective
                    lr = float(cfg.learning_rate)
                    for j in range(3):
                        w[j] += lr * g[j] * (1.0 if obj >= 0 else -1.0)

            buf_x.clear()
            buf_a.clear()
            buf_oldp.clear()
            buf_adv.clear()
            buf_r.clear()

    return {
        "status": "ok",
        "steps": int(steps),
        "seed": int(seed),
        "weights": w,
        "baseline_v": v,
    }
