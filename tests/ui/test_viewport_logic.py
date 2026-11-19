"""VP-01..VP-04, VP-07, DS-05 viewport logic that needs no OpenGL: geometry, matrices,
trails, draws, the ground grid, and camera navigation."""

import numpy as np
import pytest

from simview.ipc.protocol import Description, Geom
from simview.ui.theme import tokens
from simview.ui.viewport import model
from simview.ui.viewport import navigation as nav

Q_Z90 = np.array([np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)])


def geom(kind, size, pos=(0, 0, 0), quat=(1, 0, 0, 0), body=0, **kw):
    return Geom(body, kind, size, pos, quat, (1, 0, 0, 1), **kw)


# -- geometry (VP-01) -------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "size", "extent"),
    [
        ("box", (0.1, 0.2, 0.3), (0.2, 0.4, 0.6)),
        ("sphere", (0.5, 0, 0), (1.0, 1.0, 1.0)),
        ("cylinder", (0.1, 0.4, 0), (0.2, 0.2, 0.8)),
        ("capsule", (0.1, 0.4, 0), (0.2, 0.2, 1.0)),
        ("ellipsoid", (0.1, 0.2, 0.3), (0.2, 0.4, 0.6)),
    ],
)
def test_primitives_have_mujoco_sizes(kind, size, extent):
    b = model.geom_mesh(geom(kind, size)).bounds
    got = (b[1] - b[0], b[3] - b[2], b[5] - b[4])
    np.testing.assert_allclose(got, extent, rtol=0.02)


def test_mesh_geom():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    f = np.array([[0, 1, 2]], dtype=np.int32)
    mesh = model.geom_mesh(geom("mesh", (0, 0, 0), vertices=v, faces=f))
    assert mesh.n_points == 3 and mesh.n_cells == 1
    with pytest.raises(ValueError, match="cannot draw"):
        model.geom_mesh(geom("hfield", (1, 1, 1)))


def test_world_matrix_is_body_times_local():
    desc = Description(dt=1e-3, geoms=[geom("box", (1, 1, 1), pos=(1, 0, 0), body=1)])
    bodies = np.array([[0, 0, 0, 1, 0, 0, 0], [0, 0, 2, *Q_Z90]], dtype=float)
    (m,) = model.geom_world_matrices(desc, bodies)
    np.testing.assert_allclose(m[:3, 3], [0, 1, 2], atol=1e-12)  # (1,0,0) turned 90 deg, raised 2


def test_pose_round_trip():
    q = np.array([0.9, 0.1, -0.3, 0.2])
    q /= np.linalg.norm(q)
    pos, quat = model.matrix_to_pose(model.pose_matrix(np.array([1.0, 2.0, 3.0]), q))
    np.testing.assert_allclose(pos, [1, 2, 3])
    np.testing.assert_allclose(quat if quat[0] * q[0] > 0 else -quat, q, atol=1e-12)


def test_ground_grid_fades_and_uses_theme_colors():
    for theme in ("dark", "light"):
        grid = model.ground_grid(theme)
        rgba = grid.point_data["rgba"]
        r = np.hypot(grid.points[:, 0], grid.points[:, 1])
        assert rgba[r < 1.0, 3].min() == 255  # near the origin: opaque
        assert rgba[r >= tokens.GRID_EXTENT * 0.999, 3].max() == 0  # at the edge: gone
        major = model.hex_rgb(tokens.color(theme, "viewport.grid_major"))
        assert any((c[:3] == major).all() for c in rgba[:200])


# -- trails (VP-04) ------------------------------------------------------------------------------
def test_trail_keeps_its_length_in_seconds_and_resets():
    trail = model.Trail(seconds=1.0)
    for k in range(300):
        trail.add(k * 0.01, np.array([k, 0, 0]))
    ts = [t for t, _ in trail.points]
    assert 1.0 - 0.01 - 1e-9 <= ts[-1] - ts[0] <= 1.0  # within one 10 ms sample
    assert trail.polyline().n_points == len(ts)
    trail.add(0.5, np.zeros(3))  # time went backwards: a reset or a scrub
    assert len(trail.points) == 1 and trail.polyline() is None


# -- debug draws (VP-07) -------------------------------------------------------------------------
def test_draw_geometry_groups_and_resolves_colors():
    draws = [
        ("line", ((0, 0, 0), (1, 0, 0)), "accent", 2.0, ""),
        ("arrow", ((0, 0, 0), (0, 1, 0)), "red", 2.0, ""),
        ("point", ((1, 1, 1),), "accent", 8.0, ""),
        ("text", ((0, 0, 1),), "text.primary", 11.0, "hi"),
        ("frame", ((0, 0, 0), (0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)), "frame", 0.1, ""),
    ]
    g = model.draw_geometry(draws, "dark")
    assert len(g.lines) == 1 + 3 and len(g.arrows) == 1 and len(g.points) == 1
    assert g.lines[0][2] == tokens.color("dark", "accent")
    assert g.arrows[0][2] == "red"
    assert g.labels[0][1] == "hi"
    assert [ln[2] for ln in g.lines[1:]] == [tokens.AXIS_COLORS[a] for a in "xyz"]


# -- navigation (VP-02, VP-03, DS-05) ------------------------------------------------------------
def cam(**kw):
    return nav.Camera(position=np.array([5.0, -5.0, 5.0]), focal=np.zeros(3), **kw)


def test_orbit_keeps_distance_to_pivot_and_pivot_on_screen():
    c = cam()
    pivot = np.array([1.0, 0.5, 0.0])
    before = nav.project(c, pivot, 800, 600)
    d0 = np.linalg.norm(c.position - pivot)
    c2 = nav.orbit(c, pivot, 40, -25, tokens.ORBIT_DEG_PER_PX)
    assert np.linalg.norm(c2.position - pivot) == pytest.approx(d0)
    np.testing.assert_allclose(nav.project(c2, pivot, 800, 600), before, atol=1e-6)


@pytest.mark.parametrize("dy", [100, -100])
def test_orbit_stops_at_the_poles_without_flipping(dy):
    c = cam()
    right0 = c.right
    for _ in range(50):
        c = nav.orbit(c, np.zeros(3), 0, dy, tokens.ORBIT_DEG_PER_PX)  # keep tilting
        tilt = np.arccos(np.clip(np.dot(c.forward, -nav.UP), -1, 1))
        assert nav.MIN_POLE_ANGLE - 1e-9 <= tilt <= np.pi - nav.MIN_POLE_ANGLE + 1e-9
        np.testing.assert_allclose(c.right, right0, atol=1e-9)  # the horizon never reverses


def test_pan_moves_the_scene_with_the_mouse():
    c = cam()
    p = np.zeros(3)
    before = nav.project(c, p, 800, 600)
    after = nav.project(nav.pan(c, 30, 10, 600), p, 800, 600)
    np.testing.assert_allclose(after - before, [30, 10], atol=1e-6)


@pytest.mark.parametrize("parallel", [False, True])
def test_zoom_to_cursor_keeps_the_point_under_the_cursor(parallel):
    c = cam(parallel=parallel, parallel_scale=4.0)
    point = np.array([1.0, 1.0, 0.0])
    before = nav.project(c, point, 800, 600)
    c2 = nav.zoom_to(c, point, 2, tokens.ZOOM_STEP)
    np.testing.assert_allclose(nav.project(c2, point, 800, 600), before, atol=1e-6)
    if parallel:
        assert c2.parallel_scale < c.parallel_scale
    else:
        assert np.linalg.norm(c2.position - point) < np.linalg.norm(c.position - point)


def test_presets_frame_and_2d():
    c = cam()
    for name, (direction, _) in nav.PRESETS.items():
        v = nav.preset(name, np.zeros(3), 1.0, c)
        np.testing.assert_allclose(-v.forward, direction, atol=1e-12)
    top = nav.top_2d(np.zeros(3), 2.0, c)
    assert top.parallel and top.parallel_scale == 2.0
    np.testing.assert_allclose(top.forward, [0, 0, -1])
    framed = nav.frame(np.array([1.0, 1.0, 1.0]), 0.5, c)
    np.testing.assert_allclose(framed.forward, c.forward)
    np.testing.assert_allclose(framed.focal, [1, 1, 1])


def test_fly_keys():
    c = cam()
    np.testing.assert_allclose(nav.fly(c, "w", 1.0).position - c.position, c.forward)
    np.testing.assert_allclose(nav.fly(c, "e", 1.0).position - c.position, nav.UP)
    assert nav.fly(c, "x", 1.0) is c
