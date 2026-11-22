"""Occupancy grid stage (VW-06, D-126): a 3D log-odds voxel grid fused from point clouds.

Each update traces every ray from its camera to its point: voxels the ray passes through get
`l_free`, the voxel holding the point gets `l_occ` (each voxel once per update, a hit wins over a
pass-through, as OctoMap does), and values are clamped to `clamp`. Ray traversal samples every
ray at `res` spacing, all rays at once with NumPy. A voxel is occupied when its log-odds is
above 0 and free below 0; never-seen voxels stay 0 (unknown).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from simview.perception.backproject import PointCloud


class OccupancyGrid:
    """Pipeline stage: PointCloud -> this grid (the same, live object every step).

    `res` is the voxel edge (m). `extent` is the horizontal size: one number (a square) or
    (x, y); `height=(z0, z1)` the vertical range. A world-fixed grid is centred on `center`
    (x, y); `rolling=True` re-centres it on the ego vehicle every update, keeping the cells
    that overlap (shifted by whole voxels). Hits below `floor` (z, m; None = off) are ground: their
    rays still clear space but they don't mark occupancy. `decay` (0..1) pulls every value
    toward unknown by that fraction per update (values under 0.01 snap to 0), so cells of
    moved objects clear."""

    output = "occupancy"

    def __init__(
        self,
        res: float = 0.2,
        extent: float | Sequence[float] = 60.0,
        *,
        height: tuple[float, float] = (0.0, 4.0),
        center: Sequence[float] = (0.0, 0.0),
        rolling: bool = False,
        floor: float | None = 0.1,
        l_occ: float = 0.85,
        l_free: float = -0.4,
        clamp: tuple[float, float] = (-2.0, 3.5),
        decay: float = 0.0,
    ) -> None:
        ex, ey = (float(extent), float(extent)) if np.isscalar(extent) else map(float, extent)  # type: ignore[arg-type]
        z0, z1 = (float(v) for v in height)
        if res <= 0 or ex <= 0 or ey <= 0 or z1 <= z0:
            raise ValueError("need res > 0, a positive extent, and height (z0, z1) with z1 > z0")
        if not (l_occ > 0 > l_free and clamp[0] < 0 < clamp[1]):
            raise ValueError("need l_occ > 0 > l_free and clamp (lo < 0 < hi)")
        if not 0.0 <= decay < 1.0:
            raise ValueError("decay must be in [0, 1)")
        self.res = float(res)
        self.shape = (
            max(1, round(ex / self.res)),
            max(1, round(ey / self.res)),
            max(1, round((z1 - z0) / self.res)),
        )
        self.rolling = bool(rolling)
        self.floor = None if floor is None else float(floor)
        self.l_occ, self.l_free = np.float32(l_occ), np.float32(l_free)
        self.clamp = (np.float32(clamp[0]), np.float32(clamp[1]))
        self.decay = float(decay)
        self._center0 = np.array([float(center[0]), float(center[1])])
        self._z0 = z0
        self.reset()

    # -- state -------------------------------------------------------------------------------
    def reset(self) -> None:
        self.logodds = np.zeros(self.shape, dtype=np.float32)
        self.seen = np.zeros(self.shape, dtype=bool)
        self.origin = self._lower_corner(self._center0)
        self.t = float("nan")
        self.version = 0  # update count
        self.ego: np.ndarray | None = None
        self._centers: tuple[int, np.ndarray] | None = None

    def _lower_corner(self, center: np.ndarray) -> np.ndarray:
        nx, ny, _ = self.shape
        return np.array(
            [center[0] - nx * self.res / 2, center[1] - ny * self.res / 2, self._z0],
            dtype=np.float64,
        )

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """World (lower, upper) corners."""
        return self.origin.copy(), self.origin + np.array(self.shape) * self.res

    def copy(self) -> OccupancyGrid:
        """A detached snapshot (for loggers and UIs that keep past grids)."""
        g = object.__new__(OccupancyGrid)
        g.__dict__.update(self.__dict__)
        g.logodds, g.seen, g.origin = self.logodds.copy(), self.seen.copy(), self.origin.copy()
        g.ego = None if self.ego is None else self.ego.copy()
        g._centers = None
        return g

    # -- update ------------------------------------------------------------------------------
    def __call__(self, cloud: PointCloud) -> OccupancyGrid:
        self.update(cloud)
        return self

    def _recenter(self, xy: np.ndarray) -> None:
        center = np.round(np.asarray(xy, dtype=np.float64) / self.res) * self.res
        new = self._lower_corner(center)
        shift = np.round((new[:2] - self.origin[:2]) / self.res).astype(int)
        if not shift.any():
            return
        lo, seen = np.zeros_like(self.logodds), np.zeros_like(self.seen)
        src, dst = [], []
        for d, n in zip(shift, self.shape[:2], strict=True):
            d = int(d)
            if abs(d) >= n:
                src = []
                break
            src.append(slice(max(d, 0), n + min(d, 0)))
            dst.append(slice(max(-d, 0), n - max(d, 0)))
        if src:
            lo[dst[0], dst[1]] = self.logodds[src[0], src[1]]
            seen[dst[0], dst[1]] = self.seen[src[0], src[1]]
        self.logodds, self.seen = lo, seen
        self.origin = self.origin + np.array([shift[0], shift[1], 0]) * self.res

    def _flat(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Flat voxel indices of points (N, 3) and a mask of those inside the grid."""
        ijk = np.floor((pts - self.origin) / self.res).astype(np.int64)
        n = np.array(self.shape)
        inside = np.all((ijk >= 0) & (ijk < n), axis=1)
        ijk = ijk[inside]
        return (ijk[:, 0] * n[1] + ijk[:, 1]) * n[2] + ijk[:, 2], inside

    def update(self, cloud: PointCloud) -> None:
        if self.rolling:
            if cloud.ego is not None:
                xy = np.asarray(cloud.ego)[:2, 3]
            else:
                xy = cloud.origins[:, :2].mean(axis=0)
            self._recenter(xy)
        lo = self.logodds.reshape(-1)
        if self.decay:
            lo *= np.float32(1.0 - self.decay)
            lo[np.abs(lo) < np.float32(0.01)] = 0.0  # faded out: unknown again
        self.t, self.version = float(cloud.t), self.version + 1
        self.ego = None if cloud.ego is None else np.asarray(cloud.ego, dtype=np.float64).copy()
        self._centers = None
        pts = np.asarray(cloud.points, dtype=np.float64)
        if len(pts) == 0:
            return
        size = lo.size
        hit_mask = np.zeros(size, dtype=bool)
        occ = pts if self.floor is None else pts[pts[:, 2] >= self.floor]
        hit_idx, _ = self._flat(occ)
        hit_mask[hit_idx] = True
        free_mask = self._free_mask(cloud, pts)
        free_mask &= ~hit_mask
        seen = self.seen.reshape(-1)
        lo[free_mask] += self.l_free
        lo[hit_mask] += self.l_occ
        np.clip(lo, self.clamp[0], self.clamp[1], out=lo)
        seen |= free_mask
        seen |= hit_mask

    def _free_mask(self, cloud: PointCloud, pts: np.ndarray) -> np.ndarray:
        """Voxels crossed by the rays, sampled every `res` from each camera to its point."""
        mask = np.zeros(self.logodds.size, dtype=bool)
        o = np.asarray(cloud.origins, dtype=np.float64)[cloud.origin_index]
        d = pts - o
        dist = np.linalg.norm(d, axis=1)
        step = self.res
        counts = np.floor(dist / step).astype(np.int64)  # samples strictly before the hit
        keep = counts > 0
        if not keep.any():
            return mask
        o, d, dist, counts = o[keep], d[keep], dist[keep], counts[keep]
        # In voxel units: sample k of a ray is at start + (k + 0.5) * dir (one voxel apart).
        start_v = ((o - self.origin) / self.res).astype(np.float32)
        dir_v = (d / dist[:, None] * (step / self.res)).astype(np.float32)
        total = int(counts.sum())
        ray = np.repeat(np.arange(len(counts), dtype=np.int32), counts)
        first = np.repeat(np.cumsum(counts) - counts, counts)
        k = (np.arange(total, dtype=np.int64) - first).astype(np.float32) + np.float32(0.5)
        n = self.shape
        flat = np.zeros(total, dtype=np.int32)
        inside = np.ones(total, dtype=bool)
        for a in range(3):
            i = np.floor(start_v[ray, a] + dir_v[ray, a] * k).astype(np.int32)
            inside &= (i >= 0) & (i < n[a])
            flat *= n[a]
            flat += i
        mask[flat[inside]] = True
        return mask

    # -- queries -----------------------------------------------------------------------------
    @property
    def occupancy(self) -> np.ndarray:
        """Boolean (nx, ny, nz): occupied voxels."""
        return self.logodds > 0

    @property
    def probability(self) -> np.ndarray:
        """Occupancy probability per voxel (0.5 = unknown)."""
        return 1.0 / (1.0 + np.exp(-self.logodds.astype(np.float64)))

    def occupied(self, points: Sequence[float] | np.ndarray) -> np.ndarray | bool:
        """Whether each world point (N, 3), or one point (3,), is in an occupied voxel."""
        p = np.asarray(points, dtype=np.float64)
        one = p.ndim == 1
        p = p.reshape(-1, 3)
        flat, inside = self._flat(p)
        out = np.zeros(len(p), dtype=bool)
        out[inside] = self.logodds.reshape(-1)[flat] > 0
        return bool(out[0]) if one else out

    def is_free(self, a: Sequence[float], b: Sequence[float]) -> bool:
        """True if no occupied voxel lies on the segment a-b (unknown space counts as free)."""
        a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
        n = max(2, int(np.ceil(np.linalg.norm(b - a) / (self.res / 4))) + 1)
        pts = a + np.linspace(0.0, 1.0, n)[:, None] * (b - a)
        return not bool(np.any(self.occupied(pts)))

    def occupied_centers(self) -> np.ndarray:
        """World centres (N, 3) of the occupied voxels, in index order."""
        if self._centers is None or self._centers[0] != self.version:
            ijk = np.argwhere(self.logodds > 0)
            self._centers = (self.version, self.origin + (ijk + 0.5) * self.res)
        return self._centers[1]

    def nearest_obstacle(self, pos: Sequence[float], within: float = np.inf) -> float:
        """Distance from `pos` to the nearest occupied voxel centre (inf if none within
        `within`). A 2-element `pos` (x, y) measures horizontal distance over every height."""
        hit = self.closest_occupied(pos, within)
        if hit is None:
            return float("inf")
        p = np.asarray(pos, dtype=np.float64)
        return float(np.linalg.norm(hit[: len(p)] - p))

    def closest_occupied(self, pos: Sequence[float], within: float = np.inf) -> np.ndarray | None:
        """The nearest occupied voxel centre to `pos` (as in `nearest_obstacle`), or None."""
        c = self.occupied_centers()
        if len(c) == 0:
            return None
        p = np.asarray(pos, dtype=np.float64)
        if p.shape not in ((2,), (3,)):
            raise ValueError("pos is (x, y) or (x, y, z)")
        d = np.linalg.norm(c[:, : len(p)] - p, axis=1)
        i = int(np.argmin(d))
        return None if d[i] > within else c[i].copy()
