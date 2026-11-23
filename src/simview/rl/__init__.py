"""Reinforcement learning (ML-01..ML-04): scenes as Gymnasium envs, parallel vector envs, and
training metrics. Needs the `rl` extra (`pip install 'simview[rl]'`)."""

from __future__ import annotations

from typing import Any

__all__ = ["SimEnv", "log_metric", "make_env", "make_vec_env", "sb3_logger", "training_dir"]


def __getattr__(name: str) -> Any:
    # Gymnasium and Stable-Baselines3 load on first use (an optional extra).
    if name in ("SimEnv", "make_env"):
        from simview.rl import env

        return getattr(env, name)
    if name in ("log_metric", "sb3_logger", "training_dir"):
        from simview.rl import metrics

        return getattr(metrics, name)
    if name == "make_vec_env":
        from simview.rl.vec_env import make_vec_env

        return make_vec_env
    raise AttributeError(f"module 'simview.rl' has no attribute {name!r}")
