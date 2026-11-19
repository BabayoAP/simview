"""Camera navigation math (VP-02, VP-03, DS-05), independent of VTK.

SimView's default is Onshape/SolidWorks style (§7.5): orbit around the point under the cursor,
pan in the view plane, zoom toward the cursor. World up is +z. A `Camera` is plain data; `view.py`
copies it to and from the VTK camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

UP = np.array([0.0, 0.0, 1.0])
MIN_POLE_ANGLE = np.radians(1.0)  # orbit stops this close to straight up/down
PRESETS = {  # view direction (from focal point toward camera) and up vector
    "front": (np.array([0.0, -1.0, 0.0]), UP),
    "right": (np.array([1.0, 0.0, 0.0]), UP),
    "top": (np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0])),
    "iso": (np.array([1.0, -1.0, 1.0]) / np.sqrt(3.0), UP),
}


@dataclass(frozen=True)
class Camera:
    position: np.ndarray
    focal: np.ndarray
    up: np.ndarray = field(default_factory=UP.copy)
    parallel: bool = False
    parallel_scale: float = 1.0  # half the view height in metres, when parallel
    view_angle: float = 30.0  # vertical field of view in degrees, when perspective

    @property
    def distance(self) -> float:
        return float(np.linalg.norm(self.position - self.focal))

    @property
    def forward(self) -> np.ndarray:
        d = self.focal - self.position
        return d / np.linalg.norm(d)

    @property
    def right(self) -> np.ndarray:
        r = np.cross(self.forward, self.up)
        return r / np.linalg.norm(r)

    @property
    def true_up(self) -> np.ndarray:
        return np.cross(self.right, self.forward)


def _rotate(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation of vector v about a unit axis."""
    axis = axis / np.linalg.norm(axis)
    return (
        v * np.cos(angle)
        + np.cross(axis, v) * np.sin(angle)
        + axis * np.dot(axis, v) * (1 - np.cos(angle))
    )


def orbit(cam: Camera, pivot: np.ndarray, dx: float, dy: float, deg_per_px: float) -> Camera:
    """Turntable orbit around `pivot`: dx turns about world z, dy tilts about the camera's
    right axis. Tilt stops just short of the poles so the view never flips."""
    yaw = -np.radians(dx * deg_per_px)
    pitch = -np.radians(dy * deg_per_px)
    pos, foc, up = cam.position - pivot, cam.focal - pivot, cam.true_up
    pos, foc, up = (_rotate(v, UP, yaw) for v in (pos, foc, up))
    right = np.cross(foc - pos, up)
    right /= np.linalg.norm(right)
    view = (foc - pos) / np.linalg.norm(foc - pos)
    tilt = np.arccos(np.clip(np.dot(view, -UP), -1.0, 1.0))  # 0 looking straight down
    new_tilt = np.clip(tilt - pitch, MIN_POLE_ANGLE, np.pi - MIN_POLE_ANGLE)
    pitch = tilt - new_tilt
    pos, foc, up = (_rotate(v, right, pitch) for v in (pos, foc, up))
    return replace(cam, position=pos + pivot, focal=foc + pivot, up=up)


def pan(cam: Camera, dx: float, dy: float, height_px: int) -> Camera:
    """Move the camera in its view plane so the scene follows the mouse by (dx, dy) px."""
    if cam.parallel:
        metres_per_px = 2 * cam.parallel_scale / height_px
    else:
        metres_per_px = 2 * cam.distance * np.tan(np.radians(cam.view_angle) / 2) / height_px
    shift = (-dx * cam.right + dy * cam.true_up) * metres_per_px
    return replace(cam, position=cam.position + shift, focal=cam.focal + shift)


def zoom_to(cam: Camera, point: np.ndarray, notches: float, step: float) -> Camera:
    """Zoom toward `point` (the world point under the cursor): positive notches zoom in.
    The point stays under the cursor."""
    f = 1.0 - (1.0 - step) ** notches  # fraction of the way toward the point
    if cam.parallel:
        scale = cam.parallel_scale * (1.0 - f)
        # Keep `point` fixed on screen: move the view center toward it by the same fraction.
        offset = point - cam.focal
        offset -= np.dot(offset, cam.forward) * cam.forward
        shift = offset * f
        return replace(
            cam, position=cam.position + shift, focal=cam.focal + shift, parallel_scale=scale
        )
    move = (point - cam.position) * f
    return replace(cam, position=cam.position + move, focal=cam.focal + move)


def preset(name: str, center: np.ndarray, radius: float, cam: Camera) -> Camera:
    """A named view (front, right, top, iso) that frames a sphere of `radius` at `center`."""
    direction, up = PRESETS[name]
    dist = radius / np.sin(np.radians(cam.view_angle) / 2)
    return replace(
        cam,
        position=center + direction * dist,
        focal=center.copy(),
        up=up.copy(),
        parallel_scale=radius,
    )


def frame(center: np.ndarray, radius: float, cam: Camera) -> Camera:
    """Keep the view direction, and fit a sphere of `radius` at `center` (frame all/selected)."""
    dist = radius / np.sin(np.radians(cam.view_angle) / 2)
    return replace(
        cam, position=center - cam.forward * dist, focal=center.copy(), parallel_scale=radius
    )


def top_2d(center: np.ndarray, radius: float, cam: Camera) -> Camera:
    """VP-03: top-down orthographic view (rotation is locked by the caller)."""
    return replace(preset("top", center, radius, cam), parallel=True)


def fly(cam: Camera, key: str, step: float) -> Camera:
    """Fly mode (VP-02): W/S forward and back, A/D left and right, E/Q up and down."""
    moves = {
        "w": cam.forward,
        "s": -cam.forward,
        "d": cam.right,
        "a": -cam.right,
        "e": UP,
        "q": -UP,
    }
    if key not in moves:
        return cam
    shift = moves[key] * step
    return replace(cam, position=cam.position + shift, focal=cam.focal + shift)


def project(cam: Camera, point: np.ndarray, width: int, height: int) -> np.ndarray:
    """Screen position (px from the top left) of a world point; used by tests and picking."""
    rel = point - cam.position
    x, y, z = np.dot(rel, cam.right), np.dot(rel, cam.true_up), np.dot(rel, cam.forward)
    if cam.parallel:
        half_h = cam.parallel_scale
    else:
        half_h = z * np.tan(np.radians(cam.view_angle) / 2)
    scale = (height / 2) / half_h
    return np.array([width / 2 + x * scale, height / 2 - y * scale])
