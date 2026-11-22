"""ML-01, ML-02, SE-09: scenes as Gymnasium envs and SB3 vector envs."""

import numpy as np
import pytest

gym = pytest.importorskip("gymnasium")
from gymnasium import spaces  # noqa: E402
from gymnasium.utils.env_checker import check_env  # noqa: E402

import simview as sv  # noqa: E402
from simview.runner.headless import load_scene  # noqa: E402
from simview.templates import scene_path  # noqa: E402

BOX1 = spaces.Box(-1.0, 1.0, shape=(1,), dtype=np.float32)


class Cart(sv.Entity):
    """x'' = u (a point mass pushed along x)."""

    state_names = ("x", "v")

    def derivative(self, t, x, u):
        return np.array([x[1], float(u[0]) if len(u) else 0.0])


def cart_scene():
    scene = sv.Scene(dt=0.01, seed=0)
    scene.add_entity(Cart([0.0, 0.0], name="cart"))
    seen = []

    @scene.controller()
    def watch(t, state, ctx):  # controllers see the policy's action
        seen.append(None if ctx.action is None else float(ctx.action[0]))

    scene.seen = seen
    return scene


def cart_env(**kw):
    args = dict(
        action_space=BOX1,
        act_fn=lambda sim, a: {"cart": [2.0 * float(a[0])]},
        rate=20.0,
        max_time=1.0,
        reset_fn=lambda sim, rng: sim.scene["cart"].x.__setitem__(0, rng.uniform(-1, 1)),
    )
    args.update(kw)
    return sv.make_env(
        cart_scene,
        lambda sim: sim.scene["cart"].x.copy(),
        lambda sim, a: -abs(float(sim.scene["cart"].x[0])),
        lambda sim: abs(float(sim.scene["cart"].x[0])) > 2.0,
        **args,
    )


def test_custom_scene_env_passes_env_checker():
    env = cart_env()
    check_env(env, skip_render_check=True)
    assert env.observation_space.shape == (2,) and env.observation_space.dtype == np.float32
    assert env.substeps == 5 and env.max_steps == 20


def test_template_env_passes_env_checker():
    """ML-01 by template id, as in UC-4: make_env("drone_landing")."""
    env = sv.make_env("drone_landing")
    check_env(env, skip_render_check=True)
    assert env.action_space.shape == (3,) and env.observation_space.shape == (6,)
    assert env.substeps == 4 and env.max_steps == 250
    by_path = sv.make_env(scene_path("drone_landing"))
    assert by_path.observation_space == env.observation_space


def test_reset_is_seeded_and_step_advances_the_scene():
    env = cart_env()
    a, _ = env.reset(seed=3)
    b, _ = env.reset(seed=3)
    c, _ = env.reset(seed=4)
    np.testing.assert_array_equal(a, b)
    assert a[0] != c[0] and a[1] == 0.0
    obs, reward, term, trunc, info = env.step(np.array([1.0], np.float32))
    assert info["t"] == pytest.approx(0.05)  # one 20 Hz step = 5 ticks of 10 ms
    assert obs[1] == pytest.approx(0.1)  # v = 2 m/s^2 * 0.05 s
    assert obs[0] == pytest.approx(c[0] + 0.5 * 2.0 * 0.05**2)
    assert reward == pytest.approx(-abs(obs[0]))
    assert not term and not trunc
    assert env.scene.seen[-5:] == [1.0] * 5  # ctx.action on every tick of the step


def test_truncation_and_termination_on_the_exact_tick():
    env = cart_env(reset_fn=None)
    env.reset(seed=0)
    for i in range(20):
        _, _, term, trunc, _ = env.step(np.zeros(1, np.float32))
        assert not term and trunc == (i == 19)
    # pushed hard, the cart passes x = 2 m between control steps: the episode ends right there
    env = cart_env(reset_fn=None, max_time=None, act_fn=lambda sim, a: {"cart": [400.0]})
    env.reset(seed=0)
    t = 0.0
    while True:
        _, _, term, trunc, info = env.step(np.ones(1, np.float32))
        if term:
            break
        t = info["t"]
    x_end = env.scene["cart"].x[0]
    assert x_end > 2.0 and info["t"] - t < env.step_dt  # stopped mid-step
    v = env.scene["cart"].x[1]
    assert x_end - v * 0.01 <= 2.0  # the tick before was still inside 2 m


def test_success_goes_to_info_at_episode_end():
    env = cart_env(reset_fn=None, max_time=0.1, success_fn=lambda sim: True)
    env.reset(seed=0)
    _, _, _, trunc, info = env.step(np.zeros(1, np.float32))
    assert not trunc and "is_success" not in info
    _, _, _, trunc, info = env.step(np.zeros(1, np.float32))
    assert trunc and info["is_success"] is True


def test_bad_arguments():
    with pytest.raises(TypeError, match="action_space"):
        sv.make_env(cart_scene, lambda s: [0.0], lambda s, a: 0.0, lambda s: False)
    with pytest.raises(TypeError, match="unknown"):
        cart_env(bogus=1)
    with pytest.raises(ValueError, match="divide"):
        cart_env(rate=30.0)
    with pytest.raises(FileNotFoundError):
        sv.make_env("no_such_template")
    with pytest.raises(TypeError, match="unknown"):
        sv.Scene().rl_task(obs=1)
    env = cart_env()
    with pytest.raises(RuntimeError, match="reset"):
        env.step(np.zeros(1, np.float32))


def test_drone_landing_baseline_runs_without_a_policy(tmp_path):
    """The card / headless run: no policy, so the PD lander flies; it lands and rests."""
    run = sv.run(load_scene(scene_path("drone_landing")), 12.0, out=tmp_path / "l.parquet")
    assert run["landed"][-1] == 1.0 and run["dist_xy"][-1] < 0.5
    assert run["drone.z"][-1] == pytest.approx(0.05)


# -- SB3 vector envs (ML-02, SE-09) ---------------------------------------------------------------
sb3 = pytest.importorskip("stable_baselines3")


def test_vec_env_in_subprocesses_is_an_sb3_vec_env():
    from stable_baselines3.common.vec_env import SubprocVecEnv, VecEnv

    venv = sv.make_vec_env("drone_landing", n_envs=2, seed=0)
    try:
        assert isinstance(venv, SubprocVecEnv) and isinstance(venv, VecEnv)
        obs = venv.reset()
        assert obs.shape == (2, 6) and not np.array_equal(obs[0], obs[1])  # seeded 0 and 1
        obs, rew, dones, infos = venv.step(np.zeros((2, 3), np.float32))
        assert obs.shape == (2, 6) and rew.shape == (2,) and len(infos) == 2
    finally:
        venv.close()


def test_in_process_vec_env_and_a_short_ppo_run():
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_checker import check_env as sb3_check_env
    from stable_baselines3.common.vec_env import DummyVecEnv

    sb3_check_env(sv.make_env("drone_landing"))
    venv = sv.make_vec_env("drone_landing", n_envs=2, seed=0, subprocess=False)
    assert isinstance(venv, DummyVecEnv)
    model = PPO("MlpPolicy", venv, n_steps=64, batch_size=64, n_epochs=1, seed=0, device="cpu")
    model.learn(128)
    action, _ = model.predict(venv.reset(), deterministic=True)
    assert action.shape == (2, 3)
    with pytest.raises(TypeError, match="Scene object"):
        sv.make_vec_env(cart_scene(), n_envs=2)


# -- recording (ML-03, ML-04) ---------------------------------------------------------------------
def test_recorded_episodes_replay_as_runs(tmp_path, monkeypatch):
    from simview.investigate.runs import read_info
    from simview.rl.metrics import TRAINING_ENV, TrainingRun, log_metric

    monkeypatch.delenv(TRAINING_ENV, raising=False)
    env = sv.make_env("drone_landing", record_every=2, record_dir=tmp_path / "train")
    for ep in range(3):
        env.reset(seed=ep)
        while True:
            *_, term, trunc, _ = env.step(np.zeros(3, np.float32))
            if term or trunc:
                break
    log_metric("custom/x", 5, 1.5)
    tr = TrainingRun(tmp_path / "train")
    assert tr.refresh()
    assert [e["episode"] for e in tr.episodes] == [0, 1, 2]
    assert [bool(e["log"]) for e in tr.episodes] == [True, False, True]
    assert tr.series["custom/x"].values == [1.5]
    assert len(tr.series["episode/return"].values) == 3
    info = read_info(tr.recorded()[0]["log"])
    assert info.scene and info.scene.endswith("scene.py") and info.rows > 10
    assert not tr.refresh()  # nothing new
