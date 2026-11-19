"""DA-01..DA-04, DA-07, DS-09: the plot panel and signal tree (headless Qt)."""

import os
import time

import numpy as np
import pytest
from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import QColor, QImage

from simview.ipc.record import RowLayout
from simview.ipc.shm import Layout
from simview.ui.plots.panel import PlotPanel, label
from simview.ui.plots.signals import SIGNAL_MIME, SignalTree, decode, encode
from simview.ui.theme import tokens
from simview.ui.timeline.history import History


def make_history(n=1000, signals=("drone.x", "drone.y", "drone.z", "err"), dt=0.01):
    units = tuple("m" if s.startswith("drone.") else "" for s in signals)
    lay = RowLayout(tuple(signals), units, Layout.build(["drone"], [3], ["drone"], 0))
    h = History(lay, dt)
    t = np.arange(n) * dt
    cols = [np.arange(n)] + [np.sin(t + k) for k in range(len(signals))]
    cols += [np.zeros(n)] * 3  # marker
    h.append(np.column_stack(cols))
    return h


@pytest.fixture
def panel(qapp):
    p = PlotPanel(lambda: None)
    p.resize(800, 400)
    p.set_history(make_history())
    p.show()
    yield p
    p.close()


def test_signal_tree_groups_by_entity_and_drags_names(qapp):
    tree = SignalTree()
    tree.load(make_history().layout)
    assert set(tree.groups) == {"drone", "Channels"}
    assert tree.leaves["drone.z"].text(0) == "z" and tree.leaves["drone.z"].text(1) == "m"
    assert tree.leaves["err"].text(0) == "err"
    mime = tree.mimeData([tree.groups["drone"]])  # a group drags all of its signals
    assert mime.hasFormat(SIGNAL_MIME)
    assert decode(mime) == ["drone.x", "drone.y", "drone.z"]
    got = []
    tree.activated.connect(got.append)
    tree.itemDoubleClicked.emit(tree.leaves["err"], 0)
    assert got == [["err"]]
    sel = []
    tree.selected.connect(sel.append)
    tree.leaves["drone.y"].setSelected(True)
    assert sel[-1] == "drone"  # DS-06: a signal's entity is the selection
    tree.select(None)
    assert not tree.selectedItems()


def test_drop_on_empty_panel_makes_a_time_plot(panel):
    assert not panel.plots
    panel.plot_signals(decode(encode(["drone.z"])))
    (view,) = panel.plots
    assert view.kind == "time" and view.names == ["drone.z"]
    view.widget.dropped.emit(["err", "nope", "drone.z"])  # unknown and repeated ignored
    assert view.names == ["drone.z", "err"]


def test_time_plot_style_and_labels(panel):
    """DS-09 / §7.6: units on axes, 1.5 px data, 1 px accent cursor, mono ticks, grid."""
    view = panel.add_plot("time", ["drone.z"])
    view.refresh()
    p = view.plot
    assert p.getAxis("bottom").labelText == "Time [s]"
    assert p.getAxis("left").labelText == "drone.z [m]"
    curve = view.curves["drone.z"]
    assert curve.opts["pen"].widthF() == tokens.PLOT_LINE_WIDTH
    view.set_cursor(500)
    assert view.cursor.isVisible() and view.cursor.value() == pytest.approx(5.0)
    pen = view.cursor.pen
    assert pen.widthF() == tokens.PLOT_REF_WIDTH
    assert pen.color().name().upper() == tokens.color("dark", "accent")
    assert p.getAxis("left").style["tickFont"].family() == tokens.FONT_MONO
    assert p.getAxis("left").grid is not False
    view.add_signals(["err"])
    assert p.getAxis("left").labelText == "Value"  # mixed units: no unit claimed
    assert label("a", "") == "a" and label("a", "m") == "a [m]"


def test_vector_components_use_axis_colors(panel):
    view = panel.add_plot("time", ["drone.x", "drone.y", "drone.z", "err"])
    colors = [view.curves[n].color for n in ("drone.x", "drone.y", "drone.z", "err")]
    assert colors[:3] == [tokens.AXIS_COLORS[a] for a in "xyz"]
    assert colors[3] in tokens.OKABE_ITO


def test_xy_scatter_and_histogram(panel):
    """DA-04: XY (trajectory top view), scatter, and histogram plots."""
    xy = panel.add_plot("xy", ["drone.x", "drone.y"])
    xy.refresh()
    x, y = xy.curves["drone.y"].getData()
    np.testing.assert_allclose(x, panel.history.signal("drone.x"))
    np.testing.assert_allclose(y, panel.history.signal("drone.y"))
    assert xy.plot.getAxis("bottom").labelText == "drone.x [m]"
    assert xy.plot.vb.state["aspectLocked"]  # same units: a true top view
    xy.set_cursor(10)
    assert xy.cursor_dot.isVisible()
    np.testing.assert_allclose(xy.cursor_dot.getData()[0], [panel.history.signal("drone.x")[10]])

    sc = panel.add_plot("scatter", ["drone.x", "err"])
    sc.refresh()
    assert sc.curves["err"].opts["symbol"] == "o"
    assert sc.curves["err"].opts["pen"].style() == Qt.PenStyle.NoPen  # points, no lines

    hist = panel.add_plot("histogram", ["err"])
    hist.refresh()
    edges, counts = hist.curves["err"].getData()[0], hist.curves["err"].yData
    assert counts.sum() == panel.history.n
    assert hist.plot.getAxis("left").labelText == "Count"
    assert len(edges) or len(counts)


def test_incomplete_xy_shows_its_hint(panel):
    xy = panel.add_plot("xy", ["drone.x"])
    assert not xy.hint.isHidden() and not xy.curves
    xy.add_signals(["drone.y"])
    assert xy.hint.isHidden()


def test_hover_reads_values_and_emits_time(panel, qapp):
    """§7.6 crosshair readout; DA-02 hover time."""
    view = panel.add_plot("time", ["drone.z", "err"])
    view.refresh()
    view.plot.vb.setXRange(0, 10, padding=0)
    qapp.processEvents()
    got = []
    panel.hover_time.connect(got.append)
    scene_pos = view.plot.vb.mapViewToScene(QPointF(2.0, 0.0))
    view._mouse_moved(scene_pos)
    assert got and got[-1] == pytest.approx(2.0, abs=0.02)
    assert view.readout.isVisible() and "drone.z:" in view.readout.toPlainText()
    view.widget.left.emit()
    assert got[-1] is None and not view.readout.isVisible()


def test_selection_bolds_the_entity_traces(panel):
    view = panel.add_plot("time", ["drone.z", "err"])
    sel = []
    panel.selected.connect(sel.append)
    view._trace_clicked("drone.z")
    assert sel == ["drone"]
    panel.set_selection("drone")
    assert view.curves["drone.z"].opts["pen"].widthF() == tokens.PLOT_SELECTED_WIDTH
    assert view.curves["err"].opts["pen"].widthF() == tokens.PLOT_LINE_WIDTH


def test_close_plot_shows_the_empty_state(panel):
    view = panel.add_plot("time", ["err"])
    view.closed.emit()
    assert not panel.plots and panel.stack.currentWidget() is panel.empty


def test_exports_use_the_light_theme(panel, tmp_path, qapp):
    """DA-07 + DS-09: PNG/SVG exports are light-themed; the screen stays dark."""
    view = panel.add_plot("time", ["drone.z"])
    view.refresh()
    qapp.processEvents()
    png = view.export_image(tmp_path / "plot.png")
    img = QImage(str(png))
    assert img.width() >= 2 * view.plot.width() - 2  # 2x for reports
    corner = QColor(img.pixel(2, 2)).name().upper()
    assert corner == tokens.color("light", "bg.panel")
    svg = view.export_image(tmp_path / "plot.svg").read_text(encoding="utf-8")
    assert "<svg" in svg
    assert view.theme == "dark"
    assert view.widget.backgroundBrush().color().name().upper() == tokens.color("dark", "bg.panel")


def test_ten_signals_of_100k_samples_redraw_at_30_fps(qapp):
    """DA-01: 10 signals x 100k samples update at >= 30 FPS (median redraw < 33 ms)."""
    names = tuple(f"s{k}" for k in range(10))
    h = make_history(n=100_000, signals=names, dt=0.001)
    p = PlotPanel(lambda: None)
    p.resize(1000, 300)
    p.set_history(h)
    view = p.add_plot("time", list(names))
    p.show()
    qapp.processEvents()
    times = []
    rows = np.column_stack(
        [np.arange(100_000, 100_100)] + [np.zeros(100)] * 10 + [np.zeros(100)] * 3
    )
    for k in range(15):
        rows[:, 0] = np.arange(100_000 + 100 * k, 100_100 + 100 * k)
        h.append(rows.copy())  # live data keeps arriving
        start = time.perf_counter()
        p.refresh()
        view.set_cursor(h.n - 1)
        view.widget.viewport().repaint()  # paint now, not later
        times.append(time.perf_counter() - start)
    assert h.n > 100_000
    # 30 FPS on the development machine (median about 25 ms, D-050). Shared CI runners are
    # several times slower at software rendering, so CI only guards against a regression.
    budget = 1 / 30 if not os.environ.get("CI") else 0.15
    assert float(np.median(times)) < budget, times
    p.close()


def test_panel_toolbar_adds_plots(panel):
    for kind, button in panel.add_buttons.items():
        button.click()
        assert panel.plots[-1].kind == kind
    assert len(panel.plots) == 4
    got = []
    panel.export_data.connect(lambda: got.append(1))
    from qtpy.QtWidgets import QToolButton

    data = [b for b in panel.findChildren(QToolButton) if b.text() == "Export data…"]
    data[0].click()
    assert got == [1]
