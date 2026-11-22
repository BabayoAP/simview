"""VW-06: log-odds occupancy updates, clamping, decay, rolling, and queries."""

import numpy as np
import pytest

from simview.perception import OccupancyGrid, PointCloud


def cloud(points, origin=(0.0, 0.0, 1.0), t=0.0, ego=None) -> PointCloud:
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    return PointCloud(
        t=t,
        points=pts,
        colors=np.zeros((len(pts), 3), np.uint8),
        origins=np.array([origin], dtype=float),
        origin_index=np.zeros(len(pts), np.int32),
        ego=ego,
    )


def grid(**kw) -> OccupancyGrid:
    kw.setdefault("res", 0.5)
    kw.setdefault("extent", 20.0)
    kw.setdefault("height", (0.0, 3.0))
    return OccupancyGrid(**kw)


def test_ray_frees_space_and_marks_the_hit():
    g = grid()
    g(cloud([5.1, 0.1, 1.1], origin=(0.1, 0.1, 1.1)))
    assert g.occupied([5.1, 0.1, 1.1])
    assert g.logodds.reshape(-1)[g._flat(np.array([[5.1, 0.1, 1.1]]))[0]][0] == np.float32(0.85)
    # every voxel between the camera and the hit got l_free once
    for x in np.arange(0.25, 4.9, 0.5):
        ijk = np.floor((np.array([x, 0.1, 1.1]) - g.origin) / g.res).astype(int)
        assert g.logodds[tuple(ijk)] == np.float32(-0.4), x
    assert not g.occupied([3.0, 0.1, 1.1])
    assert g.seen.sum() == 11  # 10 free + 1 hit
    # a voxel off the ray is unknown
    assert g.logodds[tuple(np.floor((np.array([3.0, 5.0, 1.1]) - g.origin) / 0.5).astype(int))] == 0


def test_repeated_updates_clamp():
    g = grid(clamp=(-1.0, 2.0))
    c = cloud([5.0, 0.0, 1.0])
    for _ in range(10):
        g(c)
    assert g.logodds.max() == np.float32(2.0)
    assert g.logodds.min() == np.float32(-1.0)


def test_decay_clears_a_moved_object():
    g = grid(decay=0.5)
    g(cloud([5.0, 0.0, 1.0]))
    assert g.occupied([5.0, 0.0, 1.0])
    for _ in range(30):
        g(cloud([-5.0, 0.0, 1.0]))  # looking elsewhere: the old hit fades
    assert not g.occupied([5.0, 0.0, 1.0])
    assert g.occupied([-5.0, 0.0, 1.0])


def test_floor_hits_clear_but_do_not_occupy():
    g = grid(floor=0.1)
    g(cloud([4.0, 0.0, 0.02]))
    assert not g.occupied([4.0, 0.0, 0.02])
    assert g.seen.any()


def test_queries():
    g = grid()
    g(cloud([[5.0, 0.0, 1.0], [0.0, -3.0, 1.0]]))
    occ = g.occupied(np.array([[5.0, 0.0, 1.0], [5.0, 3.0, 1.0], [100.0, 0.0, 1.0]]))
    assert occ.tolist() == [True, False, False]
    centres = g.occupied_centers()
    assert centres.shape == (2, 3)
    assert g.nearest_obstacle([0.0, 0.0, 1.0]) == pytest.approx(
        np.linalg.norm(g.closest_occupied([0.0, 0.0, 1.0]) - [0.0, 0.0, 1.0])
    )
    assert g.nearest_obstacle([0.0, 0.0]) == pytest.approx(np.hypot(0.25, 2.75))  # horizontal
    assert g.nearest_obstacle([0.0, 0.0], within=1.0) == np.inf
    assert not g.is_free([0.0, 0.0, 1.0], [8.0, 0.0, 1.0])
    assert g.is_free([0.0, 0.0, 1.0], [0.0, 2.0, 1.0])
    assert g.is_free([0.0, 0.0, 1.0], [-8.0, 5.0, 1.0])  # unknown space counts as free
    p = g.probability
    assert p.max() > 0.5 > p.min() and (p == 0.5).any()


def test_world_fixed_grid_bounds_and_snapshot():
    g = grid(center=(10.0, 0.0))
    lo, hi = g.bounds
    np.testing.assert_allclose(lo, [0.0, -10.0, 0.0])
    np.testing.assert_allclose(hi, [20.0, 10.0, 3.0])
    g(cloud([15.0, 0.0, 1.0], origin=(10.0, 0.0, 1.0)))
    snap = g.copy()
    g.reset()
    assert snap.occupied([15.0, 0.0, 1.0]) and not g.occupied([15.0, 0.0, 1.0])


def test_rolling_grid_follows_the_ego_and_keeps_overlap():
    g = grid(rolling=True)
    ego = np.eye(4)
    g(cloud([3.0, 0.0, 1.0], ego=ego))
    assert g.occupied([3.0, 0.0, 1.0])
    ego2 = np.eye(4)
    ego2[:3, 3] = [4.0, 0.0, 0.0]
    g(cloud([12.0, 0.0, 1.0], origin=(4.0, 0.0, 1.0), ego=ego2))
    np.testing.assert_allclose(g.bounds[0][:2], [-6.0, -10.0])
    assert g.occupied([3.0, 0.0, 1.0])  # still inside, kept
    assert g.occupied([12.0, 0.0, 1.0])  # beyond the old grid, now inside
    ego3 = np.eye(4)
    ego3[:3, 3] = [100.0, 0.0, 0.0]
    g(cloud([101.0, 0.0, 1.0], origin=(100.0, 0.0, 1.0), ego=ego3))
    assert not g.occupied([12.0, 0.0, 1.0]) and len(g.occupied_centers()) == 1


def test_updates_are_deterministic():
    rng = np.random.default_rng(0)
    pts = rng.uniform([-9, -9, 0], [9, 9, 3], size=(5000, 3))
    a, b = grid(res=0.2), grid(res=0.2)
    a(cloud(pts))
    b(cloud(pts))
    assert a.logodds.tobytes() == b.logodds.tobytes()


def test_argument_checks():
    with pytest.raises(ValueError):
        OccupancyGrid(res=0)
    with pytest.raises(ValueError):
        OccupancyGrid(height=(2, 1))
    with pytest.raises(ValueError):
        OccupancyGrid(l_occ=-1)
    with pytest.raises(ValueError):
        OccupancyGrid(decay=1.0)
    assert OccupancyGrid(res=0.2, extent=(10, 4)).shape == (50, 20, 20)
