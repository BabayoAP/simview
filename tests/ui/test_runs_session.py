"""PRD §5.11 in the app: the Runs panel with the real sim process (RI-01..RI-06).

Covers the M5b done-whens that need the UI: clicking a finding moves the timeline to it within
100 ms, and an imported CSV log replays in the viewport.
"""

import time

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pytest

from simview.ui.main_window import MainWindow
from tests.ui.test_scene_session import DRAG, loaded, pump

MOVING = "moving: abs(ur5.shoulder_pan_joint.v) > 0.05 for 0.02 s"


@pytest.fixture
def window(qapp, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("SIMVIEW_RUNS", str(tmp_path / "runs"))
    w = MainWindow(settings)
    w.open_reports = False
    w.show()
    yield w
    w.close_scene()
    w.close()


def record_and_stop(qapp, w, seconds=0.6):
    """Run the UC-3 drag scene with the target moved, then Stop: the run is saved."""
    w.load_scene(DRAG)
    pump(qapp, lambda: loaded(w) and w.history is not None and w.client.frame() is not None)
    w.runs.add_scenario(MOVING)
    goal = w.client.description.targets["goal"].copy()
    goal[:3, 3] += [0.08, -0.06, 0.05]
    w.sim_view.target_moved.emit("goal", goal)
    w.speed_box.setCurrentIndex(w.speed_box.findText("Max"))
    w.run()
    pump(qapp, lambda: w.history is not None and w.history.n * 0.002 >= seconds)
    w.pause()
    pump(qapp, lambda: not w.client.frame().running)
    pump(qapp, lambda: w.history.n == w.client.frame().tick + 1)
    n = w.history.n
    w.stop()
    pump(qapp, lambda: w.runs.runs() != [])
    return n


def test_stopped_run_is_saved_cataloged_and_scanned(qapp, window):
    """RI-01 + RI-02: Stop saves the live run; it is listed and scanned for the scenarios."""
    n = record_and_stop(qapp, window)
    (run,) = window.runs.runs()
    assert run.source == "app" and run.rows == n and run.scene.endswith("ur5_ik_drag.py")
    assert run.seed == 0 and run.dt == pytest.approx(0.002)
    findings = window.runs.all_findings()
    assert findings and all(f.run.path == run.path for f in findings)
    assert findings[0].signals == ("ur5.shoulder_pan_joint.v",)
    assert window.runs.table.topLevelItem(0).text(6) == str(len(findings))
    assert window.runs.table.topLevelItem(0).text(2) == "app"


def test_finding_click_opens_the_run_and_moves_there_within_100_ms(qapp, window):
    """M5b done-when + RI-03."""
    record_and_stop(qapp, window)
    finding = window.runs.all_findings()[0]
    window.runs.finding_clicked.emit(finding)  # another run is shown: it opens first
    pump(qapp, lambda: window.opened_run is not None)
    h = window.history
    assert window.playback.recorded and h.n == finding.run.rows
    assert window.playback.index == h.index_at(finding.start)
    window.to_start()
    start = time.perf_counter()
    window.runs.finding_clicked.emit(finding)  # the run is open: a seek
    elapsed = time.perf_counter() - start
    assert elapsed < 0.100, elapsed
    assert window.sim_view.frame.t == pytest.approx(finding.start, abs=1e-9)
    assert window.timeline.slider.value() == h.index_at(finding.start)
    plot = next(p for p in window.plots.plots if "ur5.shoulder_pan_joint.v" in p.names)
    x0, x1 = plot.plot.vb.viewRange()[0]
    pad = max(0.5 * (finding.end - finding.start), 50 * h.dt)  # the window, plus context
    assert (x0, x1) == (pytest.approx(finding.start - pad), pytest.approx(finding.end + pad))


def test_an_opened_run_replays_and_stops_at_its_end(qapp, window):
    record_and_stop(qapp, window, seconds=0.3)
    window.open_run(window.runs.runs()[0])
    pump(qapp, lambda: window.opened_run is not None)
    h = window.history
    assert window.playback.index == 0 and "ur5_ik_drag.py —" in window.windowTitle()
    window.speed_box.setCurrentIndex(window.speed_box.findText("10×"))
    window.run()
    assert window.playback.replaying and not window.playback.sim_running
    pump(qapp, lambda: not window.playback.replaying)
    assert window.playback.index == h.n - 1 and not window.client.frame().running
    window.step()  # the end of a saved run: nothing to step to
    assert window.playback.index == h.n - 1
    window.stop()  # back to the live scene
    pump(qapp, lambda: window.opened_run is None and window.history is not None)
    assert not window.playback.recorded


def test_imported_csv_replays_in_the_viewport(qapp, window, tmp_path):
    """M5b done-when + RI-06: a CSV robot log, mapped onto the UR5, drives the viewport."""
    t = np.arange(0, 0.8, 0.005)
    q = np.column_stack([0.4 * np.sin(2 * t + k) - (1.7 if k == 1 else 0) for k in range(6)])
    joints = (
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    )
    csv = tmp_path / "arm.csv"
    pacsv.write_csv(pa.table({"time": t, **{f"q{k}": q[:, k] for k in range(6)}}), csv)
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window) and window.history is not None)
    info = window.import_log(csv, {f"ur5.{j}.q": f"q{k}" for k, j in enumerate(joints)}, "time")
    assert info in window.runs.runs() and info.source == "import"
    window.open_run(info)
    pump(qapp, lambda: window.opened_run is not None)
    k = 77
    window.seek(k)
    frame = window.sim_view.frame
    assert frame.t == pytest.approx(t[k])
    np.testing.assert_allclose(frame.states["ur5"][:6], q[k])
    from simview.runner.headless import load_scene

    arm = load_scene(DRAG)["ur5"]
    np.testing.assert_allclose(frame.markers["ur5"], arm.fk(q[k])[:3, 3], atol=1e-9)
    assert np.abs(frame.bodies).sum() > 0  # body poses for the 3D view


def test_report_and_compare_from_the_panel(qapp, window):
    """RI-04 + RI-05 from the app: files written, comparison findings listed."""
    record_and_stop(qapp, window, seconds=0.3)
    window.run()
    pump(qapp, lambda: window.history is not None and window.history.n > 200)
    window.pause()
    window.stop()  # a second, different run (the target was back at its start)
    pump(qapp, lambda: len(window.runs.runs()) == 2)
    a, b = window.runs.runs()
    report = window.write_report([a])
    assert report.exists() and "<svg" in report.read_text(encoding="utf-8")
    c = window.compare_runs(a, b)
    assert c.signals
    titles = [f.title for f in window.runs.all_findings()]
    assert any(b.name in t for t in titles) or not c.diverged
    for item in (window.runs.table.topLevelItem(0), window.runs.table.topLevelItem(1)):
        item.setSelected(True)
    window.runs.buttons["compare"].click()
    window.runs.buttons["report"].click()
    assert len(list((window.runs_folder() / "reports").glob("*.html"))) >= 2


def test_bad_scenario_is_explained(qapp, window):
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window))
    window.runs.scenario_edit.setText("bad: ur5.q > ")
    window.runs.scenario_edit.returnPressed.emit()
    assert "can't parse" in window.runs.message.text()
    assert window.runs.scenarios == []
