"""Any SimView scene as a Gymnasium environment (ML-01).

    env = sv.make_env("drone_landing")                      # a template that declares its task
    env = sv.make_env(scene, obs_fn, reward_fn, done_fn, action_space=Box(-1, 1, (3,)))

The functions get the run's `Sim` (`sim.scene["drone"].x`, `sim.t`, `sim.rng`):

- `obs_fn(sim) -> array`, `reward_fn(sim, action) -> float`, `done_fn(sim) -> bool`
  (terminated: the task ended, e.g. landed or crashed);
- `act_fn(sim, action) -> {entity: input}` (optional) maps an action straight to entity inputs.
  Scene controllers can read the latest action as `ctx.action` instead, which suits an inner
  loop (attitude control) that runs faster than the policy;
- `reset_fn(sim, rng)` (optional) randomizes the start (set `entity.x`) using the env's RNG;
- `success_fn(sim) -> bool` (optional) goes to `info["is_success"]` when an episode ends, which
  Stable-Baselines3 reports as the success rate.

`rate` is the policy's rate in Hz (one env step = 1 / rate seconds of sim time; default: one
scene tick), and `max_time` truncates an episode after that many seconds.

Recording (ML-04): with `record_every=N`, every finished episode's return, length, and success go
to the training folder (`sv.rl.training_dir()`), and every Nth episode is also logged tick by
tick as a normal run log, which the Training panel replays in the viewport.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from simview.core.logger import Logger
from simview.core.scene import Scene
from simview.core.scheduler import Sim
from simview.rl.spec import MISSING_RL, TASK_KEYS

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(MISSING_RL) from exc

SceneSource = Scene | str | Path | Callable[[], Scene]
MAX_RECORD_STEPS = 10_000  # env steps a recorded episode logs at most (no max_time set)


def load_source(source: SceneSource) -> Scene:
    """A scene from a `Scene`, a scene file, a template id (`"drone_landing"`), or a
    function returning a `Scene`."""
    if isinstance(source, Scene):
        return source
    if callable(source):
        scene = source()
        if not isinstance(scene, Scene):
            raise TypeError("the scene factory must return a simview.Scene")
        return scene
    from simview.runner.headless import load_scene
    from simview.templates import scene_path

    path = Path(source)
    if not path.is_file():
        template = scene_path(str(source))
        if template is None:
            raise FileNotFoundError(f"{source!r} is neither a scene file nor a template id")
        path = template
    return load_scene(path)


class SimEnv(gym.Env):
    """A scene run step by step for an RL agent. See the module docstring."""

    metadata: dict[str, Any] = {"render_modes": []}  # noqa: RUF012 - Gymnasium's convention

    def __init__(
        self,
        scene: SceneSource,
        obs_fn: Callable[[Sim], Any] | None = None,
        reward_fn: Callable[[Sim, Any], float] | None = None,
        done_fn: Callable[[Sim], bool] | None = None,
        *,
        record_every: int = 0,
        record_dir: str | Path | None = None,
        env_index: int = 0,
        n_envs: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.scene = load_source(scene)
        # ML-04: episode stats always (when recording), full logs every `record_every`th
        self.record_every = int(record_every)
        self.record_dir: Path | None = None
        if self.record_every > 0:
            from simview.rl.metrics import training_dir

            self.record_dir = training_dir(record_dir)
        self.env_index, self.n_envs = int(env_index), int(n_envs)
        self.episode = -1  # episodes started by this env
        self.total_steps = 0  # env steps taken by this env, all episodes
        self.ep_return = 0.0
        self.logger: Logger | None = None
        unknown = sorted(set(kwargs) - TASK_KEYS)
        if unknown:
            raise TypeError(f"make_env() got unknown arguments: {', '.join(unknown)}")
        spec = {**(self.scene.task or {}), **kwargs}
        for key, fn in (("obs_fn", obs_fn), ("reward_fn", reward_fn), ("done_fn", done_fn)):
            if fn is not None:
                spec[key] = fn
        missing = [k for k in ("obs_fn", "reward_fn", "done_fn", "action_space") if k not in spec]
        if missing:
            raise TypeError(
                f"make_env() needs {', '.join(missing)} (pass them, or declare the scene's "
                "task with scene.rl_task(...))"
            )
        self.obs_fn = spec["obs_fn"]
        self.reward_fn = spec["reward_fn"]
        self.done_fn = spec["done_fn"]
        self.act_fn = spec.get("act_fn")
        self.reset_fn = spec.get("reset_fn")
        self.success_fn = spec.get("success_fn")
        self.action_space = spec["action_space"]
        dt = self.scene.dt
        rate = spec.get("rate")
        if rate is None:
            self.substeps = 1
        else:
            self.substeps = round(1.0 / (rate * dt))
            if self.substeps < 1 or abs(self.substeps * dt * rate - 1.0) > 1e-6:
                raise ValueError(f"rate {rate} Hz must divide the scene rate {1 / dt:g} Hz")
        self.step_dt = self.substeps * dt
        max_time = spec.get("max_time")
        self.max_steps = None if max_time is None else max(1, round(max_time / self.step_dt))
        self.sim: Sim | None = None
        self.steps = 0
        obs_space = spec.get("observation_space")
        if obs_space is None:  # infer the shape from the start state
            probe = Sim(self.scene)
            first = np.asarray(self.obs_fn(probe), dtype=np.float32)
            probe.close()
            obs_space = spaces.Box(-np.inf, np.inf, shape=first.shape, dtype=np.float32)
        self.observation_space = obs_space

    # -- Gymnasium API -------------------------------------------------------------------------
    def _obs(self) -> np.ndarray:
        assert self.sim is not None
        dtype = getattr(self.observation_space, "dtype", np.float32)
        return np.asarray(self.obs_fn(self.sim), dtype=dtype)

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        # Each episode is a fresh run with a seed drawn from the env's RNG: reset(seed=s)
        # repeats exactly, and sensor noise differs between episodes.
        self.scene.seed = int(self.np_random.integers(2**31 - 1))
        if self.sim is not None:
            self.sim.close()  # the previous episode's run ends (D-132)
        sim = Sim(self.scene)
        self.sim = sim
        if self.reset_fn is not None:
            self.reset_fn(sim, self.np_random)
            sim._sample(force=True)  # sensors read the randomized start
        self.steps = 0
        self.episode += 1
        self.ep_return = 0.0
        self.logger = None
        if self.record_dir is not None and self.episode % self.record_every == 0:
            ticks = (self.max_steps or MAX_RECORD_STEPS) * self.substeps + 1
            self.logger = Logger(sim, min(ticks, MAX_RECORD_STEPS * self.substeps + 1))
            self.logger.record()
        return self._obs(), {"t": sim.t}

    def step(self, action: Any) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        sim = self.sim
        if sim is None:
            raise RuntimeError("call reset() before step()")
        action = np.asarray(action, dtype=getattr(self.action_space, "dtype", None))
        sim.action = action
        if self.act_fn is not None:
            for name, u in (self.act_fn(sim, action) or {}).items():
                self.scene[name].u = np.asarray(u, dtype=np.float64)
        terminated = False
        log = self.logger
        for _ in range(self.substeps):  # the episode ends on the tick the task does
            sim.step()
            if log is not None and log.row < len(log.ticks):
                log.record()
            terminated = bool(self.done_fn(sim))
            if terminated:
                break
        self.steps += 1
        truncated = not terminated and self.max_steps is not None and self.steps >= self.max_steps
        reward = float(self.reward_fn(sim, action))
        info: dict[str, Any] = {"t": sim.t}
        if (terminated or truncated) and self.success_fn is not None:
            info["is_success"] = bool(self.success_fn(sim))
        self.total_steps += 1
        self.ep_return += reward
        if (terminated or truncated) and self.record_dir is not None:
            self._finish_episode(info.get("is_success"))
        return self._obs(), reward, terminated, truncated, info

    def close(self) -> None:
        """Gymnasium's close: ends the current episode's run (`Sim.close()`)."""
        if self.sim is not None:
            self.sim.close()
        super().close()

    def _finish_episode(self, success: bool | None) -> None:
        """Write the episode's stats (and its log, if recorded) to the training folder."""
        from simview.rl.metrics import EPISODE_DIR, log_episode
        from simview.runner.run import run_metadata, write_context

        assert self.record_dir is not None and self.sim is not None
        log_path = ""
        if self.logger is not None:
            name = f"env{self.env_index}-ep{self.episode:06d}.parquet"
            path = self.record_dir / EPISODE_DIR / name
            meta = run_metadata(self.scene, self.sim.t, source="rl", params=None)
            self.logger.write(path, meta)
            write_context(path, self.scene)
            log_path = str(path)
            self.logger = None
        log_episode(
            self.record_dir,
            self.env_index,
            {
                "env": self.env_index,
                "episode": self.episode,
                # this env's steps times the number of envs: the global training step, about
                "step": self.total_steps * self.n_envs,
                "return": self.ep_return,
                "length": self.steps,
                "success": success,
                "log": log_path,
                "seed": self.scene.seed,
            },
        )


def make_env(
    scene: SceneSource,
    obs_fn: Callable[[Sim], Any] | None = None,
    reward_fn: Callable[[Sim, Any], float] | None = None,
    done_fn: Callable[[Sim], bool] | None = None,
    **kwargs: Any,
) -> SimEnv:
    """A Gymnasium `Env` that runs `scene` (ML-01). See the module docstring for the arguments;
    any not given come from the scene's `scene.rl_task(...)`."""
    return SimEnv(scene, obs_fn, reward_fn, done_fn, **kwargs)
