"""RI-02, RI-03: scenarios, windows, scanning many runs, and the scan cache."""

import numpy as np
import pytest

import simview as sv
from simview.core.entity import Entity
from simview.investigate import Catalog, Scenario, ScenarioError, scan, windows
from simview.investigate.runs import RunData
from simview.investigate.scenario import load_scenarios, parse_duration, save_scenarios

DT = 0.01


class Still(Entity):
    state_names = ("x",)

    def derivative(self, t, x, u):
        return np.zeros(1)


def schedule(seed):
    """Injected events (start tick, ticks) that must match, and near misses that must not."""
    rng = np.random.default_rng(seed)
    events, misses = [], []
    tick = 20
    for _ in range(rng.integers(1, 4)):
        length = int(rng.integers(5, 30))  # 0.05-0.30 s: long enough (>= 0.05 s)
        events.append((tick, length))
        tick += length + int(rng.integers(10, 40))
        misses.append((tick, 4))  # 0.04 s above the threshold: too short
        tick += 4 + int(rng.integers(10, 40))
    return events, misses, tick + 30


def event_scene(seed):
    events, misses, end = schedule(seed)
    load = np.random.default_rng(seed + 1000).uniform(0.0, 1.9, end)  # noise below 2
    for start, length in events + misses:
        load[start : start + length] = 2.5
    load[end - 25 : end - 5] = 1.99  # long but never above the threshold
    scene = sv.Scene(dt=DT, seed=seed)
    scene.add_entity(Still([0.0], name="probe"))
    scene.log("load", lambda sim: float(load[min(sim.tick, end - 1)]), unit="N")
    return scene, events, end


def test_twenty_runs_every_event_found_no_false_matches(tmp_path):
    """M5b done-when: a scenario defined once finds every injected event across 20 runs."""
    catalog = Catalog(tmp_path / "runs")
    expected = {}
    for seed in range(20):
        scene, events, end = event_scene(seed)
        info = sv.run(scene, (end - 1) * DT, out=catalog.folder / f"run{seed:02d}.parquet")
        expected[info.path.name] = [((s) * DT, (s + n - 1) * DT) for s, n in events]
    overload = Scenario("overload", "load > 2 for 0.05 s")
    results = scan(catalog, [overload])
    assert len(results) == 20
    total = 0
    for r in results:
        got = [(w.start, w.end) for w in r.matches]
        want = expected[r.run.path.name]
        assert len(got) == len(want), r.run.name  # no misses, no false matches
        np.testing.assert_allclose(np.array(got), np.array(want), atol=1e-9)
        assert not r.missing
        total += len(got)
    assert total == sum(len(v) for v in expected.values())
    f = results[0].findings[0]
    assert f.signals == ("load",) and f.run == results[0].run and f.end > f.start


def test_expressions():
    t = np.arange(100) * 0.01

    class Run:
        signals = ("a.x", "b", "odd name")
        dt = 0.01

        def __init__(self):
            self.t = t
            self.cols = {"a.x": np.sin(t * 10), "b": t * 2, "odd name": -t}

        def __contains__(self, n):
            return n == "t" or n in self.cols

        def __getitem__(self, n):
            return t if n == "t" else self.cols[n]

    run = Run()
    sc = Scenario("s", "abs(a.x) > 0.9 and t > 0.5 and not b > 1.8 for 20 ms")
    assert sc.duration == pytest.approx(0.02) and sc.signals == ("a.x", "b")
    mask = sc.mask(run)
    assert mask.dtype == bool and mask.sum() > 0
    assert np.all(t[mask] > 0.5) and np.all(np.abs(np.sin(t[mask] * 10)) > 0.9)
    assert Scenario("q", "`odd name` < -0.5").mask(run).sum() == 49
    assert Scenario("c", "0.2 < b <= 0.4").mask(run).sum() == 10  # chained comparison
    assert Scenario("f", "max(b, 1) - min(b, 1) >= 0 and sqrt(hypot(b, b)) >= 0").mask(run).all()
    assert parse_duration("x > 1 for 1.5e-2 s") == ("x > 1", pytest.approx(0.015))
    assert parse_duration("x > 1") == ("x > 1", 0.0)


@pytest.mark.parametrize(
    "bad",
    [
        "__import__('os').system('x') > 0",
        "a.x.__class__ > 1",  # fine syntactically, but not a signal: reported missing, not run
        "open('f') > 0",
        "'text' == 1",
        "[1, 2] > 0",
        "lambda: 1",
        "a.x >",
        "a[0] > 1",
        "True",
    ],
)
def test_unsafe_or_bad_expressions_are_rejected(bad):
    if bad == "a.x.__class__ > 1":
        assert Scenario("s", bad).signals == ("a.x.__class__",)
        return
    with pytest.raises(ScenarioError):
        Scenario("s", bad)


def test_windows_count_samples_as_dt_long():
    t = np.arange(10) * 0.1
    mask = np.array([0, 1, 1, 0, 1, 1, 1, 1, 0, 1], bool)
    ws = windows(t, mask, 0.3, 0.1)  # 3 samples = 0.3 s
    assert len(ws) == 1 and (ws[0].start, ws[0].end) == pytest.approx((0.4, 0.7))
    assert len(windows(t, mask, 0.0, 0.1)) == 3  # including the last sample
    assert windows(t, np.ones(10, bool), 0, 0.1)[0].duration == pytest.approx(0.9)


def test_missing_signals_are_reported_not_unmatched(tmp_path):
    catalog = Catalog(tmp_path)
    scene, _events, end = event_scene(1)
    sv.run(scene, (end - 1) * DT, out=tmp_path / "a.parquet")
    expr = Scenario("drone", "drone.z > 1 and load > 2")
    pred = Scenario("pred", predicate=lambda run: run["nope"] > 0, signals=())
    res = {r.scenario.name: r for r in scan(catalog, [expr, pred])}
    assert res["drone"].missing == ["drone.z"] and res["drone"].matches == []
    assert res["pred"].missing == ["nope"]
    with pytest.raises(ScenarioError):
        Scenario("both", "x > 1", predicate=lambda r: r["x"] > 1)


def test_predicate_scenarios():
    scene, events, end = event_scene(3)
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    info = sv.run(scene, (end - 1) * DT, out=folder / "p.parquet")
    run = Catalog(folder).open(info.path.name)
    assert isinstance(run, RunData)
    sc = Scenario(
        "overload (python)", predicate=lambda r: r["load"] > 2, signals=["load"], duration=0.05
    )
    assert [w.start for w in sc.scan(run).matches] == pytest.approx([s * DT for s, _ in events])


def test_scan_cache_reads_only_new_or_changed_runs(tmp_path, monkeypatch):
    catalog = Catalog(tmp_path)
    for seed in (1, 2):
        scene, _e, end = event_scene(seed)
        sv.run(scene, (end - 1) * DT, out=tmp_path / f"r{seed}.parquet")
    sc = Scenario("overload", "load > 2 for 0.05 s")
    first = scan(catalog, [sc])
    reads = []
    import simview.investigate.scenario as mod

    real = mod.RunData
    monkeypatch.setattr(mod, "RunData", lambda info: reads.append(info.name) or real(info))
    again = scan(catalog, [sc])
    assert reads == [] and [len(r.matches) for r in again] == [len(r.matches) for r in first]
    scene, _e, end = event_scene(3)
    sv.run(scene, (end - 1) * DT, out=tmp_path / "r3.parquet")  # a new run: scanned
    scan(catalog, [sc])
    assert reads == ["r3"]
    scan(catalog, [Scenario("other", "load > 1")])  # a new scenario: every run read
    assert sorted(reads[1:]) == ["r1", "r2", "r3"]


def test_scenarios_file_round_trip(tmp_path):
    scs = [Scenario("a", "x > 1 for 0.1 s"), Scenario("b", "y < 0")]
    save_scenarios(tmp_path, scs)
    back = load_scenarios(tmp_path)
    assert [(s.name, s.expression, s.duration) for s in back] == [
        ("a", "x > 1 for 0.1 s", pytest.approx(0.1)),
        ("b", "y < 0", 0.0),
    ]
    assert load_scenarios(tmp_path / "none") == []
