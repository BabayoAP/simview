"""Ray casting against the scene's MuJoCo world (SN-02, SN-03), shared by lidar and camera."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from simview.core.entity import Entity
    from simview.core.scheduler import Sim


def cast(
    sim: Sim,
    origin: np.ndarray,
    directions: np.ndarray,
    max_range: float,
    exclude: Entity | None,
    groups: np.ndarray | None = None,
    normals: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Cast unit `directions` (N, 3) from `origin`. Returns (distance, geom id, normals): the
    distance is inf and the geom -1 where nothing is hit within `max_range`. A scene without
    a MuJoCo world hits nothing. `exclude`'s own body (robot base, free body, or proxy) is
    skipped so a sensor doesn't see the vehicle it's mounted on."""
    import mujoco

    n = len(directions)
    dist = np.full(n, np.inf)
    geom = np.full(n, -1, dtype=np.int32)
    world = sim.scene.world
    if world is None or n == 0:
        return dist, geom, (np.zeros((n, 3)) if normals else None)
    m, d = world.model, world.data
    body = -1
    if exclude is not None:
        body = world.proxy_body(exclude)
        if body < 0:
            body = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, exclude.name)
    raw = np.empty(n)
    nrm = np.empty((n, 3)) if normals else None
    mujoco.mj_multiRay(
        m,
        d,
        np.ascontiguousarray(origin, dtype=np.float64),
        np.ascontiguousarray(directions, dtype=np.float64).ravel(),
        groups,
        1,
        int(body),
        geom,
        raw,
        None if nrm is None else nrm.ravel(),
        n,
        float(max_range),
    )
    hit = (geom >= 0) & (raw >= 0) & (raw <= max_range)
    dist[hit] = raw[hit]
    geom[~hit] = -1
    return dist, geom, nrm
