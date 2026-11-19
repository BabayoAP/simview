"""VP-05: the timeline's playback: live, parked, stepping, scrubbing, and replay (D-048)."""

import numpy as np

from simview.ipc.record import RowLayout
from simview.ipc.shm import Layout
from simview.ui.timeline.history import History
from simview.ui.timeline.playback import REPLAY_MAX_SPEED, Playback


class FakeSim:
    def __init__(self):
        self.calls = []

    def play(self):
        self.calls.append("play")

    def pause(self):
        self.calls.append("pause")

    def step(self, n=1):
        self.calls.append("step")


def history(n=101, dt=0.01):
    lay = RowLayout(("a",), ("",), Layout.build([], [], [], 0))
    h = History(lay, dt)
    h.append(np.column_stack([np.arange(n), np.arange(n) * 2.0]))
    return h


def make():
    sim = FakeSim()
    pb = Playback(sim)
    pb.reset(history())
    return sim, pb


def test_live_play_pause_and_step_drive_the_sim():
    sim, pb = make()
    assert pb.live and pb.index == 100 and pb.shown is None
    pb.play()
    assert pb.running and sim.calls == ["play"]
    pb.pause()
    pb.step_forward()
    assert sim.calls == ["play", "pause", "step"] and pb.live


def test_step_back_parks_and_pauses():
    sim, pb = make()
    pb.play()
    pb.step_back()
    assert not pb.running and sim.calls == ["play", "pause"]
    assert pb.cursor == 99 and pb.shown == 99
    pb.step_back()
    assert pb.index == 98
    pb.step_forward()
    pb.step_forward()
    assert pb.live  # stepped onto the newest row: live again
    assert sim.calls == ["play", "pause"]  # stepping through history doesn't touch the sim


def test_seek_clamps_and_the_last_row_is_live():
    _, pb = make()
    pb.seek(-5)
    assert pb.cursor == 0
    pb.seek(40)
    assert pb.index == 40
    pb.seek(10_000)
    assert pb.live
    pb.to_start()
    assert pb.index == 0
    pb.to_live()
    assert pb.live


def test_replay_runs_at_speed_then_hands_over_to_the_live_sim():
    sim, pb = make()
    pb.seek(0)
    pb.play()
    assert pb.replaying and sim.calls == []
    pb.advance(0.25, 1.0)  # 0.25 s at 1x: row 25 (dt = 0.01)
    assert pb.index == 25
    pb.advance(0.1, 2.0)  # 0.2 s more at 2x
    assert pb.index == 45
    pb.advance(10.0, 1.0)
    assert pb.live and pb.sim_running and sim.calls == ["play"]


def test_replay_at_max_speed_and_pause():
    sim, pb = make()
    pb.seek(0)
    pb.play()
    pb.advance(0.05, 0.0)
    assert pb.index == round(0.05 * REPLAY_MAX_SPEED / 0.01)
    pb.toggle()
    assert not pb.running
    i = pb.index
    pb.advance(1.0, 1.0)
    assert pb.index == i and sim.calls == []


def test_preview_shows_a_row_without_moving_the_cursor():
    _, pb = make()
    pb.seek(30)
    pb.preview = 70
    assert pb.shown == 70 and pb.index == 30
    pb.preview = None
    assert pb.shown == 30
