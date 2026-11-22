"""VW-07: BEV occupancy and height map, array and image."""

import numpy as np
import pytest

from simview.perception import BevMap, OccupancyGrid
from simview.perception.bev import FREE, UNKNOWN

from .test_occupancy import cloud


def test_bev_marks_columns_in_the_band_with_max_height():
    g = OccupancyGrid(res=0.5, extent=10.0, height=(0.0, 4.0), floor=None)
    g(cloud([[3.0, 0.0, 1.2], [3.0, 0.0, 0.3], [-2.0, 2.0, 3.8]], origin=(0, 0, 1.0)))
    bev = BevMap(z_band=(0.2, 2.5))(g)
    i, j = np.floor((np.array([3.0, 0.0]) - g.origin[:2]) / 0.5).astype(int)
    assert bev.occupied[i, j]
    assert bev.height[i, j] == pytest.approx(1.5)  # top of the voxel holding z = 1.2
    k, m = np.floor((np.array([-2.0, 2.0]) - g.origin[:2]) / 0.5).astype(int)
    assert not bev.occupied[k, m]  # z = 3.8 is above the band
    assert bev.occupied.sum() == 1
    assert np.isnan(bev.height[~bev.occupied]).all()
    assert bev.known[i - 1, j] and not bev.known[0, 0]


def test_bev_image_orientation_and_values():
    g = OccupancyGrid(res=0.5, extent=10.0, height=(0.0, 4.0))
    g(cloud([[4.0, 3.0, 1.0]], origin=(0, 0, 1.0)))
    bev = BevMap()(g)
    assert bev.image.shape == (20, 20, 3) and bev.image.dtype == np.uint8
    row, col = bev.pixel(4.0, 3.0)
    assert (row, col) == (20 - 1 - 16, 18)  # +x right, +y up
    assert bev.image[row, col, 0] < 96  # occupied: dark
    assert bev.image[0, 0, 0] == UNKNOWN
    r2, c2 = bev.pixel(2.0, 1.5)  # on the ray: free
    assert bev.image[r2, c2, 0] == FREE
    with pytest.raises(ValueError):
        BevMap(z_band=(2.0, 1.0))
