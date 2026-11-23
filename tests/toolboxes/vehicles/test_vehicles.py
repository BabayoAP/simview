"""TB-VEH: kinematic bicycle, paths and roads, pure pursuit, Stanley, scripted NPCs."""

import numpy as np
import pytest

import simview as sv
from simview.toolboxes import vehicles as vh


def drive(car, controller, path, *, duration, dt=0.01, target=8.0):
    """Close the loop by hand (no scene), returning the |cross-track| history."""
    errs = []
    for k in range(int(round(duration / dt))):
        x, y, yaw, v = car.x
        steer = controller(x, y, yaw, v)
        car.u = np.array([vh.speed_control(v, target), steer])
        car.advance(k * dt, dt)
        errs.append(abs(path.nearest(car.x[:2]).cross_track))
    return np.array(errs)


# -- bicycle ---------------------------------------------------------------------------------
def test_bicycle_turns_on_the_kinematic_radius():
    """Constant steer at constant speed follows a circle of radius L / tan(steer)."""
    car = vh.KinematicBicycle([0, 0, 0, 5.0], wheelbase=2.5)
    steer = 0.2
    car.u = np.array([0.0, steer])
    dt, radius = 0.001, 2.5 / np.tan(steer)
    for k in range(4000):
        car.advance(k * dt, dt)
    x, y, yaw, v = car.x
    # rear axle stays on the circle centered (0, R)
    assert np.hypot(x, y - radius) == pytest.approx(radius, abs=1e-6)
    assert yaw == pytest.approx(5.0 * 4.0 / radius, rel=1e-9)
    assert v == 5.0


def test_bicycle_clips_inputs_and_speed():
    car = vh.KinematicBicycle([0, 0, 0, 0.0], max_steer=0.3, max_accel=2.0, max_speed=3.0)
    assert car.inputs(np.array([10.0, 1.0])) == (2.0, 0.3)
    assert car.inputs(np.array([])) == (0.0, 0.0)
    car.u = np.array([10.0, 0.0])
    for k in range(300):
        car.advance(k * 0.01, 0.01)
    assert car["v"] == pytest.approx(3.0)
    car.u = np.array([-10.0, 0.0])
    for k in range(300):
        car.advance(k * 0.01, 0.01)
    assert car["v"] == 0.0  # no reversing with min_speed = 0
    with pytest.raises(ValueError):
        vh.KinematicBicycle(wheelbase=0)
    with pytest.raises(ValueError):
        vh.KinematicBicycle(max_steer=2.0)


def test_bicycle_pose_and_velocity_for_sensors():
    car = vh.KinematicBicycle([1.0, 2.0, np.pi / 2, 3.0], wheelbase=2.0)
    np.testing.assert_allclose(car.velocity(), [0, 3, 0], atol=1e-12)
    np.testing.assert_allclose(car.pose()[:3, 3], [1, 2, 0])
    np.testing.assert_allclose(car.rotation() @ [1, 0, 0], [0, 1, 0], atol=1e-12)
    np.testing.assert_allclose(car.front_axle(), [1, 4], atol=1e-12)


# -- paths and roads -------------------------------------------------------------------------
def test_path_arc_length_and_nearest():
    p = vh.Path([[0, 0], [10, 0], [10, 10]])
    assert p.length == 20.0
    np.testing.assert_allclose(p.point_at(15), [10, 5])
    np.testing.assert_allclose(p.point_at(-3), [0, 0])
    np.testing.assert_allclose(p.point_at(99), [10, 10])
    assert p.heading_at(15) == pytest.approx(np.pi / 2)
    n = p.nearest([4, 2])
    assert n.s == pytest.approx(4) and n.cross_track == pytest.approx(2)  # left is +
    assert p.nearest([4, -1]).cross_track == pytest.approx(-1)
    assert p.nearest([12, 7]).cross_track == pytest.approx(-2)  # right of the north leg
    with pytest.raises(ValueError):
        vh.Path([[0, 0], [0, 0]])


def test_straight_arc_join():
    s = vh.straight((0, 0), 0.0, 10.0)
    a = vh.arc((10, 5), 5.0, -np.pi / 2, np.pi / 2, step=0.1)
    p = vh.join(s, a)
    assert p.length == pytest.approx(10 + 5 * np.pi / 2, rel=1e-3)
    np.testing.assert_allclose(p.point_at(p.length), [15, 5], atol=1e-9)
    assert p.heading_at(p.length) == pytest.approx(np.pi / 2, abs=0.02)


def test_road_lanes_and_offsets_stay_parallel():
    center = vh.join(vh.straight((0, 0), 0.0, 20.0), vh.arc((20, 30), 30.0, -np.pi / 2, 1.0))
    road = vh.Road(center, lanes=3, lane_width=3.5)
    assert road.width == 10.5
    for i, expect in enumerate((-3.5, 0.0, 3.5)):
        lane = road.lane(i)
        for s in np.linspace(0, lane.length, 25):
            assert center.nearest(lane.point_at(s)).cross_track == pytest.approx(expect, abs=0.02)
    assert road.lane_of((5, -4.0)) == 0
    assert road.lane_of((5, 0.0)) == 1
    assert road.lane_of((5, 5.0)) == 2
    assert road.lane_of((5, 6.0)) is None
    with pytest.raises(IndexError):
        road.lane(3)


def test_road_and_path_draw():
    from simview.core.draw import DrawList

    draw = DrawList()
    road = vh.Road(vh.straight((0, 0), 0.0, 12.0, step=4.0), lanes=2)
    road.draw(draw)
    kinds = {d.kind for d in draw.persistent}
    assert kinds == {"line"} and len(draw.persistent) == 3 + 3 + 2  # 2 edges + 2 dashes
    road.lane(0).draw(draw, color="state.success")
    assert len(draw.transient) == 3


# -- controllers -----------------------------------------------------------------------------
@pytest.mark.parametrize("make", ["pure_pursuit", "stanley"])
def test_trackers_converge_onto_a_curved_path(make):
    path = vh.join(
        vh.straight((0, 0), 0.0, 30.0, step=0.5),
        vh.arc((30, 25), 25.0, -np.pi / 2, np.pi / 2, step=0.5),
        vh.straight((55, 25), np.pi / 2, 60.0, step=0.5),
    )
    car = vh.KinematicBicycle([0.0, -2.0, 0.3, 5.0], wheelbase=2.7)
    if make == "pure_pursuit":
        ctrl = vh.PurePursuit(path, wheelbase=2.7)
    else:
        ctrl = vh.Stanley(path, wheelbase=2.7, k=1.5)
    errs = drive(car, ctrl, path, duration=12.0)
    assert errs[0] > 1.5  # started 2 m off
    assert errs[-300:].max() < 0.35  # tracking, including through the bend
    assert path.nearest(car.x[:2]).s > 70  # and making progress


def test_pure_pursuit_geometry():
    """Goal straight ahead: no steer. Goal on a circle through the axle: exact curvature."""
    pp = vh.PurePursuit(vh.straight((0, 0), 0.0, 50.0), wheelbase=2.0, min_lookahead=5.0, gain=0)
    assert pp(0, 0, 0, 3.0) == pytest.approx(0.0)
    np.testing.assert_allclose(pp.goal, [5, 0])
    steer = pp(0, -1.0, 0, 3.0)  # 1 m right of the path: turn left
    alpha = np.arctan2(1.0, 5.0)
    assert steer == pytest.approx(np.arctan(2 * 2.0 * np.sin(alpha) / np.hypot(5, 1)))
    assert pp.lookahead(10.0) == 5.0
    assert vh.PurePursuit(pp.path, gain=0.5, min_lookahead=2.0).lookahead(10.0) == 7.0


def test_stanley_signs_and_wrap():
    st = vh.Stanley(
        vh.straight((0, 0), 0.0, 50.0), wheelbase=0.0, k=1.0, softening=0.0, max_steer=1.2
    )
    assert st(0, -1.0, 0, 1.0) == pytest.approx(np.pi / 4)  # right of path: steer left
    assert st(0, 1.0, 0, 1.0) == pytest.approx(-np.pi / 4)
    assert st(0, 0, 0.2, 1.0) == pytest.approx(-0.2)  # heading error only
    assert vh.wrap(3 * np.pi / 2) == pytest.approx(-np.pi / 2)
    assert vh.speed_control(5.0, 8.0, kp=2.0, max_accel=4.0) == 4.0


# -- NPCs ------------------------------------------------------------------------------------
def test_npc_follows_its_speed_schedule():
    path = vh.straight((0, 0), 0.0, 100.0)
    npc = vh.ScriptedNPC(path, [(0.0, 0.0), (2.0, 10.0)], start=5.0)
    assert npc["s"] == 5.0 and npc["v"] == 0.0
    dt = 0.01
    for k in range(400):
        npc.advance(k * dt, dt)
    # 10 m during the ramp, then 10 m/s for 2 s
    assert npc["s"] == pytest.approx(5 + 10 + 20, abs=1e-9)
    assert npc["x"] == pytest.approx(35) and npc["v"] == 10.0
    np.testing.assert_allclose(npc.velocity(), [10, 0, 0])


def test_npc_stops_or_loops_at_the_end():
    path = vh.straight((0, 0), 0.0, 10.0)
    stop = vh.ScriptedNPC(path, 4.0)
    loop = vh.ScriptedNPC(path, 4.0, loop=True)
    for k in range(400):
        stop.advance(k * 0.01, 0.01)
        loop.advance(k * 0.01, 0.01)
    assert stop["s"] == 10.0 and stop["v"] == 0.0
    assert loop["s"] == pytest.approx(16 % 10)
    lane = vh.Road(vh.arc((0, 0), 20.0, 0.0, np.pi)).lane(0)
    curve = vh.ScriptedNPC(lane, lambda t: 5.0)
    curve.advance(0.0, 1.0)
    assert curve["yaw"] == pytest.approx(lane.heading_at(5.0))
    with pytest.raises(ValueError):
        vh.ScriptedNPC(path, [(1.0, 2.0), (0.5, 3.0)])


# -- in a scene ------------------------------------------------------------------------------
def test_scene_with_ego_and_npcs_runs_deterministically(tmp_path):
    def build():
        road = vh.Road(vh.straight((0, 0), 0.0, 200.0, step=2.0), lanes=2)
        scene = sv.Scene(dt=0.01)
        ego = scene.add_entity(vh.KinematicBicycle([0, -3.0, 0.0, 0.0], name="ego"))
        for i, (lane, s0, v) in enumerate([(0, 20, 6.0), (1, 10, 9.0), (1, 40, 7.0)]):
            scene.add_entity(vh.ScriptedNPC(road.lane(lane), v, start=s0, name=f"npc{i}"))
        pp = vh.PurePursuit(road.lane(0))

        @scene.controller(rate=50)
        def planner(t, state, ctx):
            if t == 0:
                road.draw(ctx.draw)
            x, y, yaw, v = state["ego"].x
            ctx.draw.point((*pp.goal, 0.0))
            return {"ego": [vh.speed_control(v, 5.0), pp(x, y, yaw, v)]}

        scene.log("cte", lambda sim: vh.cross_track_error(road.lane(0), ego.x[:2]), "m")
        return scene

    a = sv.run(build(), 10.0, out=tmp_path / "a.parquet")
    b = sv.run(build(), 10.0, out=tmp_path / "b.parquet")
    assert {"ego.x", "ego.v", "npc0.s", "npc2.x", "cte"} <= set(a.columns)
    np.testing.assert_array_equal(a["ego.x"], b["ego.x"])
    assert abs(a["cte"][-1]) < 0.05  # merged onto lane 0's center
    assert a["ego.v"][-1] == pytest.approx(5.0, abs=0.05)
    assert a["npc1.s"][-1] == pytest.approx(10 + 9.0 * 10.0, abs=0.1)


def test_sv_vehicles_is_lazy():
    assert sv.vehicles is vh
