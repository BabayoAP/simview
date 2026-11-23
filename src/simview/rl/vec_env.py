"""N headless copies of a scene stepped in parallel processes (SE-09), as a Stable-Baselines3
`VecEnv` (ML-02):

    if __name__ == "__main__":  # the envs run in spawned processes
        venv = sv.make_vec_env("drone_landing", n_envs=8)
        model = PPO("MlpPolicy", venv).learn(200_000)

Each process loads the scene itself, so pass a scene file, a template id, or a function that
builds the scene (not a `Scene` object, which belongs to this process).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from simview.core.scene import Scene
from simview.rl.env import SceneSource, make_env
from simview.rl.spec import MISSING_RL


def make_vec_env(
    scene: SceneSource,
    n_envs: int = 4,
    *,
    seed: int | None = None,
    subprocess: bool = True,
    monitor_dir: str | None = None,
    record_every: int = 0,
    record_dir: str | None = None,
    **kwargs: Any,
) -> Any:  # noqa: ANN401 - a stable_baselines3 VecEnv (an optional dependency)
    """`n_envs` envs (`make_env(scene, **kwargs)`), each wrapped in SB3's `Monitor` (episode
    reward and length; SB3 reads the success rate from `info["is_success"]`), in a
    `SubprocVecEnv` (spawned processes) or, with `subprocess=False`, a `DummyVecEnv` stepping
    them in turn in this process. Env i is seeded `seed + i`. `record_every=N` records every
    env's episode stats, and every Nth episode's full log, into the training folder (ML-04)."""
    try:
        from stable_baselines3.common.monitor import Monitor
        from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
    except ImportError as exc:
        raise ImportError(MISSING_RL) from exc
    if n_envs < 1:
        raise ValueError(f"n_envs must be >= 1, got {n_envs}")
    if isinstance(scene, Scene) and (n_envs > 1 or subprocess):
        raise TypeError(
            "a Scene object can't be copied into other processes: pass its scene file, a "
            "template id, or a function that builds it"
        )

    folder = None
    if record_every > 0:  # one folder for all envs, chosen here (the workers inherit it)
        from simview.rl.metrics import training_dir

        folder = str(training_dir(record_dir))

    def env_fn(env_index: int) -> Any:
        return make_env(
            scene,
            record_every=record_every,
            record_dir=folder,
            env_index=env_index,
            n_envs=n_envs,
            **kwargs,
        )

    def factory(i: int) -> Any:
        def init() -> Any:
            path = None if monitor_dir is None else str(Path(monitor_dir) / str(i))
            return Monitor(env_fn(i), filename=path)

        return init

    fns = [factory(i) for i in range(n_envs)]
    venv = SubprocVecEnv(fns, start_method="spawn") if subprocess else DummyVecEnv(fns)
    if seed is not None:
        venv.seed(seed)  # env i resets with seed + i
    return venv
