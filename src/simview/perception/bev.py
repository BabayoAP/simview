"""BEV map stage (VW-07, D-127): a top-down occupancy and height map from the occupancy grid."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from simview.perception.occupancy import OccupancyGrid

# Gray levels of the BEV image (data, not UI styling): unknown, free, and the occupied range
# (low obstacles lighter, tall ones darker).
UNKNOWN, FREE, OCC_LOW, OCC_HIGH = 128, 255, 96, 0


@dataclass(eq=False)
class Bev:
    """`occupied` (nx, ny) bool: a voxel within the height band is occupied; `known` (nx, ny):
    some voxel of the band was observed; `height` (nx, ny) float32: top of the highest occupied
    voxel in the band (nan where none). Index [i, j] is the column at x = origin_x + (i + 0.5)
    res, y = origin_y + (j + 0.5) res. `image` (ny, nx, 3) uint8 is the map seen from above
    with +x to the right and +y up (row 0 is the largest y)."""

    t: float
    occupied: np.ndarray
    known: np.ndarray
    height: np.ndarray
    image: np.ndarray
    origin: np.ndarray  # world (x, y) of the map's lower corner
    res: float
    ego: np.ndarray | None = None

    def pixel(self, x: float, y: float) -> tuple[int, int]:
        """(row, col) of a world (x, y) in `image`."""
        col = int(np.floor((x - self.origin[0]) / self.res))
        row = self.image.shape[0] - 1 - int(np.floor((y - self.origin[1]) / self.res))
        return row, col


class BevMap:
    """Pipeline stage: OccupancyGrid -> Bev, over the height band `z_band` (metres)."""

    output = "bev"

    def __init__(self, z_band: tuple[float, float] = (0.2, 2.5)) -> None:
        if z_band[1] <= z_band[0]:
            raise ValueError("z_band is (low, high) with high > low")
        self.z_band = (float(z_band[0]), float(z_band[1]))

    def reset(self) -> None:
        pass

    def __call__(self, grid: OccupancyGrid) -> Bev:
        return self.compute(grid)

    def compute(self, grid: OccupancyGrid) -> Bev:
        nz = grid.shape[2]
        tops = grid.origin[2] + (np.arange(nz) + 1) * grid.res
        bottoms = tops - grid.res
        band = (tops > self.z_band[0]) & (bottoms < self.z_band[1])
        occ3 = grid.logodds[:, :, band] > 0
        occupied = occ3.any(axis=2)
        known = grid.seen[:, :, band].any(axis=2)
        height = np.full(occupied.shape, np.nan, dtype=np.float32)
        if occ3.shape[2]:
            last = occ3.shape[2] - 1 - np.argmax(occ3[:, :, ::-1], axis=2)
            height[occupied] = tops[band][last[occupied]]
        gray = np.where(known, FREE, UNKNOWN).astype(np.float32)
        if occupied.any():
            frac = np.clip((height - self.z_band[0]) / (self.z_band[1] - self.z_band[0]), 0, 1)
            gray[occupied] = OCC_LOW + (OCC_HIGH - OCC_LOW) * frac[occupied]
        img = np.round(gray).astype(np.uint8).T[::-1]  # rows: y descending; cols: x
        return Bev(
            t=grid.t,
            occupied=occupied,
            known=known,
            height=height,
            image=np.ascontiguousarray(np.repeat(img[:, :, None], 3, axis=2)),
            origin=grid.origin[:2].copy(),
            res=grid.res,
            ego=None if grid.ego is None else grid.ego.copy(),
        )
