"""SE-02 / NF-04: the shared-memory state buffer and its seqlock."""

import numpy as np

from simview.ipc.shm import SEQ, Layout, StateBuffer


def make(create=True, name=None):
    layout = Layout.build(["arm", "ball"], [12, 2], ["ball"], n_bodies=3)
    return StateBuffer(layout, name=name, create=create)


def test_layout_offsets_do_not_overlap():
    layout = Layout.build(["arm", "ball"], [12, 2], ["ball"], n_bodies=3)
    o = layout.offsets
    assert o["x:ball"] == o["x:arm"] + 12
    assert o["p:ball"] == o["x:ball"] + 2
    assert o["bodies"] == o["p:ball"] + 3
    assert layout.size == o["bodies"] + 21


def test_round_trip_between_two_handles():
    w = make()
    r = make(create=False, name=w.name)
    try:
        assert r.read() is None  # nothing written yet
        states = {"arm": np.arange(12.0), "ball": np.array([1.0, -2.0])}
        bodies = np.arange(21.0).reshape(3, 7)
        w.write(5, 0.005, 1.0, True, 123.0, 2.0, states, {"ball": np.array([0, 0, 1.0])}, bodies)
        f = r.read()
        assert f.tick == 5 and f.t == 0.005 and f.running and f.speed == 2.0 and f.wall == 123.0
        np.testing.assert_array_equal(f.states["arm"], states["arm"])
        np.testing.assert_array_equal(f.markers["ball"], [0, 0, 1.0])
        np.testing.assert_array_equal(f.bodies, bodies)
    finally:
        r.close()
        w.close(unlink=True)


def test_reader_skips_a_frame_being_written():
    w = make()
    try:
        w.write(
            1,
            0.0,
            0.0,
            False,
            0.0,
            1.0,
            {"arm": np.zeros(12), "ball": np.zeros(2)},
            {"ball": np.zeros(3)},
            np.zeros((3, 7)),
        )
        w.arr[SEQ] += 1  # simulate the writer mid-frame
        assert w.read(retries=5) is None
        w.arr[SEQ] += 1
        assert w.read().tick == 1
    finally:
        w.close(unlink=True)
