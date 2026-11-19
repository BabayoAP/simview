"""VP-05, DA-01..DA-03, DA-07, DS-06 through the main window with the real sim process.

Covers the M5 done-when: scrubbing moves the viewport and the plot cursor together within
100 ms. The 3D view is the no-OpenGL stand-in here; `test_viewport_gl.py` times the real one.
"""

import time

import numpy as np
import pyarrow.parquet as pq
import pytest

from simview.ui.main_window import MainWindow
from tests.ui.test_scene_session import DRAG, loaded, pump


@pytest.fixture
def window(qapp, settings):
    w = MainWindow(settings)
    w.show()
    yield w
    w.close_scene()
    w.close()


def recorded(qapp, w, ticks=300):
    """Load the UC-3 scene, run flat out until `ticks` rows are recorded, then pause."""
    w.load_scene(DRAG)
    pump(qapp, lambda: loaded(w) and w.history is not None and w.history.n >= 1)
    w.speed_box.setCurrentIndex(w.speed_box.findText("Max"))
    w.run()
    pump(qapp, lambda: w.history.n >= ticks)
    w.pause()
    n = w.history.n
    pump(qapp, lambda: w.client.frame() is not None and not w.client.frame().running)
    pump(qapp, lambda: w.history.n == w.client.frame().tick + 1)  # the last rows arrived
    assert w.history.n >= n
    return w.history


def test_rows_stream_into_the_history_and_signal_tree(qapp, window):
    h = recorded(qapp, window)
    assert np.all(np.diff(h.ticks) == 1) and h.ticks[0] == 0
    tree = window.signal_tree
    assert {"ur5", "Channels"} <= set(tree.groups)
    assert tree.leaves["ur5.shoulder_pan_joint.q"].text(1) == "rad"
    assert tree.leaves["tool_error"].text(1) == "m"
    q = h.signal("ur5.shoulder_pan_joint.q")
    assert q[-1] == pytest.approx(window.client.frame().states["ur5"][0])
    assert window.timeline.slider.maximum() == h.n - 1


def test_scrub_moves_viewport_and_plot_cursor_within_100_ms(qapp, window):
    """M5 done-when."""
    h = recorded(qapp, window)
    plot = window.plots.add_plot("time", ["ur5.shoulder_pan_joint.q", "tool_error"])
    window.plots.refresh()
    times = []
    for i in (h.n // 4, h.n // 2, 10, h.n - 5):
        start = time.perf_counter()
        window.timeline.slider.setValue(i)  # a user drag on the scrub slider
        times.append(time.perf_counter() - start)
        assert window.sim_view.frame.tick == int(h.ticks[i])
        np.testing.assert_allclose(window.sim_view.frame.states["ur5"], h.frame(i).states["ur5"])
        assert plot.cursor.value() == pytest.approx(h.time_of(i))
        assert window.timeline.readout.text().startswith(f"t = {h.time_of(i):.3f} s")
    assert max(times) < 0.100, times
    assert not window.running and not window.playback.live


def test_step_back_and_forward_through_history(qapp, window):
    """VP-05: ',' steps back one tick (recorded), '.' forward; at the end it steps the sim."""
    h = recorded(qapp, window)
    last = h.n - 1
    window.actions_.get("sim.step_back").trigger()
    assert window.sim_view.frame.tick == last - 1
    window.step_back()
    assert window.sim_view.frame.tick == last - 2
    window.step()
    window.step()
    assert window.playback.live
    window.step()  # live: the sim takes one tick
    pump(qapp, lambda: h.n == last + 2)
    window.to_start()
    assert window.sim_view.frame.tick == 0 and window.inspector is not None


def test_replay_hands_over_to_the_live_sim(qapp, window):
    h = recorded(qapp, window, ticks=150)
    window.speed_box.setCurrentIndex(window.speed_box.findText("10×"))
    window.seek(h.n - 60)
    window.run()
    assert window.playback.replaying and window.running
    pump(qapp, lambda: window.playback.sim_running)  # ran out of recording: live again
    assert window.playback.live
    n = h.n
    pump(qapp, lambda: h.n > n + 20)  # and the sim records new rows
    window.pause()


def test_plot_hover_previews_the_viewport(qapp, window):
    """DA-02: hovering a plot moves the viewport to that time; leaving restores the cursor."""
    h = recorded(qapp, window)
    window.seek(h.n - 1 - 10)
    window.plots.hover_time.emit(h.time_of(40))
    assert window.sim_view.frame.tick == 40
    assert window.timeline.slider.value() == h.n - 11  # the cursor itself didn't move
    window.plots.hover_time.emit(None)
    assert window.sim_view.frame.tick == int(h.ticks[h.n - 11])
    window.plots.seek_time.emit(h.time_of(25))  # clicking a time plot seeks
    assert window.sim_view.frame.tick == 25


def test_plots_join_the_selection(qapp, window):
    """DS-06: trace click and signal tree selection select the entity everywhere."""
    recorded(qapp, window, ticks=50)
    plot = window.plots.add_plot("time", ["ur5.shoulder_pan_joint.q"])
    window.plots.selected.emit("ur5")
    assert window.sim_view.selection == "ur5"
    assert window.scene_tree.items["ur5"].isSelected()
    assert plot.selection == "ur5"
    window.scene_tree.selected.emit(None)
    assert plot.selection is None and not window.signal_tree.selectedItems()
    window.signal_tree.leaves["ur5.shoulder_pan_joint.v"].setSelected(True)
    assert window.sim_view.selection == "ur5" and plot.selection == "ur5"


def test_export_data_and_reset(qapp, window, tmp_path):
    """DA-07 from the window; Stop resets the recording."""
    h = recorded(qapp, window, ticks=100)
    out = window.export_data(tmp_path / "run.parquet")
    table = pq.read_table(out)
    assert table.num_rows == h.n and table.column_names[:2] == ["t", "tick"]
    assert "tool_error" in table.column_names
    window.stop()
    pump(qapp, lambda: window.history is not None and window.history.n == 1)
    assert window.playback.live
