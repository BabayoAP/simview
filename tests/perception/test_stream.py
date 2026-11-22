"""VW-02: stream semantics."""

import numpy as np
import pytest

import simview as sv
from simview.perception import CameraRig, Pipeline, Stream

from .helpers import box_scene, run_ticks


def test_latest_and_sequence_numbers():
    s = Stream("a")
    assert s.latest() is None and s.seq == -1 and np.isnan(s.t)
    assert s.push("x", 0.0) == 0
    assert s.push("y", 0.1) == 1
    assert s.latest() == "y" and s.t == 0.1 and s.seq == 1


def test_readers_get_every_item_since_their_last_read():
    s = Stream("a")
    r1, r2 = s.reader(), s.reader()
    s.push(1, 0.0)
    s.push(2, 0.1)
    assert r1.since_last() == [1, 2]
    assert r1.since_last() == []
    s.push(3, 0.2)
    assert r1.since_last() == [3]
    assert r2.since_last() == [1, 2, 3]  # independent positions
    assert r1.dropped == r2.dropped == 0


def test_slow_reader_counts_drops():
    s = Stream("a", maxlen=3)
    r = s.reader()
    for i in range(10):
        s.push(i, i * 0.1)
    assert r.pending == 10
    assert r.since_last() == [7, 8, 9]
    assert r.dropped == 7
    fast = s.reader()
    s.push(10, 1.0)
    s.push(11, 1.1)
    assert fast.latest() == 11  # a UI that shows only the latest skips the rest
    assert fast.dropped == 11


def test_stream_rejects_empty_buffer():
    with pytest.raises(ValueError):
        Stream("a", maxlen=0)


def test_controllers_read_streams_and_nothing_is_lost_in_a_run():
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=4, width=16, height=12, rate=10))
    seen: list[int] = []
    readers = {}

    @scene.controller(rate=10)
    def ctrl(t, state, ctx):
        s = ctx.streams["ego.cam0"]
        r = readers.setdefault("r", s.reader())
        seen.extend(f.seq for f in r.since_last())
        assert ctx.streams["ego.cloud"].latest() is not None

    scene.add_pipeline(Pipeline([sv.perception.BackProject()], inputs=rig, name="ego"))
    run_ticks(scene, 100)  # 1 s: frames at t = 0, 0.1, ..., 1.0
    assert seen == list(range(10))  # every frame up to t = 0.9, read by the t = 1.0 call
    assert readers["r"].dropped == 0
    assert set(rig.streams) == {f"ego.cam{i}" for i in range(4)}


def test_reader_starts_over_after_the_stream_resets():
    s = Stream("a")
    r = s.reader()
    for i in range(5):
        s.push(i, i * 0.1)
    assert r.since_last() == [0, 1, 2, 3, 4]
    s.reset()  # e.g. a dataset replayed again
    s.push("again", 0.0)
    assert r.pending == 1
    assert r.since_last() == ["again"]  # not lost behind the old cursor
    assert r.dropped == 0
    s.reset()
    s.push("x", 0.0)
    s.push("y", 0.1)
    assert r.latest() == "y" and r.dropped == 1


def test_default_inputs_are_camera_streams_not_other_pipelines():
    scene, ego = box_scene()
    ego.attach(CameraRig.surround(n=2, width=16, height=12))
    seen: dict[str, list[type]] = {"a": [], "b": []}

    def stage(key):
        def f(items):
            seen[key] += [type(i) for i in items]
            return items[0].t

        f.__name__ = f"out_{key}"
        return f

    scene.add_pipeline(Pipeline([stage("a")], name="a"))
    scene.add_pipeline(Pipeline([stage("b")], name="b"))  # must not read "a.out_a"
    run_ticks(scene, 10)
    assert seen["a"] and seen["b"]
    assert set(seen["a"]) == set(seen["b"]) == {sv.perception.Frame}
