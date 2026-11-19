"""RI-01, RI-04, RI-05, RI-06 and the `simview runs` CLI."""

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import pytest

import simview as sv
from simview.core.scheduler import Sim
from simview.investigate import Catalog, Scenario, compare, import_log, scan, write_report
from simview.investigate.cli import main as cli
from simview.investigate.runs import read_info
from simview.ipc.protocol import describe
from simview.ipc.record import record_row, replay_rows, row_layout
from simview.ipc.shm import Layout
from simview.runner.headless import load_scene
from tests.investigate.test_scenario import DT, event_scene

ROOT = Path(__file__).resolve().parents[2]
PICK = ROOT / "examples" / "ur5_pick.py"


def make_runs(folder, seeds=(1, 2)):
    out = []
    for seed in seeds:
        scene, _events, end = event_scene(seed)
        out.append(sv.run(scene, (end - 1) * DT, out=Path(folder) / f"r{seed}.parquet"))
    return out


# -- RI-01: catalog ---------------------------------------------------------------------------
def test_catalog_lists_filters_and_opens(tmp_path):
    make_runs(tmp_path)
    scene = load_scene(PICK)
    sv.run(scene, 0.1, out=tmp_path / "pick.parquet")
    (tmp_path / "broken.parquet").write_bytes(b"not parquet")  # skipped, not fatal
    cat = Catalog(tmp_path)
    runs = cat.runs()
    assert {r.name for r in runs} == {"r1", "r2", "pick"}
    pick = cat.get("pick")
    assert pick.scene == str(PICK.resolve()) and pick.seed == 0 and pick.source == "sim"
    assert pick.duration == pytest.approx(0.1) and pick.dt == pytest.approx(0.002)
    assert pick.date and "ur5.shoulder_pan_joint.q" in pick.signals
    assert [r.name for r in cat.filter("ur5_pick")] == ["pick"]
    assert {r.name for r in cat.filter(seed=1)} == {"r1"}
    assert [r.name for r in cat.filter(scene="ur5_pick.py")] == ["pick"]
    assert cat.filter(source="import") == []
    data = cat.open("pick.parquet")
    assert len(data["t"]) == pick.rows == 51 and data.dt == pytest.approx(0.002)
    with pytest.raises(KeyError):
        data["nope"]
    with pytest.raises(FileNotFoundError):
        cat.get("missing")
    assert cat.new_path("pick").name == "pick-1.parquet"
    assert Catalog(tmp_path / "none").runs() == []


def test_same_seed_logs_stay_byte_identical(tmp_path):
    """NF-06 still holds: the run's context (date, scene file) lives in a sidecar file."""
    a = sv.run(load_scene(PICK), 0.05, out=tmp_path / "a.parquet")
    b = sv.run(load_scene(PICK), 0.05, out=tmp_path / "b.parquet")
    assert a.path.read_bytes() == b.path.read_bytes()
    assert (tmp_path / "a.run.json").exists()


# -- RI-05: comparison ------------------------------------------------------------------------
def test_compare_finds_first_divergence_and_one_sided_matches(tmp_path):
    a, b = make_runs(tmp_path, (4, 4))[0], None
    # the same run with a bump at t = 0.5 s and one extra overload
    table = pq.read_table(a.path)
    load = table.column("load").to_numpy().copy()
    load[50:60] = 3.0
    b_path = tmp_path / "bumped.parquet"
    pq.write_table(
        table.set_column(table.schema.get_field_index("load"), "load", pa.array(load)), b_path
    )
    cat = Catalog(tmp_path)
    run, base = cat.open("bumped"), cat.open(a.path.name)
    same = compare(base, cat.open(a.path.name))
    assert not same.diverged and same.overlap[1] > 0
    sc = Scenario("overload", "load > 2 for 0.05 s")
    c = compare(run, base, atol=1e-6, scenarios=[sc])
    (d,) = c.diverged
    assert d.signal == "load" and d.first_divergence == pytest.approx(0.5)
    assert [(w.start, w.end) for w in c.only_run_matches["overload"]] == [
        (pytest.approx(0.5), pytest.approx(0.59))
    ]
    titles = [f.title for f in c.findings]
    assert any("diverges" in t for t in titles) and any("not in baseline" in t for t in titles)
    assert b is None


def test_compare_interpolates_different_sample_rates(tmp_path):
    t1, t2 = np.arange(0, 1.0001, 0.01), np.arange(0, 1.0001, 0.025)
    for name, t, extra in (("fine", t1, True), ("coarse", t2, False)):
        cols = {"t": t, "tick": np.arange(len(t)), "x": 2 * t}
        if extra:
            cols["only_fine"] = t
        pq.write_table(pa.table(cols), tmp_path / f"{name}.parquet")
    cat = Catalog(tmp_path)
    c = compare(cat.open("fine"), cat.open("coarse"), atol=1e-9)
    assert not c.diverged and c.only_in_run == ["only_fine"]
    assert c.signals[0].max_abs < 1e-12


# -- RI-06: import and replay -----------------------------------------------------------------
def robot_csv(tmp_path):
    """A 'real' UR5 log: joint angles under the robot's own column names, in ms, shuffled."""
    t_ms = np.arange(0, 1000, 4.0)  # 250 Hz
    q = np.column_stack([0.3 * np.sin(t_ms / 300 + k) for k in range(6)])
    cols = {"time_ms": t_ms, **{f"j{k + 1}": q[:, k] for k in range(6)}, "current": t_ms / 1e3}
    table = pa.table(cols)
    order = np.random.default_rng(0).permutation(len(t_ms))
    table = table.take(pa.array(np.concatenate([order, order[:5]])))  # unsorted, duplicates
    path = tmp_path / "ur5_log.csv"
    pacsv.write_csv(table, path)
    return path, t_ms / 1e3, q


JOINTS = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)


def test_import_csv_with_mapping(tmp_path):
    path, t, q = robot_csv(tmp_path)
    cat = Catalog(tmp_path / "runs")
    mapping = {f"ur5.{j}.q": f"j{k + 1}" for k, j in enumerate(JOINTS)}
    info = import_log(
        path,
        cat,
        mapping=mapping,
        time_column="time_ms",
        time_scale=1e-3,
        scene=ROOT / "examples" / "ur5_ik_drag.py",
    )
    assert info.source == "import" and info.rows == 250
    assert info.dt == pytest.approx(0.004) and info.duration == pytest.approx(t[-1])
    assert info.scene.endswith("ur5_ik_drag.py")
    run = cat.open(info)
    np.testing.assert_allclose(run["ur5.elbow_joint.q"], q[:, 2])
    np.testing.assert_allclose(run["current"], t)  # unmapped numeric columns are kept
    assert np.all(np.diff(run["t"]) > 0)
    with pytest.raises(ValueError, match="no column"):
        import_log(path, cat, mapping={"ur5.x": "nope"}, time_column="time_ms")
    with pytest.raises(ValueError, match="time column"):
        import_log(path, cat)


def test_imported_log_replays_through_the_scene(tmp_path):
    """RI-06: mapped states drive the scene, so the viewport's poses and markers follow."""
    path, _t, q = robot_csv(tmp_path)
    cat = Catalog(tmp_path / "runs")
    mapping = {f"ur5.{j}.q": f"j{k + 1}" for k, j in enumerate(JOINTS)}
    info = import_log(path, cat, mapping=mapping, time_column="time_ms", time_scale=1e-3)
    scene = load_scene(ROOT / "examples" / "ur5_ik_drag.py")
    sim = Sim(scene)
    desc = describe(scene)
    state = Layout.build(
        [e.name for e in desc.entities],
        [len(scene[e.name].x) for e in desc.entities],
        [e.name for e in desc.entities if e.has_marker],
        scene.world.model.nbody,
    )
    lay = row_layout(scene, state)
    rows, dt = replay_rows(scene, sim, lay, str(info.path))
    assert rows.shape == (250, lay.width) and dt == pytest.approx(0.004)
    arm = scene["ur5"]
    k = 123
    np.testing.assert_allclose(rows[k, 1:7], q[k])  # the joint states
    marker = rows[k, lay.markers_at : lay.markers_at + 3]
    np.testing.assert_allclose(marker, arm.fk(q[k])[:3, 3], atol=1e-9)  # FK of the logged q
    assert np.isnan(rows[k, 1 + lay.signals.index("tool_error")])  # channel not in the log
    assert record_row  # (the live recorder shares the row layout)


# -- RI-04: reports ---------------------------------------------------------------------------
def test_report_for_the_uc3_pick_run(tmp_path):
    """M5b done-when: a report for the UC-3 pick run exports with its plots."""
    info = sv.run(load_scene(PICK), 5.5, out=tmp_path / "pick.parquet")
    cat = Catalog(tmp_path)
    lifted = Scenario("cube lifted", "cube.z > 0.08 for 0.5 s")
    grip = Scenario("fingers closed", "grip.close_l.q > 0.01 for 100 ms")
    drone = Scenario("drone high", "drone.z > 1")
    results = scan(cat, [lifted, grip, drone])
    out = write_report([cat.open(info.path.name)], results, tmp_path / "pick.html")
    page = out.read_text(encoding="utf-8")
    assert page.count("<svg") >= 2  # one plot per matched scenario, inline
    assert "cube lifted" in page and "cube.z" in page and "fingers closed" in page
    assert "not checked, this run doesn't log drone.z" in page
    assert "ur5_pick.py" in page and "<td>cube.z</td><td>m</td>" in page
    assert "<script" not in page and "http" not in page.split("<svg", 1)[0]  # self-contained
    assert read_info(info.path).rows == 2751


def test_comparison_report(tmp_path):
    runs = make_runs(tmp_path, (5, 6))
    cat = Catalog(tmp_path)
    a, b = cat.open(runs[0].path.name), cat.open(runs[1].path.name)
    c = compare(a, b, atol=1e-6)
    out = write_report([a, b], [], tmp_path / "cmp.html", comparison=c, title="a vs b")
    page = out.read_text(encoding="utf-8")
    assert "First divergence" in page and "<svg" in page and "a vs b" in page


# -- CLI --------------------------------------------------------------------------------------
def test_cli(tmp_path, capsys):
    runs = make_runs(tmp_path / "runs", (7, 8))
    f = str(tmp_path / "runs")
    assert cli(["--folder", f, "list"]) == 0
    assert "r7" in capsys.readouterr().out
    assert cli(["--folder", f, "scan", "-s", "overload: load > 2 for 0.05 s", "--save"]) == 0
    out = capsys.readouterr().out
    assert "overload at" in out and "matches" in out
    assert (tmp_path / "runs" / "scenarios.json").exists()
    html = tmp_path / "r.html"
    assert cli(["--folder", f, "report", "r7", "-o", str(html)]) == 0 and html.exists()
    capsys.readouterr()
    assert cli(["--folder", f, "compare", "r7", "r7"]) == 0  # identical: no divergence
    assert cli(["--folder", f, "compare", "r7", "r8", "-o", str(tmp_path / "c.html")]) == 1
    assert "diverges at" in capsys.readouterr().out
    csv, _t, _q = robot_csv(tmp_path)
    assert (
        cli(
            [
                "--folder",
                f,
                "import",
                str(csv),
                "--time",
                "time_ms",
                "--time-scale",
                "0.001",
                "--map",
                "ur5.shoulder_pan_joint.q=j1",
            ]
        )
        == 0
    )
    assert "250 rows" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli(["--folder", f, "import", str(csv), "--map", "bad"])
    assert runs
