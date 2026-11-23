"""Camera rigs (VW-01, D-122): N calibrated RGB + depth cameras mounted on one entity.

A rig is a sensor: `ego.attach(CameraRig.surround(n=8))`. Each camera is an SN-02 `Camera`
(ray cast on the CPU) mounted in the rig's frame; the rig samples all of them at its own rate
and publishes one stream per camera, named `<entity>.<camera>`, of `Frame`s (K, world-from-camera
pose of the optical frame, RGB, float32 z-depth).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from simview.perception.stream import SENSOR_FROM_OPTICAL, Frame, Stream
from simview.sensors.base import Sensor
from simview.sensors.camera import Camera

if TYPE_CHECKING:
    from simview.core.scheduler import Sim


def camera_K(cam: Camera) -> np.ndarray:  # noqa: N802
    """A SimView camera's intrinsics in the OpenCV pixel convention (centres at integers)."""
    return np.array(
        [
            [cam.focal, 0.0, cam.width / 2 - 0.5],
            [0.0, cam.focal, cam.height / 2 - 0.5],
            [0.0, 0.0, 1.0],
        ]
    )


class CameraRig(Sensor):
    """Cameras (their `pos`/`rpy` are in the rig's frame) sampled together at `rate` Hz.

    The rig's own `pos`/`rpy` mount it on the entity. Camera names must be unique; each
    camera's own rate is ignored (the rig's applies). `streams` maps stream names to `Stream`s
    once the rig is attached."""

    uses_world = True

    def __init__(
        self,
        cameras: Sequence[Camera],
        rate: float = 10.0,
        *,
        name: str = "rig",
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        rpy: Sequence[float] = (0.0, 0.0, 0.0),
        maxlen: int = 64,
    ) -> None:
        super().__init__(rate, name=name, pos=pos, rpy=rpy)
        cams = list(cameras)
        if not cams:
            raise ValueError("a camera rig needs at least one camera")
        names = [c.name for c in cams]
        if len(set(names)) != len(names):
            raise ValueError(f"camera names in a rig must be unique, got {names}")
        for c in cams:
            if c.entity is not None:
                raise ValueError(f"camera {c.name!r} is already attached to {c.entity.name}")
        self.cameras = cams
        self._local = [c.mount.copy() for c in cams]  # camera-in-rig mounts
        self._zscale = [c.directions[:, 0].reshape(c.height, c.width) for c in cams]
        self.maxlen = int(maxlen)
        self._streams: dict[str, Stream] = {}

    # -- presets -----------------------------------------------------------------------------
    @classmethod
    def surround(
        cls,
        n: int = 8,
        *,
        width: int = 160,
        height: int = 120,
        rate: float = 10.0,
        mount_height: float = 1.4,
        max_range: float = 60.0,
        name: str = "rig",
    ) -> CameraRig:
        """A car's ring: for n=8, main, narrow and wide front, two per side, and rear (D-122).
        Other n give n evenly spaced cameras. `mount_height` is above the entity's origin."""
        if n < 1:
            raise ValueError("a rig needs at least one camera")
        if n == 8:
            layout = [  # name, yaw (deg, left positive), horizontal fov (deg), x offset
                ("front_main", 0.0, 60.0, 1.0),
                ("front_narrow", 0.0, 35.0, 1.0),
                ("front_wide", 0.0, 120.0, 1.0),
                ("left_front", 75.0, 90.0, 0.5),
                ("left_rear", 135.0, 90.0, 0.0),
                ("right_front", -75.0, 90.0, 0.5),
                ("right_rear", -135.0, 90.0, 0.0),
                ("rear", 180.0, 90.0, -0.5),
            ]
        else:
            fov = min(120.0, 1.25 * 360.0 / n)
            layout = [(f"cam{i}", 360.0 * i / n, fov, 0.0) for i in range(n)]
        cams = [
            Camera(
                rate,
                width=width,
                height=height,
                fov=np.radians(f),
                max_range=max_range,
                name=nm,
                pos=(x, 0.0, mount_height),
                rpy=(0.0, 0.0, np.radians(yaw)),
            )
            for nm, yaw, f, x in layout
        ]
        return cls(cams, rate, name=name)

    @classmethod
    def drone(
        cls,
        n: int = 6,
        *,
        width: int = 160,
        height: int = 120,
        rate: float = 10.0,
        max_range: float = 60.0,
        name: str = "rig",
    ) -> CameraRig:
        """A drone's cameras: n-1 around the horizon plus one looking down (n=6: front, left,
        back, right at 90 deg, down, and up, a cube)."""
        if n < 2:
            raise ValueError("a drone rig needs at least two cameras")
        if n == 6:
            ring = [("front", 0.0), ("left", 90.0), ("back", 180.0), ("right", -90.0)]
            layout = [(nm, 0.0, y) for nm, y in ring] + [("down", 90.0, 0.0), ("up", -90.0, 0.0)]
            fov = 90.0
        else:
            k = n - 1
            layout = [(f"cam{i}", 0.0, 360.0 * i / k) for i in range(k)] + [("down", 90.0, 0.0)]
            fov = min(120.0, 1.25 * 360.0 / k)
        cams = [
            Camera(
                rate,
                width=width,
                height=height,
                fov=np.radians(fov),
                max_range=max_range,
                name=nm,
                rpy=(0.0, np.radians(pitch), np.radians(yaw)),
            )
            for nm, pitch, yaw in layout
        ]
        return cls(cams, rate, name=name)

    # -- streams -----------------------------------------------------------------------------
    def stream_name(self, cam: Camera | str) -> str:
        cname = cam if isinstance(cam, str) else cam.name
        owner = self.entity.name if self.entity is not None else self.name
        return f"{owner}.{cname}"

    @property
    def streams(self) -> dict[str, Stream]:
        """Stream name -> Stream, one per camera, in camera order."""
        want = [self.stream_name(c) for c in self.cameras]
        if list(self._streams) != want:
            self._streams = {n: Stream(n, self.maxlen) for n in want}
        return self._streams

    def intrinsics(self, cam: Camera | str) -> np.ndarray:
        return camera_K(self._camera(cam))

    def camera_pose(self, cam: Camera | str) -> np.ndarray:
        """World-from-camera pose of a camera's optical frame (x right, y down, z forward)."""
        c = self._camera(cam)
        assert self.entity is not None, f"rig {self.name!r} isn't attached to an entity"
        return (
            self.entity.pose()
            @ self.mount
            @ self._local[self.cameras.index(c)]
            @ (SENSOR_FROM_OPTICAL)
        )

    def _camera(self, cam: Camera | str) -> Camera:
        if isinstance(cam, Camera):
            return cam
        for c in self.cameras:
            if c.name == cam:
                return c
        raise KeyError(f"rig {self.name!r} has no camera {cam!r}")

    # -- sensor protocol ---------------------------------------------------------------------
    def reset(self, sim: Sim) -> None:
        super().reset(sim)
        for c, local in zip(self.cameras, self._local, strict=True):
            c.entity = self.entity
            c.mount = self.mount @ local
            c.reset(sim)
        for s in self.streams.values():
            s.reset()

    def measure(self, sim: Sim) -> None:
        assert self.entity is not None
        ego = self.entity.pose()
        streams = list(self.streams.values())
        for c, zs, stream in zip(self.cameras, self._zscale, streams, strict=True):
            c.t, c.tick = self.t, self.tick
            c.measure(sim)
            depth = (c.depth * zs).astype(np.float32)  # range along the ray -> z-depth
            frame = Frame(
                t=self.t,
                seq=stream.seq + 1,
                source=stream.name,
                K=camera_K(c),
                pose=c.pose() @ SENSOR_FROM_OPTICAL,
                rgb=c.image,
                depth=depth,
                ego=ego.copy(),
            )
            stream.push(frame, self.t)
