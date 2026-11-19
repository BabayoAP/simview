"""VP-05, DA-01: per-tick history rows from the sim, held by the UI's `History` (Qt-free)."""

import numpy as np
import pytest

import simview as sv
from simview.core.entity import Entity
from simview.core.scheduler import Sim
from simview.ipc.protocol import describe
from simview.ipc.record import record_row, row_layout
from simview.ipc.shm import Layout
from simview.ui.timeline.history import History


class Cart(Entity):
    state_names = ("x", "v")
    state_units = {"x": "m", "v": "m/s"}

    def derivative(self, t, x, u):
        return np.array([x[1], 1.0])


def cart_scene():
    scene = sv.Scene(dt=0.01)
    scene.add_entity(Cart([0.0, 0.0], name="cart"))
    scene.log("energy", lambda sim: 0.5 * sim.scene["cart"]["v"] ** 2, unit="J")
    return scene


def layout_of(scene):
    desc = describe(scene)
    markers = [e.name for e in desc.entities if e.has_marker]
    n_bodies = scene.world.model.nbody if scene.world is not None else 0
    state = Layout.build(
        [e.name for e in desc.entities],
        [len(scene[e.name].x) for e in desc.entities],
        markers,
        n_bodies,
    )
    return row_layout(scene, state)


def recorded(scene, ticks):
    lay = layout_of(scene)
    sim = Sim(scene)
    rows = [record_row(scene, sim, lay)]
    for _ in range(ticks):
        sim.step()
        rows.append(record_row(scene, sim, lay))
    return lay, np.vstack(rows)


def test_row_layout_matches_the_parquet_log_columns_with_units():
    scene = cart_scene()
    lay = layout_of(scene)
    assert lay.signals == ("cart.x", "cart.v", "energy")
    assert lay.units == ("m", "m/s", "J")
    assert lay.state.marker_entities == ("cart",)  # has an x state
    assert lay.width == 1 + 3 + 3  # tick, signals, marker


def test_robot_and_body_units():
    scene = sv.Scene(dt=0.002)
    scene.add_ground()
    scene.add_robot("ur5")
    scene.add_box("cube", size=(0.1, 0.1, 0.1), pos=(0.5, 0, 0.05), mass=0.1)
    lay = layout_of(scene)
    units = dict(zip(lay.signals, lay.units, strict=True))
    assert units["cube.z"] == "m" and units["cube.vx"] == "m/s" and units["cube.wz"] == "rad/s"
    assert units["cube.qw"] == ""
    joint = next(s for s in lay.signals if s.startswith("ur5.") and s.endswith(".q"))
    assert units[joint] == "rad" and units[joint[:-1] + "v"] == "rad/s"
    _, rows = recorded(scene, 3)
    assert rows.shape == (4, lay.width)
    h = History(lay, 0.002)
    h.append(rows)
    frame = h.frame(3)
    assert frame.bodies.shape == (scene.world.model.nbody, 7)
    np.testing.assert_allclose(frame.states["cube"], h.frame(3).states["cube"])


def test_history_frames_signals_and_time():
    scene = cart_scene()
    lay, rows = recorded(scene, 100)
    h = History(lay, 0.01)
    h.append(rows[:40])
    h.append(rows[40:])
    assert h.n == 101 and h.version == 2
    np.testing.assert_allclose(h.t, np.arange(101) * 0.01)
    # v' = 1, so v(t) = t; energy is logged alongside
    np.testing.assert_allclose(h.signal("cart.v"), h.t, atol=1e-12)
    np.testing.assert_allclose(h.signal("energy"), 0.5 * h.t**2, atol=1e-12)
    f = h.frame(50)
    assert f.tick == 50 and f.t == pytest.approx(0.5)
    np.testing.assert_allclose(f.states["cart"], rows[50, 1:3])
    np.testing.assert_allclose(f.markers["cart"], [rows[50, 1], 0, 0])
    assert h.index_at(0.504) == 50 and h.index_at(-3) == 0 and h.index_at(99) == 100


def test_rows_from_a_tick_on_are_replaced():
    """A re-recorded tick (a dragged body) or a reset replaces what the history held."""
    scene = cart_scene()
    lay, rows = recorded(scene, 10)
    h = History(lay, 0.01)
    h.append(rows)
    redo = rows[5:6].copy()
    redo[0, 1] = 42.0
    h.append(redo)
    assert h.n == 6 and h.signal("cart.x")[-1] == 42.0
    h.append(rows[:3])  # the scene was reset
    assert h.n == 3


def test_history_drops_its_oldest_quarter_when_full():
    scene = cart_scene()
    lay, rows = recorded(scene, 999)
    h = History(lay, 0.01, max_bytes=8 * lay.width * 400)
    h.append(rows)
    assert h.n <= 400 and h.ticks[-1] == 999
    assert np.all(np.diff(h.ticks) == 1)


def test_trails_from_history():
    scene = cart_scene()
    lay, rows = recorded(scene, 500)
    h = History(lay, 0.01)
    h.append(rows)
    trail = h.trails(300, {"cart": 1.0})["cart"]
    np.testing.assert_allclose(trail[-1], h.frame(300).markers["cart"])
    np.testing.assert_allclose(trail[0, 0], h.signal("cart.x")[200])  # 1 s back
    assert h.trails(300, {}) == {}


def test_draws_follow_the_timeline():
    scene = cart_scene()
    lay, rows = recorded(scene, 10)
    h = History(lay, 0.01)
    h.append(rows)
    h.add_draws(2, [("point", ((0, 0, 0),), "accent", 8, "")])
    h.add_draws(6, [])
    assert h.draws_at(1) == [] and len(h.draws_at(2)) == 1 and len(h.draws_at(5)) == 1
    assert h.draws_at(9) == []
    h.add_draws(4, [("point", ((1, 0, 0),), "accent", 8, "")])  # re-sent: later sets go
    assert len(h.draws_at(9)) == 1


def test_table_has_the_log_columns():
    scene = cart_scene()
    lay, rows = recorded(scene, 10)
    h = History(lay, 0.01)
    h.append(rows)
    table = h.table({"scene": "cart.py"})
    assert table.column_names == ["t", "tick", "cart.x", "cart.v", "energy"]
    assert table.num_rows == 11
    assert b"cart.py" in table.schema.metadata[b"simview"]
