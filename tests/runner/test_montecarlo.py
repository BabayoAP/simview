"""SE-08: Monte Carlo and parameter sweeps."""

import textwrap

import numpy as np
import pyarrow.parquet as pq
import pytest

import simview as sv
from simview.runner.headless import load_scene
from simview.runner.montecarlo import plan_trials
from simview.templates import scene_path

SCENE = textwrap.dedent(
    """
    import numpy as np
    import simview as sv

    class Spring(sv.Entity):
        state_names = ("x", "v")

        def derivative(self, t, x, u):
            push = u[0] if len(u) else 0.0
            return np.array([x[1], -scene.params.k * x[0] - scene.params.c * x[1] + push])

    scene = sv.Scene(dt=0.01, seed=0)
    scene.params.k = 4.0
    scene.params.c = 0.5
    scene.params.noise = 0.1
    if scene.params.k > 100:
        raise ValueError("k too stiff")
    spring = scene.add_entity(Spring([1.0, 0.0], name="spring"))
    built_with_k = scene.params.k  # read during setup, like the templates do

    @scene.controller()
    def push(t, state, ctx):
        return {"spring": [ctx.params.noise * ctx.rng.standard_normal()]}

    scene.log("k_at_build", lambda sim: built_with_k)
    scene.metric("peak", lambda run: float(np.abs(run["spring.x"][10:]).max()))
    scene.metric("final_x", lambda run: float(run["spring.x"][-1]))
    """
)


@pytest.fixture
def scene_file(tmp_path):
    path = tmp_path / "spring.py"
    path.write_text(SCENE)
    return path


def double_final_x(run):  # module level: picklable for worker processes
    return 2.0 * float(run["spring.x"][-1])


def test_plan_grid_times_trials_and_seeded_samples():
    plan = plan_trials({"c": sv.Uniform(0.1, 0.9), "noise": 0.2}, {"k": [1, 2, 3]}, 4, seed=7)
    assert len(plan) == 12
    assert [r["k"] for r in plan] == [1.0] * 4 + [2.0] * 4 + [3.0] * 4
    assert all(0.1 <= r["c"] < 0.9 and r["noise"] == 0.2 for r in plan)
    again = plan_trials({"c": sv.Uniform(0.1, 0.9), "noise": 0.2}, {"k": [1, 2, 3]}, 4, seed=7)
    assert plan == again
    assert plan != plan_trials({"c": sv.Uniform(0.1, 0.9)}, {"k": [1, 2, 3]}, 4, seed=8)


def test_distributions():
    rng = np.random.default_rng(0)
    n = [sv.Normal(1.0, 0.5).sample(rng) for _ in range(4000)]
    assert abs(np.mean(n) - 1.0) < 0.03 and abs(np.std(n) - 0.5) < 0.03
    clipped = [sv.Normal(0.0, 1.0, lo=0.0).sample(rng) for _ in range(200)]
    assert min(clipped) == 0.0
    assert set(sv.Choice([1, 2]).sample(rng) for _ in range(50)) == {1.0, 2.0}
    with pytest.raises(ValueError):
        sv.Uniform(1, 1)
    with pytest.raises(ValueError):
        plan_trials({"k": 1.0}, {"k": [1.0]}, 1, 0)
    with pytest.raises(ValueError):
        plan_trials(None, None, 0, 0)


def test_load_scene_overrides_params_at_declaration(scene_file):
    scene = load_scene(scene_file, params={"k": 9.0}, seed=5)
    assert scene.params.k == 9.0 and scene.params.c == 0.5 and scene.seed == 5
    assert scene.channels["k_at_build"](None) == 9.0  # setup code saw the new value
    with pytest.raises(KeyError, match="kk"):
        load_scene(scene_file, params={"kk": 1.0})
    assert load_scene(scene_file).params.k == 4.0  # overrides don't leak into later loads


def test_sweep_collects_params_and_metrics(scene_file, tmp_path):
    res = sv.sweep(
        scene_file,
        2.0,
        grid={"k": [1.0, 16.0]},
        params={"c": sv.Uniform(0.2, 1.0)},
        trials=3,
        workers=0,
        out=tmp_path / "sw",
    )
    assert len(res) == 6 and res.params == ["k", "c"] and res.metrics == ["peak", "final_x"]
    assert list(res["trial"]) == list(range(6)) and list(res["seed"]) == list(range(6))
    assert np.all(res.ok) and np.all(res["log"] == "")
    assert not list((tmp_path / "sw").glob("trial-*"))  # logs dropped by default
    # a stiffer spring oscillates faster: its final position differs from the soft ones
    assert np.std(res["final_x"][:3]) > 0 and np.all(res["peak"] <= 1.0 + 1e-9)
    again = sv.SweepResults.load(tmp_path / "sw")
    assert again.params == res.params and np.array_equal(again["final_x"], res["final_x"])
    assert "6 trials, 0 failed" in repr(again)


def test_parallel_sweep_matches_serial(scene_file, tmp_path):
    kw = dict(params={"k": sv.Normal(4.0, 1.0, lo=0.5), "noise": 0.3}, trials=4)
    serial = sv.sweep(scene_file, 1.0, workers=0, out=tmp_path / "a", **kw)
    parallel = sv.sweep(scene_file, 1.0, workers=2, out=tmp_path / "b", **kw)
    for col in ("trial", "seed", "k", "noise", "peak", "final_x"):
        np.testing.assert_array_equal(serial[col], parallel[col])
    # each trial has its own seed, so the noise differs between trials with the same k
    assert len(set(serial["final_x"])) == 4


def test_failed_trial_is_reported_not_raised(scene_file, tmp_path):
    res = sv.sweep(scene_file, 0.5, grid={"k": [4.0, 500.0]}, workers=0, out=tmp_path / "f")
    assert list(res["status"]) == ["ok", "error"]
    assert "k too stiff" in res["error"][1]
    assert np.isnan(res["peak"][1]) and np.isfinite(res["peak"][0])
    assert "1 failed" in repr(res)


def test_metric_selection_columns_callables_and_kept_logs(scene_file, tmp_path):
    res = sv.sweep(
        scene_file,
        0.5,
        metrics=["final_x", "spring.v"],
        workers=0,
        keep_logs=True,
        out=tmp_path / "m",
    )
    assert res.metrics == ["final_x", "spring.v"]
    log = pq.read_table(res["log"][0])  # the kept log is a normal run log
    assert log.column("spring.v").to_numpy()[-1] == res["spring.v"][0]
    extra = sv.sweep(
        scene_file, 0.5, metrics={"twice": double_final_x}, workers=1, out=tmp_path / "x"
    )
    assert extra.metrics == ["twice"] and np.isfinite(extra["twice"][0])
    bad = sv.sweep(scene_file, 0.5, metrics=["nope"], workers=0, out=tmp_path / "n")
    assert bad["status"][0] == "error" and "nope" in bad["error"][0]


def test_50_trial_monte_carlo_finishes(scene_file, tmp_path):
    """M9 done-when: a 50-trial Monte Carlo finishes (in parallel processes)."""
    seen = []
    res = sv.sweep(
        scene_file,
        1.0,
        params={"k": sv.Uniform(1.0, 10.0), "noise": sv.Uniform(0.0, 0.5)},
        trials=50,
        workers=4,
        out=tmp_path / "mc",
        on_trial=lambda done, total, row: seen.append((done, total)),
    )
    assert len(res) == 50 and np.all(res.ok)
    assert seen[-1] == (50, 50) and len(seen) == 50


def test_drone_delivery_template_sweeps(tmp_path):
    """UC-2's knobs reach the scene, and its metrics come out (a short run: not delivered)."""
    res = sv.sweep(
        scene_path("drone_delivery"),
        0.2,
        grid={"gust": [0.5, 3.0]},
        metrics=["params.gust", "delivered", "max_deviation"],
        workers=0,
        out=tmp_path / "uc2",
    )
    assert np.all(res.ok), res["error"]
    np.testing.assert_array_equal(res["params.gust"], [0.5, 3.0])
    assert list(res["delivered"]) == [0.0, 0.0]
