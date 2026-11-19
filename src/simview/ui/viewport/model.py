"""What the viewport draws, as plain geometry and matrices (VP-01, VP-04, VP-07).

No OpenGL here: this turns the sim's scene description and state frames into PyVista meshes,
4x4 world matrices, trail polylines, debug-draw geometry, and the ground grid, so it is tested on
every OS. `view.py` puts the results on screen.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pyvista as pv

from simview.ipc.protocol import Description, Geom
from simview.ui.theme import tokens
from simview.ui.theme.tokens import ThemeName

CYLINDER_RESOLUTION = 32


# -- transforms --------------------------------------------------------------------------------
def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """3x3 rotation from a (w, x, y, z) quaternion (normalized here)."""
    w, x, y, z = np.asarray(q, dtype=np.float64) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def pose_matrix(pos: np.ndarray, quat: np.ndarray) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = quat_to_matrix(quat)
    m[:3, 3] = pos
    return m


def matrix_to_pose(m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(position, (w, x, y, z) quaternion) of a 4x4 rigid transform."""
    from scipy.spatial.transform import Rotation

    x, y, z, w = Rotation.from_matrix(m[:3, :3]).as_quat()
    return m[:3, 3].copy(), np.array([w, x, y, z])


# -- geometry ------------------------------------------------------------------------------------
def geom_mesh(g: Geom) -> pv.PolyData:
    """The geom's surface in its own frame (MuJoCo half sizes; cylinders along z)."""
    s = g.size
    if g.kind == "box":
        return pv.Cube(x_length=2 * s[0], y_length=2 * s[1], z_length=2 * s[2])
    if g.kind == "sphere":
        return pv.Sphere(radius=s[0], theta_resolution=24, phi_resolution=24)
    if g.kind == "cylinder":
        return pv.Cylinder(
            direction=(0, 0, 1), radius=s[0], height=2 * s[1], resolution=CYLINDER_RESOLUTION
        )
    if g.kind == "capsule":
        return pv.Capsule(
            direction=(0, 0, 1),
            radius=s[0],
            cylinder_length=2 * s[1],
            resolution=CYLINDER_RESOLUTION,
        )
    if g.kind == "ellipsoid":
        return pv.ParametricEllipsoid(s[0], s[1], s[2])
    if g.kind == "mesh" and g.vertices is not None and g.faces is not None:
        faces = np.hstack([np.full((len(g.faces), 1), 3), g.faces]).astype(np.int64).ravel()
        return pv.PolyData(np.asarray(g.vertices, dtype=np.float64), faces)
    raise ValueError(f"cannot draw geom kind {g.kind!r}")


def load_visual(path: str, scale: float = 1.0) -> pv.PolyData:
    """A visual mesh file as one surface (GLB/glTF scenes are merged), scaled (VP-01).

    glTF is +Y-up; SimView is +Z-up, so GLB/glTF files are turned +90 deg about x."""
    data = pv.read(path)
    if isinstance(data, pv.MultiBlock):
        data = data.combine(merge_points=False).extract_surface(algorithm="dataset_surface")
    mesh = (
        data if isinstance(data, pv.PolyData) else data.extract_surface(algorithm="dataset_surface")
    )
    if path.lower().endswith((".glb", ".gltf")):
        mesh = mesh.rotate_x(90.0, inplace=False)
    if scale != 1.0:
        mesh = mesh.scale(scale, inplace=False)
    return mesh


def geom_local(g: Geom) -> np.ndarray:
    return pose_matrix(np.array(g.pos), np.array(g.quat))


def geom_world_matrices(desc: Description, bodies: np.ndarray) -> list[np.ndarray]:
    """World matrix of every geom for one frame of body poses (n_bodies x 7)."""
    body_m = [pose_matrix(b[:3], b[3:]) for b in bodies]
    return [body_m[g.body] @ geom_local(g) for g in desc.geoms]


def body_world_matrices(bodies: np.ndarray) -> list[np.ndarray]:
    return [pose_matrix(b[:3], b[3:]) for b in bodies]


# -- ground grid (§7.5: major and minor lines that fade with distance) ----------------------
def hex_rgb(hex_color: str) -> np.ndarray:
    h = hex_color.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.uint8)


def ground_grid(theme: ThemeName) -> pv.PolyData:
    """Grid lines on z = 0 with per-point RGBA ("rgba") that fades toward the edge."""
    ext, major, minor = tokens.GRID_EXTENT, tokens.GRID_MAJOR, tokens.GRID_MINOR
    fade0, fade1 = tokens.GRID_FADE
    n = round(ext / minor)
    ticks = np.arange(-n, n + 1) * minor
    pts: list[tuple[float, float, float]] = []
    colors: list[np.ndarray] = []
    lines: list[int] = []
    samples = np.linspace(-ext, ext, 41)  # points along each line, so the fade is smooth
    for along_x in (True, False):
        for c in ticks:
            is_major = abs(c / major - round(c / major)) < 1e-9
            rgb = hex_rgb(
                tokens.color(theme, "viewport.grid_major" if is_major else "viewport.grid_minor")
            )
            start = len(pts)
            for s in samples:
                p = (s, c, 0.0) if along_x else (c, s, 0.0)
                r = np.hypot(p[0], p[1]) / ext
                alpha = 1.0 - np.clip((r - fade0) / (fade1 - fade0), 0.0, 1.0)
                pts.append(p)
                colors.append(np.append(rgb, np.uint8(255 * alpha)))
            lines += [len(samples), *range(start, start + len(samples))]
    grid = pv.PolyData(np.array(pts), lines=np.array(lines))
    grid.point_data["rgba"] = np.array(colors, dtype=np.uint8)
    return grid


# -- trails (VP-04) --------------------------------------------------------------------------------
@dataclass
class Trail:
    """The last `seconds` of an entity's marker positions, by sim time."""

    seconds: float = tokens.TRAIL_SECONDS
    points: deque[tuple[float, np.ndarray]] = field(default_factory=deque)

    def add(self, t: float, p: np.ndarray) -> None:
        if self.points and t < self.points[-1][0]:
            self.points.clear()  # the run was reset or scrubbed back
        if self.points and t == self.points[-1][0]:
            return
        self.points.append((t, np.array(p, dtype=np.float64)))
        while self.points and self.points[0][0] < t - self.seconds:
            self.points.popleft()

    def replace(self, t: float, points: np.ndarray) -> None:
        """Show a recorded path ending at time `t` (the timeline replays history, VP-05)."""
        pts = np.asarray(points, dtype=np.float64)
        self.points = deque(zip([t] * len(pts), pts, strict=True))  # rows are views, no copies

    def polyline(self) -> pv.PolyData | None:
        if len(self.points) < 2:
            return None
        return pv.lines_from_points(np.array([p for _, p in self.points]))


# -- debug draws (VP-07) ---------------------------------------------------------------------
def resolve_color(name: str, theme: ThemeName) -> str:
    """A theme token ("accent", "text.primary") or any color PyVista knows."""
    return tokens.color(theme, name) if name in tokens.COLORS[theme] else name


@dataclass
class DrawGeometry:
    lines: list[tuple[np.ndarray, np.ndarray, str, float]] = field(default_factory=list)
    arrows: list[tuple[np.ndarray, np.ndarray, str]] = field(default_factory=list)
    points: list[tuple[np.ndarray, str, float]] = field(default_factory=list)
    labels: list[tuple[np.ndarray, str, str, float]] = field(default_factory=list)


def draw_geometry(draws: list[tuple], theme: ThemeName) -> DrawGeometry:
    """Group draw records (kind, points, color, size, text) into drawable pieces."""
    out = DrawGeometry()
    for kind, pts, color, size, text in draws:
        p = [np.array(v) for v in pts]
        if kind == "line":
            out.lines.append((p[0], p[1], resolve_color(color, theme), size))
        elif kind == "arrow":
            out.arrows.append((p[0], p[1], resolve_color(color, theme)))
        elif kind == "point":
            out.points.append((p[0], resolve_color(color, theme), size))
        elif kind == "text":
            out.labels.append((p[0], text, resolve_color(color, theme), size))
        elif kind == "frame":
            for axis, end in zip("xyz", p[1:], strict=True):
                out.lines.append((p[0], end, tokens.AXIS_COLORS[axis], tokens.TRAIL_WIDTH))
    return out
