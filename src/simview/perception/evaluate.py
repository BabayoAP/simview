"""Accuracy against ground truth (VW-10, D-129): voxel IoU, precision, recall, and the error of
the nearest-obstacle distance, comparing a grid with the scene's true MuJoCo geometry.

The truth grid marks voxels that overlap a geom (box, sphere, capsule, cylinder, ellipsoid;
meshes by their bounding box; planes and height fields are ground and skipped), tested at the
voxel centre against the shape grown by half a voxel. Scores count only voxels the grid has
observed (cameras can't see inside or behind objects), within `z_band` and `radius`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from simview.perception.occupancy import OccupancyGrid

if TYPE_CHECKING:
    from simview.core.entity import Entity
    from simview.core.scene import Scene

PLANE, HFIELD, SPHERE, CAPSULE, ELLIPSOID, CYLINDER, BOX, MESH = 0, 1, 2, 3, 4, 5, 6, 7


@dataclass
class Accuracy:
    iou: float
    precision: float
    recall: float
    nearest_error: float  # |perceived - true| nearest-obstacle distance (nan if either is inf)
    nearest_true: float
    nearest_perceived: float
    tp: int
    fp: int
    fn: int


def _inside(kind: int, size: np.ndarray, q: np.ndarray, pad: float) -> np.ndarray:
    """Which local points q (N, 3) lie strictly inside the shape grown by `pad` (a voxel
    that only touches a face doesn't overlap the solid)."""
    pad -= 1e-9
    if kind == SPHERE:
        return np.linalg.norm(q, axis=1) < size[0] + pad
    if kind == CAPSULE:
        z = np.clip(q[:, 2], -size[1], size[1])
        return np.linalg.norm(q - np.c_[np.zeros((len(q), 2)), z], axis=1) < size[0] + pad
    if kind == CYLINDER:
        return (np.linalg.norm(q[:, :2], axis=1) < size[0] + pad) & (
            np.abs(q[:, 2]) < size[1] + pad
        )
    if kind == ELLIPSOID:
        return np.sum((q / (size + pad)) ** 2, axis=1) < 1.0
    return np.all(np.abs(q) < size + pad, axis=1)  # box (and mesh bounding boxes)


def truth_grid(
    grid: OccupancyGrid, scene: Scene, exclude: Iterable[Entity | str] = ()
) -> np.ndarray:
    """Boolean (nx, ny, nz): voxels that overlap the scene's true geometry. Geoms belonging to
    `exclude`d entities (e.g. the ego vehicle) are left out."""
    out = np.zeros(grid.shape, dtype=bool)
    world = scene.world
    if world is None:
        return out
    import mujoco

    world.kinematics()
    m, d = world.model, world.data
    skip_bodies: set[int] = set()
    for e in exclude:
        ent = scene.entities[e] if isinstance(e, str) else e
        bid = world.proxy_body(ent)
        if bid < 0:
            bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, ent.name)
        if bid >= 0:  # the body and everything below it
            skip_bodies |= {b for b in range(m.nbody) if _descends(m, b, bid)}
    res, pad = grid.res, grid.res / 2
    lo_w, hi_w = grid.bounds
    n = np.array(grid.shape)
    for g in range(m.ngeom):
        kind = int(m.geom_type[g])
        if kind in (PLANE, HFIELD) or int(m.geom_bodyid[g]) in skip_bodies:
            continue
        rot = d.geom_xmat[g].reshape(3, 3)
        pos = d.geom_xpos[g].copy()
        size = m.geom_size[g].copy()
        r = float(m.geom_rbound[g])
        if kind == MESH or kind not in (SPHERE, CAPSULE, ELLIPSOID, CYLINDER, BOX):
            aabb = m.geom_aabb[g]
            pos = pos + rot @ aabb[:3]
            size, kind = aabb[3:].copy(), BOX
            r = 0.0  # rbound is about the geom origin, not the box centre: bound the box itself
        if r <= 0:
            r = float(np.linalg.norm(size))
        lo = np.maximum(np.floor((pos - r - pad - lo_w) / res).astype(int), 0)
        hi = np.minimum(np.ceil((pos + r + pad - lo_w) / res).astype(int), n)
        if np.any(hi <= lo) or np.any(pos + r < lo_w) or np.any(pos - r > hi_w):
            continue
        axes = [np.arange(a, b) for a, b in zip(lo, hi, strict=True)]
        ii, jj, kk = np.meshgrid(*axes, indexing="ij")
        ijk = np.stack([ii.ravel(), jj.ravel(), kk.ravel()], axis=1)
        centres = grid.origin + (ijk + 0.5) * res
        q = (centres - pos) @ rot
        hit = _inside(kind, size, q, pad)
        sel = ijk[hit]
        out[sel[:, 0], sel[:, 1], sel[:, 2]] = True
    return out


def _descends(m: Any, body: int, root: int) -> bool:  # noqa: ANN401
    while True:
        if body == root:
            return True
        if body == 0:
            return False
        body = int(m.body_parentid[body])


def evaluate(
    grid: OccupancyGrid,
    scene: Scene,
    *,
    z_band: tuple[float, float] | None = None,
    radius: float | None = None,
    pos: Sequence[float] | None = None,
    exclude: Iterable[Entity | str] = (),
    observed_only: bool = True,
) -> Accuracy:
    """Score `grid` against `scene`'s true geometry.

    Voxels count if observed (unless `observed_only=False`), with centres in `z_band` (z
    range), and within `radius` (horizontal metres) of `pos`. `pos` (x, y) or (x, y, z)
    defaults to the grid's ego position; the nearest-obstacle distances are measured from it
    (horizontal for a 2-element `pos`) over the same band. `exclude` leaves out entities' own
    geometry, e.g. the ego vehicle."""
    truth = truth_grid(grid, scene, exclude)
    occ = grid.logodds > 0
    nx, ny, nz = grid.shape
    centres_z = grid.origin[2] + (np.arange(nz) + 0.5) * grid.res
    mask = grid.seen.copy() if observed_only else np.ones(grid.shape, dtype=bool)
    if z_band is not None:
        mask &= ((centres_z >= z_band[0]) & (centres_z <= z_band[1]))[None, None, :]
    if pos is None and grid.ego is not None:
        pos = grid.ego[:3, 3]
    p = None if pos is None else np.asarray(pos, dtype=np.float64)
    if radius is not None:
        if p is None:
            raise ValueError("radius needs pos (or a grid that knows the ego pose)")
        cx = grid.origin[0] + (np.arange(nx) + 0.5) * grid.res
        cy = grid.origin[1] + (np.arange(ny) + 0.5) * grid.res
        r2 = (cx[:, None] - p[0]) ** 2 + (cy[None, :] - p[1]) ** 2
        mask &= (r2 <= radius**2)[:, :, None]
    tp = int(np.count_nonzero(occ & truth & mask))
    fp = int(np.count_nonzero(occ & ~truth & mask))
    fn = int(np.count_nonzero(~occ & truth & mask))
    iou = tp / (tp + fp + fn) if tp + fp + fn else float("nan")
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    near_t = near_p = float("inf")
    if p is not None:
        band = np.ones(grid.shape, dtype=bool)
        if z_band is not None:
            band &= ((centres_z >= z_band[0]) & (centres_z <= z_band[1]))[None, None, :]
        near_t = _nearest(grid, truth & band, p)
        near_p = _nearest(grid, occ & band, p)
    err = abs(near_p - near_t) if np.isfinite(near_p) and np.isfinite(near_t) else float("nan")
    return Accuracy(iou, precision, recall, err, near_t, near_p, tp, fp, fn)


def _nearest(grid: OccupancyGrid, cells: np.ndarray, p: np.ndarray) -> float:
    ijk = np.argwhere(cells)
    if len(ijk) == 0:
        return float("inf")
    c = grid.origin + (ijk + 0.5) * grid.res
    return float(np.min(np.linalg.norm(c[:, : len(p)] - p, axis=1)))
