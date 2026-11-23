"""DA-06: the Monte Carlo results view."""

import numpy as np
import pytest
from qtpy.QtCore import Qt

import simview as sv
from simview.ui.main_window import MainWindow
from simview.ui.sweep_view import SORT_ROLE, SweepView
from simview.ui.theme import tokens
from tests.runner.test_montecarlo import SCENE


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sweep")
    scene = tmp / "spring.py"
    scene.write_text(SCENE)
    # 2 x 4 trials; k = 500 fails in the scene file (one failed grid point)
    return sv.sweep(
        scene,
        1.0,
        grid={"k": [2.0, 500.0, 9.0]},
        params={"c": sv.Uniform(0.1, 1.0)},
        trials=4,
        workers=0,
        out=tmp / "out",
    )


@pytest.fixture
def view(qapp, results):
    v = SweepView(results)
    v.show()
    yield v
    v.close()


def test_table_lists_every_trial_with_params_metrics_and_errors(view, results):
    m = view.model
    assert m.rowCount() == 12
    assert m.headers == ["trial", "seed", "k", "c", "peak", "final_x", "status", "error"]
    failed = [r for r in range(12) if results["status"][r] == "error"]
    assert failed == [4, 5, 6, 7]
    err = m.index(4, m.headers.index("error"))
    assert "k too stiff" in m.data(err, Qt.ItemDataRole.ToolTipRole)
    assert m.data(m.index(4, 0), Qt.ItemDataRole.ForegroundRole).color().name() == (
        tokens.color("dark", "state.error").lower()
    )
    assert m.data(m.index(0, 0), Qt.ItemDataRole.ForegroundRole) is None
    assert m.data(m.index(4, m.headers.index("peak"))) == "—"  # NaN shows as a dash
    assert "3 trials" not in view.summary.text() and "12 trials" in view.summary.text()
    assert "4 failed" in view.summary.text()


def test_sorting_is_numeric_with_missing_values_last(view, results):
    col = view.model.headers.index("peak")
    view.table.sortByColumn(col, Qt.SortOrder.AscendingOrder)
    vals = [view.proxy.index(r, col).data(SORT_ROLE) for r in range(12)]
    assert vals == sorted(vals) and vals[-4:] == [float("inf")] * 4


def test_histogram_and_scatter_show_the_metric_of_finished_trials(view, results):
    assert view.metric == "peak" and view.param == "k"
    ok = results.ok
    x, y = view.points.getData()
    np.testing.assert_array_equal(x, results["k"][ok])
    np.testing.assert_array_equal(y, results["peak"][ok])
    edges, counts = view.bars.getData()
    assert counts.sum() == ok.sum() == 8
    assert "4 trials not plotted" in view.note.text()
    view.metric_box.setCurrentText("final_x")
    view.param_box.setCurrentText("c")
    x, y = view.points.getData()
    np.testing.assert_array_equal(x, results["c"][ok])
    np.testing.assert_array_equal(y, results["final_x"][ok])
    assert view.scatter.getPlotItem().getAxis("bottom").labelText == "c"


def test_selection_links_table_and_plots(view, results):
    view.select_trial(9)
    assert view.selected_trial == 9
    cx, cy = view.chosen.getData()
    assert cx[0] == results["k"][9] and cy[0] == results["peak"][9]
    assert view.marker.isVisible() and view.marker.value() == results["peak"][9]

    class Point:  # what pyqtgraph hands sigClicked
        def data(self):
            return 2

    view._point_clicked(view.points, [Point()])
    rows = view.table.selectionModel().selectedRows()
    assert view.proxy.mapToSource(rows[0]).row() == 2 and view.selected_trial == 2
    view.select_trial(5)  # a failed trial: selected in the table, nothing to mark
    assert view.selected_trial == 5 and not view.marker.isVisible()
    assert len(view.chosen.getData()[0]) == 0


def test_main_window_opens_sweeps_and_restyles_them(qapp, settings, results, tmp_path):
    w = MainWindow(settings)
    try:
        v = w.open_sweep(results.path.parent)  # the folder works as well as the file
        assert isinstance(v, SweepView) and v.isVisible() and len(v.res) == 12
        assert w.actions_.get("file.open_sweep").text() == "Open Sweep Results…"
        bad = tmp_path / "x.parquet"
        bad.write_bytes(b"not parquet")
        assert w.open_sweep(bad) is None
        assert "Couldn't open" in w.statusBar().currentMessage()
        w.toggle_theme()
        assert v.hist.backgroundBrush().color().name() == tokens.color("light", "bg.panel").lower()
        w.toggle_theme()
        v.close()
    finally:
        w.close()
