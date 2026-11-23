"""The 3D viewport widget (VP-01..VP-04, VP-06, VP-07, VP-10, DS-04..DS-06).

A PyVista `QtInteractor` driven by the model layer (`model.py`) and the navigation math
(`navigation.py`). VTK's own mouse and keyboard handling is replaced: mouse navigation is
Onshape/SolidWorks style (§7.5), and keys reach SimView's handler first (VTK's defaults would
close the window on `q`/`e`). The heads-up toolbar and HUD are drawn inside the render window,
because Qt widgets overlaid on an OpenGL surface don't composite reliably on every platform.
"""

from __future__ import annotations

import time
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
import vtk
from qtpy.QtCore import QByteArray, QEvent, QObject, Qt, Signal
from qtpy.QtGui import QImage, QKeyEvent, QPainter
from qtpy.QtSvg import QSvgRenderer
from qtpy.QtWidgets import QVBoxLayout, QWidget

from simview.ipc.protocol import Description
from simview.ipc.shm import Frame
from simview.ui import theme as theme_mod
from simview.ui.theme import tokens
from simview.ui.theme.tokens import ThemeName
from simview.ui.viewport import model
from simview.ui.viewport import navigation as nav

FONT_FILE = (
    Path(theme_mod.__file__).resolve().parent.parent
    / "assets"
    / "fonts"
    / "JetBrainsMono-Regular.ttf"
)
HOVER_PICK_PERIOD = 1 / 30  # s between hover picks
HUD_RATE = 10  # Hz, HUD text refresh
HUD_ABOVE_SCALE = 0.1  # normalized height of the HUD's bottom edge when the scale bar shows
CLICK_SLOP = 4  # px a press may move and still count as a click
TOOLBAR_ICON = 20  # px, heads-up toolbar icon size (2x for high DPI)
DISPLAY_MODES = ("shaded+edges", "shaded", "wireframe")
PRESET_CYCLE = ("iso", "front", "right", "top")


def _gizmo_scale(actor: Any) -> float:
    """PyVista sizes the gizmo relative to the actor; this makes it GIZMO_SIZE metres long."""
    return tokens.GIZMO_SIZE / max(float(actor.GetLength()), 1e-6)


_UNIT_SPHERE = pv.Sphere(radius=1.0, theta_resolution=24, phi_resolution=16)


def _group(items: list[Any], key: Any) -> dict[Any, list[Any]]:
    out: dict[Any, list[Any]] = {}
    for item in items:
        out.setdefault(key(item), []).append(item)
    return out


def _icon_image(name: str, color: str, size: int) -> vtk.vtkImageData:
    """A Lucide icon rendered by Qt into a VTK image (RGBA)."""
    renderer = QSvgRenderer(QByteArray(theme_mod.svg_for(name, color)))
    img = QImage(size, size, QImage.Format.Format_RGBA8888)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    ptr = img.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=size * size * 4).reshape(size, size, 4)
    arr = np.ascontiguousarray(arr[::-1])  # VTK images start at the bottom row
    data = vtk.vtkImageData()
    data.SetDimensions(size, size, 1)
    vtk_arr = pv.convert_array(arr.reshape(-1, 4))
    vtk_arr.SetName("rgba")
    data.GetPointData().SetScalars(vtk_arr)
    return data


class Viewport(QWidget):
    """Shows one loaded scene. Signals carry entity names (None clears)."""

    selected = Signal(object)
    hovered = Signal(object)
    target_moved = Signal(str, object)  # name, 4x4 pose (VP-10)
    body_moved = Signal(str, object, object)  # name, position, quaternion (w, x, y, z)

    def __init__(self, theme: ThemeName, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from pyvistaqt import QtInteractor  # needs an OpenGL context; imported on use

        self.theme = theme
        self.plotter = QtInteractor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plotter)
        self.plotter.enable_anti_aliasing("msaa", multi_samples=tokens.VIEWPORT_MSAA)
        self._install_input()
        self._reset_state()
        self.options = {"grid": True, "frames": False, "trails": True, "fly": False, "2d": False}
        self.display_mode = DISPLAY_MODES[0]
        self._preset_i = 0
        self.fps = 0.0
        self._frames_drawn: list[float] = []
        self.cursor_world: np.ndarray | None = None
        self.geometry_mode = model.GEOMETRY_MODES[0]  # VW-08: perceived and/or true geometry
        self._voxels: tuple[np.ndarray, float] | None = None  # shown voxel centres, size
        self._build_static()

    # ------------------------------------------------------------------ setup
    def _reset_state(self) -> None:
        self.desc: Description | None = None
        self.frame: Frame | None = None
        self._needs_framing = False
        self.geom_actors: list[Any] = []
        self.edge_actors: list[Any] = []
        self.actor_entity: dict[int, str] = {}  # id(vtkActor) -> entity
        self.entity_actors: dict[str, list[Any]] = {}
        self.marker_actors: dict[str, Any] = {}
        self.trails: dict[str, model.Trail] = {}
        self.trail_actor: Any = None  # all trails in one actor (NF-01, D-140)
        self.trail_colors: dict[str, np.ndarray] = {}
        self.frame_actors: list[Any] = []
        self.target_actors: dict[str, Any] = {}
        self.visual_actors: dict[str, Any] = {}
        self.target_widgets: list[Any] = []
        self.draw_actors: list[Any] = []
        # The batched meshes behind draw_actors, in the same order. VTK may swap a mapper's
        # input for its own (macOS draws wide lines another way), so this is the record.
        self.draw_meshes: list[pv.PolyData] = []
        self.body_widget: Any = None
        self.dragging: str | None = None
        self.selection: str | None = None
        self.hover: str | None = None
        self.outline_actors: list[Any] = []

    def _install_input(self) -> None:
        iren = self.plotter.iren.interactor
        self._style = vtk.vtkInteractorStyleUser()
        # PyVista's gizmo and pick callbacks find the plotter through the style's `_parent`
        # (set on PyVista's own styles). Without it every mouse move raises inside them, the
        # gizmo never highlights a handle, and so it can't be grabbed.
        self._style._parent = weakref.ref(self.plotter.iren)
        iren.SetInteractorStyle(self._style)
        self._gizmo_drag = False
        for ev in (
            "LeftButtonPressEvent",
            "LeftButtonReleaseEvent",
            "RightButtonPressEvent",
            "RightButtonReleaseEvent",
            "MiddleButtonPressEvent",
            "MiddleButtonReleaseEvent",
            "MouseMoveEvent",
            "MouseWheelForwardEvent",
            "MouseWheelBackwardEvent",
        ):
            iren.AddObserver(ev, self._on_mouse, -1.0)  # after widgets (gizmo, ViewCube)
        self.plotter.installEventFilter(self)
        self._drag: dict[str, Any] | None = None
        self._last_hover_pick = 0.0
        self.picker = vtk.vtkCellPicker()
        self.picker.SetTolerance(0.002)

    def _build_static(self) -> None:
        p = self.plotter
        p.clear()
        self.renderer = p.renderer
        self._apply_background()
        self.grid_actor = p.add_mesh(
            model.ground_grid(self.theme),
            scalars="rgba",
            rgba=True,
            pickable=False,
            lighting=False,
            name="grid",
        )
        self.grid_actor.SetVisibility(self.options["grid"])
        self.world_axes = p.add_mesh(  # VP-01: world axes at the origin, shown with the grid
            self._axes_poly(tokens.WORLD_AXIS_LENGTH),
            scalars="rgb",
            rgb=True,
            line_width=3,
            pickable=False,
            lighting=False,
            name="world_axes",
        )
        self.world_axes.SetVisibility(self.options["grid"])
        self._build_voxels()
        axis = {a: tokens.AXIS_COLORS[a] for a in "xyz"}  # §7.3: X red, Y green, Z blue
        p.add_axes(line_width=2, x_color=axis["x"], y_color=axis["y"], z_color=axis["z"])
        self.view_cube = p.add_camera_orientation_widget()  # ViewCube, top right (DS-04)
        rep = self.view_cube.GetRepresentation()
        rep.SetXAxisColor(*(model.hex_rgb(axis["x"]) / 255.0))  # VTK's default Y/Z are
        rep.SetYAxisColor(*(model.hex_rgb(axis["y"]) / 255.0))  # yellow/green
        rep.SetZAxisColor(*(model.hex_rgb(axis["z"]) / 255.0))
        # HUD (§7.5): a plain text actor. VTK's corner annotation re-fits its font on every
        # change (about 25 ms a frame); the readout also refreshes at HUD_RATE, not every frame.
        self.hud = vtk.vtkTextActor()
        tp = self.hud.GetTextProperty()
        tp.SetFontFamily(vtk.VTK_FONT_FILE)
        tp.SetFontFile(str(FONT_FILE))
        tp.SetFontSize(tokens.FONT_SIZE["caption"])
        tp.SetColor(*(model.hex_rgb(tokens.color(self.theme, "text.secondary")) / 255.0))
        tp.SetJustificationToRight()
        tp.SetVerticalJustificationToBottom()
        self.hud.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        self.hud.GetPositionCoordinate().SetValue(0.99, 0.01)
        self.renderer.AddViewProp(self.hud)
        self._hud_at = 0.0
        scale = p.add_legend_scale(
            bottom_axis_visibility=True,
            left_axis_visibility=False,
            top_axis_visibility=False,
            right_axis_visibility=False,
            legend_visibility=False,
            font_size_factor=0.8,
            color=tokens.color(self.theme, "text.secondary"),
        )
        self.scale_bar = scale[0] if isinstance(scale, tuple) else scale
        self.scale_bar.SetVisibility(False)
        self._build_overlay()
        self._build_toolbar()
        cam = nav.Camera(position=np.array([2.0, -2.0, 1.5]), focal=np.array([0.0, 0.0, 0.3]))
        self.set_camera(cam)

    def _build_voxels(self) -> None:
        """VW-08: occupied voxels as one GPU-instanced cube per centre, colored by height. The
        actor and mapper stay; `set_voxels` swaps the mapper's input in place."""
        self.voxel_mapper = vtk.vtkGlyph3DMapper()
        self._voxel_res = 0.0
        self.voxel_mapper.SetSourceData(model.voxel_cube(1.0))
        self.voxel_mapper.ScalingOff()
        self.voxel_mapper.OrientOff()
        self.voxel_mapper.SetScalarModeToUsePointFieldData()
        self.voxel_mapper.SelectColorArray("rgb")
        self.voxel_mapper.SetColorModeToDirectScalars()
        self.voxel_mapper.SetInputData(model.voxel_points(np.empty((0, 3))))
        self.voxel_actor = vtk.vtkActor()
        self.voxel_actor.SetMapper(self.voxel_mapper)
        self.voxel_actor.SetPickable(False)
        self.voxel_actor.SetVisibility(False)
        self.renderer.AddActor(self.voxel_actor)
        if self._voxels is not None:
            self.set_voxels(*self._voxels)

    def set_voxels(self, centers: np.ndarray | None, res: float = 0.0) -> None:
        """Show occupied voxel centres (N, 3) of size `res` m; None clears them."""
        if centers is None or len(centers) == 0:
            self._voxels = None
            self.voxel_mapper.SetInputData(model.voxel_points(np.empty((0, 3))))
        else:
            self._voxels = (centers, res)
            if res != self._voxel_res:
                self._voxel_res = res
                self.voxel_mapper.SetSourceData(model.voxel_cube(res))
            self.voxel_mapper.SetInputData(model.voxel_points(centers))
        self._apply_geometry_mode()

    @property
    def voxel_count(self) -> int:
        return 0 if self._voxels is None else len(self._voxels[0])

    def set_geometry_mode(self, mode: str) -> None:
        """VW-08: "both", "perceived" (voxels only), or "true" (scene geometry only)."""
        if mode not in model.GEOMETRY_MODES:
            raise ValueError(f"geometry mode must be one of {model.GEOMETRY_MODES}")
        self.geometry_mode = mode
        self._apply_geometry_mode()

    def _apply_geometry_mode(self) -> None:
        true_on = self.geometry_mode != "perceived"
        for a in self.geom_actors + list(self.visual_actors.values()):
            a.SetVisibility(true_on)
        for _, ea in self.edge_actors:
            ea.SetVisibility(true_on and self.display_mode == "shaded+edges")
        self.voxel_actor.SetVisibility(self.geometry_mode != "true" and self._voxels is not None)

    def _apply_background(self) -> None:
        c = tokens.color
        self.plotter.set_background(c(self.theme, "bg.app"), top=c(self.theme, "viewport.bg_top"))

    def _build_overlay(self) -> None:
        """A second renderer layer for outlines, so they stay visible through geometry (§7.5)."""
        rw = self.plotter.render_window
        rw.SetNumberOfLayers(2)
        self.overlay = vtk.vtkRenderer()
        self.overlay.SetLayer(1)
        self.overlay.InteractiveOff()
        self.overlay.SetActiveCamera(self.renderer.GetActiveCamera())
        rw.AddRenderer(self.overlay)

    # ------------------------------------------------------------------ heads-up toolbar (DS-04)
    def _build_toolbar(self) -> None:
        self.buttons: dict[str, Any] = {}
        specs = [
            ("frame_all", "maximize", False),
            ("frame_selected", "focus", False),
            ("preset", "rotate-3d", False),
            ("display", "layers", False),
            ("grid", "grid-3x3", True),
            ("frames", "axis-3d", True),
            ("trails", "route", True),
            ("ortho", "cuboid", True),
            ("2d", "square", True),
            ("fly", "send", True),
        ]
        off = tokens.color(self.theme, "text.secondary")
        on = tokens.color(self.theme, "accent")
        size = TOOLBAR_ICON * 2
        # The backdrop goes in first: 2D props draw in the order they are added, and a
        # translucent backdrop added after the buttons would dim their icons.
        self.toolbar_bg = vtk.vtkActor2D()
        pts = vtk.vtkPoints()
        pts.SetNumberOfPoints(4)
        poly = vtk.vtkPolyData()
        poly.SetPoints(pts)
        cells = vtk.vtkCellArray()
        cells.InsertNextCell(4, [0, 1, 2, 3])
        poly.SetPolys(cells)
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        self.toolbar_bg.SetMapper(mapper)
        bg = model.hex_rgb(tokens.color(self.theme, "bg.elevated")) / 255.0
        self.toolbar_bg.GetProperty().SetColor(*bg)
        self.toolbar_bg.GetProperty().SetOpacity(0.85)  # translucent bg.elevated (§7.5)
        self.renderer.AddViewProp(self.toolbar_bg)
        for key, icon_name, toggle in specs:
            rep = vtk.vtkTexturedButtonRepresentation2D()
            rep.SetNumberOfStates(2 if toggle else 1)
            rep.SetButtonTexture(0, _icon_image(icon_name, off, size))
            if toggle:
                rep.SetButtonTexture(1, _icon_image(icon_name, on, size))
            widget = vtk.vtkButtonWidget()
            widget.SetInteractor(self.plotter.iren.interactor)
            widget.SetRepresentation(rep)
            widget.AddObserver("StateChangedEvent", lambda w, _e, k=key: self._toolbar(k, w))
            widget.On()
            self.buttons[key] = widget
        self._sync_toggle_states()
        self.plotter.render_window.AddObserver(
            "WindowResizeEvent", lambda *_: self._place_toolbar()
        )
        self._place_toolbar()

    def _place_toolbar(self) -> None:
        w, h = self.plotter.render_window.GetSize()
        n = len(self.buttons)
        pad, icon = tokens.SPACING[1], TOOLBAR_ICON
        total = n * icon + (n + 1) * pad
        x0 = (w - total) / 2
        top = h - pad
        for i, widget in enumerate(self.buttons.values()):
            x = x0 + pad + i * (icon + pad)
            widget.GetRepresentation().PlaceWidget([x, x + icon, top - icon, top, 0, 0])
        pts = self.toolbar_bg.GetMapper().GetInput().GetPoints()
        y0 = top - icon - pad / 2
        for k, (x, y) in enumerate(((x0, y0), (x0 + total, y0), (x0 + total, h), (x0, h))):
            pts.SetPoint(k, x, y, 0)
        pts.Modified()

    def _sync_toggle_states(self) -> None:
        states = (
            {
                "grid": self.options["grid"],
                "frames": self.options["frames"],
                "trails": self.options["trails"],
                "ortho": self.camera().parallel,
                "2d": self.options["2d"],
                "fly": self.options["fly"],
            }
            if hasattr(self, "renderer")
            else {}
        )
        for key, value in states.items():
            if key in getattr(self, "buttons", {}):
                self.buttons[key].GetRepresentation().SetState(int(bool(value)))

    def _toolbar(self, key: str, widget: Any) -> None:
        state = bool(widget.GetRepresentation().GetState())
        if key == "frame_all":
            self.frame_all()
        elif key == "frame_selected":
            self.frame_selected()
        elif key == "preset":
            self._preset_i = (self._preset_i + 1) % len(PRESET_CYCLE)
            self.view_preset(PRESET_CYCLE[self._preset_i])
        elif key == "display":
            i = DISPLAY_MODES.index(self.display_mode)
            self.set_display_mode(DISPLAY_MODES[(i + 1) % len(DISPLAY_MODES)])
        elif key == "ortho":
            self.set_parallel(state)
        elif key == "2d":
            self.set_2d(state)
        else:
            self.set_option(key, state)
        self._sync_toggle_states()
        self.render()

    # ------------------------------------------------------------------ scene
    def load(self, desc: Description) -> None:
        """Build actors for a newly loaded scene."""
        keep_cam = self.camera() if self.desc is not None else None
        self._reset_state()
        self._build_static()
        self.desc = desc
        p = self.plotter
        edge_color = tokens.color(self.theme, "border.subtle")
        for i, g in enumerate(desc.geoms):
            mesh = model.geom_mesh(g)
            actor = p.add_mesh(
                mesh,
                color=g.rgba[:3],
                opacity=g.rgba[3],
                smooth_shading=g.kind != "box",
                name=f"geom{i}",
            )
            actor.user_matrix = model.geom_local(g)
            self.geom_actors.append(actor)
            entity = desc.entity_of_body(g.body)
            if entity is not None:
                self.actor_entity[id(actor)] = entity
                self.entity_actors.setdefault(entity, []).append(actor)
            if g.kind == "mesh":  # CAD look: subtle feature edges (§7.5)
                edges = mesh.extract_feature_edges(
                    feature_angle=30,
                    boundary_edges=False,
                    non_manifold_edges=False,
                    manifold_edges=False,
                )
                ea = p.add_mesh(
                    edges, color=edge_color, line_width=1, pickable=False, name=f"edge{i}"
                )
                ea.user_matrix = actor.user_matrix
                self.edge_actors.append((i, ea))
        palette = tokens.OKABE_ITO
        for k, e in enumerate(desc.entities):
            if e.kind == "entity" and e.has_marker:
                actor = p.add_mesh(
                    pv.Sphere(radius=tokens.TARGET_MARKER),
                    color=palette[k % len(palette)],
                    name=f"marker:{e.name}",
                )
                self.marker_actors[e.name] = actor
                self.actor_entity[id(actor)] = e.name
                self.entity_actors.setdefault(e.name, []).append(actor)
            seconds = desc.trails.get(e.name, (tokens.TRAIL_SECONDS, None))[0]
            if e.has_marker and seconds > 0:
                self.trails[e.name] = model.Trail(seconds=seconds)
        for b in range(len(desc.body_names)):
            axes = self._axes_poly(tokens.FRAME_AXIS_LENGTH)
            a = p.add_mesh(
                axes, scalars="rgb", rgb=True, line_width=2, pickable=False, name=f"frame{b}"
            )
            a.SetVisibility(self.options["frames"])
            self.frame_actors.append(a)
        for name, pose in desc.targets.items():
            self._add_target(name, pose)
        for name, (path, pose, scale, color) in desc.visuals.items():
            mesh = model.load_visual(path, scale)
            kw = {} if color is None else {"color": model.resolve_color(color, self.theme)}
            if color is None and "RGB" not in mesh.point_data and "RGBA" not in mesh.point_data:
                kw = {"color": tokens.color(self.theme, "text.secondary")}
            actor = p.add_mesh(mesh, pickable=False, name=f"visual:{name}", **kw)
            actor.user_matrix = np.array(pose)
            self.visual_actors[name] = actor
        for a in self.geom_actors + list(self.marker_actors.values()):
            a.SetPickable(True)
        if keep_cam is not None:
            self.set_camera(keep_cam)
        else:
            self._needs_framing = True  # bodies are posed by the first frame
        self.set_display_mode(self.display_mode)

    @staticmethod
    def _axes_poly(length: float) -> pv.PolyData:
        pts = np.array(
            [[0, 0, 0], [length, 0, 0], [0, 0, 0], [0, length, 0], [0, 0, 0], [0, 0, length]]
        )
        poly = pv.PolyData(pts, lines=np.array([2, 0, 1, 2, 2, 3, 2, 4, 5]))
        rgb = np.array([model.hex_rgb(tokens.AXIS_COLORS[a]) for a in "xxyyzz"])
        poly.point_data["rgb"] = rgb
        return poly

    def _add_target(self, name: str, pose: np.ndarray) -> None:
        actor = self.plotter.add_mesh(
            pv.Sphere(radius=tokens.TARGET_MARKER),
            color=tokens.color(self.theme, "accent"),
            opacity=0.6,
            pickable=False,
            name=f"target:{name}",
        )
        actor.user_matrix = np.array(pose)
        self.target_actors[name] = actor
        last = [0.0]

        def moved(matrix: np.ndarray, final: bool = False) -> None:
            now = time.monotonic()
            if final or now - last[0] >= 1 / tokens.VIEWPORT_FPS:
                last[0] = now
                self.target_moved.emit(name, np.array(matrix))

        widget = self.plotter.add_affine_transform_widget(
            actor,
            scale=_gizmo_scale(actor),
            always_visible=True,
            interact_callback=lambda m: moved(m),
            release_callback=lambda m: moved(m, True),
        )
        self.target_widgets.append(widget)

    # ------------------------------------------------------------------ per frame
    def update_frame(self, frame: Frame, trails: dict[str, np.ndarray] | None = None) -> None:
        """Move everything to a new state frame (called at the render rate). `trails` gives
        recorded trail paths by entity (from the timeline's history) instead of extending them."""
        if self.desc is None:
            return
        self.frame = frame
        if len(frame.bodies):
            body_m = model.body_world_matrices(frame.bodies)
            for g, actor in zip(self.desc.geoms, self.geom_actors, strict=True):
                ent = self.actor_entity.get(id(actor))
                if self.dragging is not None and ent == self.dragging:
                    continue  # the gizmo owns it until release
                actor.user_matrix = body_m[g.body] @ model.geom_local(g)
            for i, ea in self.edge_actors:
                ea.user_matrix = self.geom_actors[i].user_matrix
            if self.options["frames"]:
                for b, a in enumerate(self.frame_actors):
                    a.user_matrix = body_m[b]
        for name, actor in self.marker_actors.items():
            m = np.eye(4)
            m[:3, 3] = frame.markers[name]
            actor.user_matrix = m
        for name, trail in self.trails.items():
            if trails is not None and name in trails:
                trail.replace(frame.t, trails[name])
            else:
                trail.add(frame.t, frame.markers[name])
        if self.options["trails"]:
            self._update_trails()
        self._update_outlines()
        self._update_hud()
        if self._needs_framing:
            self._needs_framing = False
            self.frame_all()

    def trail_color(self, name: str) -> np.ndarray:
        """A trail's rgb (uint8): its `scene.trail(color=...)`, else the palette by order."""
        rgb = self.trail_colors.get(name)
        if rgb is None:
            custom = self.desc.trails.get(name, (0.0, None))[1] if self.desc else None
            k = list(self.trails).index(name)
            hex_color = (
                model.resolve_color(custom, self.theme)
                if custom is not None
                else tokens.OKABE_ITO[k % len(tokens.OKABE_ITO)]
            )
            rgb = self.trail_colors[name] = model.hex_rgb(hex_color)
        return rgb

    def _update_trails(self) -> None:
        poly = model.merged_trails(
            [(trail.array(), self.trail_color(name)) for name, trail in self.trails.items()]
        )
        actor = self.trail_actor
        if poly is None:
            if actor is not None:
                actor.SetVisibility(False)
            return
        if actor is None:
            actor = self.trail_actor = self.plotter.add_mesh(
                poly,
                scalars="rgb",
                rgb=True,
                line_width=tokens.TRAIL_WIDTH,
                pickable=False,
                name="trails",
                render=False,
                lighting=False,
            )
        else:
            actor.mapper.SetInputData(poly)
        actor.SetVisibility(True)

    def set_draws(self, draws: list[tuple]) -> None:
        """VP-07: replace the debug draws."""
        p = self.plotter
        for a in self.draw_actors:
            p.remove_actor(a, render=False)  # one render per frame, by the caller
        self.draw_actors = []
        self.draw_meshes = []
        g = model.draw_geometry(draws, self.theme)
        # Batched: one actor per line width / point size / label style, not one per draw, so a
        # controller that draws every tick stays cheap.
        common = {"pickable": False, "lighting": False, "reset_camera": False, "render": False}
        for width, items in _group(g.lines, key=lambda d: d[3]).items():
            pts = np.array([q for a, b, _c, _w in items for q in (a, b)], dtype=float)
            lines = np.hstack([[2, 2 * i, 2 * i + 1] for i in range(len(items))])
            poly = pv.PolyData(pts, lines=lines)
            poly.cell_data["rgb"] = np.array([pv.Color(c).int_rgb for _a, _b, c, _w in items])
            self.draw_meshes.append(poly)
            self.draw_actors.append(
                p.add_mesh(poly, scalars="rgb", rgb=True, line_width=width, **common)
            )
        arrows = []
        for a, b, color in g.arrows:
            length = float(np.linalg.norm(b - a))
            if length > 0:
                arrow = pv.Arrow(start=a, direction=b - a, scale=length)
                arrow.point_data["rgb"] = np.tile(pv.Color(color).int_rgb, (arrow.n_points, 1))
                arrows.append(arrow)
        if arrows:
            merged = arrows[0].merge(arrows[1:]) if len(arrows) > 1 else arrows[0]
            self.draw_meshes.append(merged)
            self.draw_actors.append(
                p.add_mesh(
                    merged,
                    scalars="rgb",
                    rgb=True,
                    pickable=False,
                    reset_camera=False,
                    render=False,
                )
            )
        for size, items in _group(g.points, key=lambda d: d[2]).items():
            cloud = pv.PolyData(np.array([pt for pt, _c, _s in items], dtype=float))
            cloud.point_data["rgb"] = np.array([pv.Color(c).int_rgb for _p, c, _s in items])
            self.draw_meshes.append(cloud)
            self.draw_actors.append(
                p.add_mesh(
                    cloud,
                    scalars="rgb",
                    rgb=True,
                    point_size=size,
                    render_points_as_spheres=True,
                    **common,
                )
            )
        for pts, color, size in g.clouds:  # VP-08: one actor per cloud, plain GL points
            cloud = pv.PolyData(np.ascontiguousarray(pts, dtype=np.float32))
            self.draw_meshes.append(cloud)
            self.draw_actors.append(
                p.add_mesh(cloud, color=color, point_size=size, style="points", **common)
            )
        for color, items in _group(g.ellipsoids, key=lambda d: d[2]).items():  # VP-09
            shells = []
            for center, axes, _c in items:
                shell = _UNIT_SPHERE.copy()
                shell.points = _UNIT_SPHERE.points @ axes.T + center
                shells.append(shell)
            merged = shells[0].merge(shells[1:]) if len(shells) > 1 else shells[0]
            self.draw_meshes.append(merged)
            self.draw_actors.append(
                p.add_mesh(
                    merged,
                    color=color,
                    opacity=tokens.ELLIPSOID_OPACITY,
                    pickable=False,
                    reset_camera=False,
                    render=False,
                )
            )
        for (color, size), items in _group(g.labels, key=lambda d: (d[2], d[3])).items():
            self.draw_meshes.append(pv.PolyData(np.array([pt for pt, *_ in items], dtype=float)))
            self.draw_actors.append(
                p.add_point_labels(
                    np.array([pt for pt, *_ in items], dtype=float),
                    [text for _p, text, *_ in items],
                    text_color=color,
                    font_size=int(size),
                    shape=None,
                    show_points=False,
                    always_visible=True,
                    reset_camera=False,
                    render=False,
                )
            )

    def _update_hud(self) -> None:
        now = time.monotonic()
        self._frames_drawn = [t for t in self._frames_drawn if now - t < 1.0] + [now]
        self.fps = float(len(self._frames_drawn))
        if now - self._hud_at < 1.0 / HUD_RATE:
            return
        self._hud_at = now
        f = self.frame
        lines = [f"FPS {self.fps:5.0f}"]
        if f is not None:
            speed = "max" if f.speed <= 0 else f"{f.speed:g}x"
            lines.append(f"RTF {f.rtf:5.2f} ({speed})")
            lines.append(f"t   {f.t:8.3f} s")
        if self.selection is not None:
            pos = self.entity_position(self.selection)
            if pos is not None:
                lines.append(f"{self.selection}: {pos[0]:+.3f} {pos[1]:+.3f} {pos[2]:+.3f} m")
        if self.cursor_world is not None:
            c = self.cursor_world
            lines.append(f"cursor {c[0]:+.3f} {c[1]:+.3f} {c[2]:+.3f} m")
        self.hud.SetInput("\n".join(lines))

    def render(self) -> None:
        self.plotter.render()

    # ------------------------------------------------------------------ entities
    def entity_position(self, name: str) -> np.ndarray | None:
        f = self.frame
        if f is None:
            return None
        if name in f.markers:
            return f.markers[name]
        actors = self.entity_actors.get(name)
        if actors:
            return np.array(actors[0].user_matrix)[:3, 3]
        return None

    def select(self, name: str | None, emit: bool = False) -> None:
        """DS-06: select from the viewport or from another panel."""
        if name == self.selection:
            return
        self.selection = name
        self._attach_body_gizmo()
        self._rebuild_outlines()
        if emit:
            self.selected.emit(name)
        self.render()

    def set_hover(self, name: str | None, emit: bool = False) -> None:
        if name == self.hover:
            return
        self.hover = name
        self._rebuild_outlines()
        if emit:
            self.hovered.emit(name)
        self.render()

    def _attach_body_gizmo(self) -> None:
        """VP-10: a free body gets the translate/rotate gizmo when selected."""
        if self.body_widget is not None:
            self.body_widget.remove()
            self.body_widget = None
        name = self.selection
        if self.desc is None or name is None:
            return
        info = next((e for e in self.desc.entities if e.name == name), None)
        if info is None or info.kind != "body" or not self.entity_actors.get(name):
            return
        actor = self.entity_actors[name][0]
        g_index = self.geom_actors.index(actor)
        local = model.geom_local(self.desc.geoms[g_index])

        def interact(matrix: np.ndarray) -> None:
            self.dragging = name

        def release(matrix: np.ndarray) -> None:
            body = np.array(matrix) @ np.linalg.inv(local)
            pos, quat = model.matrix_to_pose(body)
            self.dragging = None
            self.body_moved.emit(name, pos, quat)

        self.body_widget = self.plotter.add_affine_transform_widget(
            actor,
            scale=_gizmo_scale(actor),
            always_visible=True,
            interact_callback=interact,
            release_callback=release,
        )

    def _rebuild_outlines(self) -> None:
        for a in self.outline_actors:
            self.overlay.RemoveActor(a)
        self.outline_actors = []
        accent = model.hex_rgb(tokens.color(self.theme, "accent")) / 255.0
        for name, width, opacity in (
            (
                self.hover if self.hover != self.selection else None,
                tokens.OUTLINE_HOVER,
                tokens.HOVER_OPACITY,
            ),
            (self.selection, tokens.OUTLINE_SELECT, 1.0),
        ):
            if name is None:
                continue
            for src in self.entity_actors.get(name, []):
                sil = vtk.vtkPolyDataSilhouette()
                sil.SetInputData(src.mapper.GetInput())
                sil.SetCamera(self.renderer.GetActiveCamera())
                sil.SetProp3D(src)
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(sil.GetOutputPort())
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor(*accent)
                actor.GetProperty().SetLineWidth(width)
                actor.GetProperty().SetOpacity(opacity)
                actor.GetProperty().LightingOff()
                actor.SetUserMatrix(src.GetUserMatrix())
                actor._source = src  # noqa: SLF001 - follow the source each frame
                self.overlay.AddActor(actor)
                self.outline_actors.append(actor)

    def _update_outlines(self) -> None:
        for a in self.outline_actors:
            a.SetUserMatrix(a._source.GetUserMatrix())  # noqa: SLF001

    # ------------------------------------------------------------------ display options
    def set_option(self, key: str, value: bool) -> None:
        self.options[key] = value
        if key == "grid":
            self.grid_actor.SetVisibility(value)
            self.world_axes.SetVisibility(value)
        elif key == "frames":
            for a in self.frame_actors:
                a.SetVisibility(value)
            if value and self.frame is not None and len(self.frame.bodies):
                for b, m in enumerate(model.body_world_matrices(self.frame.bodies)):
                    self.frame_actors[b].user_matrix = m
        elif key == "trails":
            if self.trail_actor is not None:
                self.trail_actor.SetVisibility(value)
        self._sync_toggle_states()

    def set_display_mode(self, mode: str) -> None:
        """shaded+edges (default for CAD imports), shaded, or wireframe (§7.5)."""
        self.display_mode = mode
        for a in self.geom_actors:
            a.prop.style = "wireframe" if mode == "wireframe" else "surface"
        self._apply_geometry_mode()

    # ------------------------------------------------------------------ camera
    def camera(self) -> nav.Camera:
        c = self.renderer.GetActiveCamera()
        return nav.Camera(
            position=np.array(c.GetPosition()),
            focal=np.array(c.GetFocalPoint()),
            up=np.array(c.GetViewUp()),
            parallel=bool(c.GetParallelProjection()),
            parallel_scale=c.GetParallelScale(),
            view_angle=c.GetViewAngle(),
        )

    def set_camera(self, cam: nav.Camera) -> None:
        c = self.renderer.GetActiveCamera()
        c.SetPosition(*cam.position)
        c.SetFocalPoint(*cam.focal)
        c.SetViewUp(*cam.up)
        c.SetParallelProjection(cam.parallel)
        c.SetParallelScale(cam.parallel_scale)
        self.renderer.ResetCameraClippingRange()
        self.plotter.camera_set = True  # stop PyVista re-framing on every add_mesh (grid included)
        self.scale_bar.SetVisibility(cam.parallel)  # scale bar in orthographic and 2D (§7.5)
        # The HUD sits above the scale bar's labels while the bar is shown.
        self.hud.GetPositionCoordinate().SetValue(0.99, HUD_ABOVE_SCALE if cam.parallel else 0.01)

    def _bounds(self, actors: list[Any]) -> tuple[np.ndarray, float]:
        pts = []
        for a in actors:
            b = a.GetBounds()
            pts += [(b[0], b[2], b[4]), (b[1], b[3], b[5])]
        if not pts:
            return np.zeros(3), 1.0
        arr = np.array(pts)
        lo, hi = arr.min(axis=0), arr.max(axis=0)
        return (lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) / 2, 0.1)

    def frame_all(self) -> None:
        center, radius = self._bounds(self.geom_actors + list(self.marker_actors.values()))
        self.set_camera(nav.frame(center, radius * 1.1, self.camera()))

    def frame_selected(self) -> None:
        if self.selection is None:
            return self.frame_all()
        center, radius = self._bounds(self.entity_actors.get(self.selection, []))
        self.set_camera(nav.frame(center, radius * 1.5, self.camera()))
        return None

    def view_preset(self, name: str) -> None:
        if self.options["2d"]:
            return
        center, radius = self._bounds(self.geom_actors + list(self.marker_actors.values()))
        self.set_camera(nav.preset(name, center, radius * 1.1, self.camera()))

    def set_parallel(self, on: bool) -> None:
        if self.options["2d"] and not on:
            return  # 2D mode is always orthographic
        cam = self.camera()
        scale = cam.distance * np.tan(np.radians(cam.view_angle) / 2)
        self.set_camera(replace(cam, parallel=on, parallel_scale=scale))

    def set_2d(self, on: bool) -> None:
        """VP-03: top-down orthographic, rotation locked."""
        self.options["2d"] = on
        center, radius = self._bounds(self.geom_actors + list(self.marker_actors.values()))
        cam = self.camera()
        self.set_camera(
            nav.top_2d(center, radius * 1.1, cam)
            if on
            else nav.preset("iso", center, radius * 1.1, replace(cam, parallel=False))
        )
        # The ViewCube would rotate the locked 2D view: switch it off and hide it (turning the
        # widget off alone leaves it drawn).
        self.view_cube.SetEnabled(not on)
        self.view_cube.GetRepresentation().SetVisibility(not on)
        self._sync_toggle_states()

    # ------------------------------------------------------------------ input
    def _pick(self, x: int, y: int) -> tuple[np.ndarray | None, str | None]:
        if self.picker.Pick(x, y, 0, self.renderer):
            actor = self.picker.GetActor()
            return np.array(self.picker.GetPickPosition()), self.actor_entity.get(id(actor))
        return None, None

    def _ground_point(self, x: int, y: int) -> np.ndarray | None:
        """Where the ray under the cursor meets z = 0 (for zoom and pivot over empty space)."""
        r = self.renderer
        r.SetDisplayPoint(x, y, 0.0)
        r.DisplayToWorld()
        near = np.array(r.GetWorldPoint()[:3]) / r.GetWorldPoint()[3]
        r.SetDisplayPoint(x, y, 1.0)
        r.DisplayToWorld()
        far = np.array(r.GetWorldPoint()[:3]) / r.GetWorldPoint()[3]
        d = far - near
        if abs(d[2]) < 1e-12:
            return None
        s = -near[2] / d[2]
        return near + s * d if s > 0 else None

    def _world_under(self, x: int, y: int) -> np.ndarray:
        point, _ = self._pick(x, y)
        if point is None:
            point = self._ground_point(x, y)
        return point if point is not None else self.camera().focal

    def _gizmo_active(self) -> bool:
        widgets = [*self.target_widgets, *([self.body_widget] if self.body_widget else [])]
        return any(getattr(w, "_pressing_down", False) for w in widgets)

    def _on_mouse(self, iren: Any, event: str) -> None:
        if self._gizmo_drag and event == "MouseMoveEvent":
            return  # dragging a gizmo: no hover picks or camera moves
        x, y = iren.GetEventPosition()
        shift, ctrl = bool(iren.GetShiftKey()), bool(iren.GetControlKey())
        if event.startswith("MouseWheel"):
            notches = 1 if event == "MouseWheelForwardEvent" else -1
            point = self._world_under(x, y)
            self.set_camera(nav.zoom_to(self.camera(), point, notches, tokens.ZOOM_STEP))
            self.render()
            return
        if event.endswith("PressEvent"):
            if self._gizmo_active():
                self._gizmo_drag = True  # the gizmo owns this drag, not navigation or picking
                return
            button = event.removesuffix("ButtonPressEvent").lower()
            if button == "left":
                mode = "click"
            elif (
                (button == "right" and ctrl) or (button == "middle" and shift) or self.options["2d"]
            ):
                mode = "pan"
            else:
                mode = "orbit"
            self._drag = {
                "mode": mode,
                "start": (x, y),
                "last": (x, y),
                "moved": False,
                "pivot": self._world_under(x, y) if mode == "orbit" else None,
            }
            return
        if event.endswith("ReleaseEvent"):
            # PyVista's gizmo switches the interactor to its trackball style on release, which
            # would bring back VTK's own mouse and key handling: put SimView's style back.
            if iren.GetInteractorStyle() is not self._style:
                iren.SetInteractorStyle(self._style)
            if self._gizmo_drag:
                self._gizmo_drag = False
                return
            drag, self._drag = self._drag, None
            if drag is not None and drag["mode"] == "click" and not drag["moved"]:
                _, entity = self._pick(x, y)
                self.select(entity, emit=True)
            return
        # Mouse move
        drag = self._drag
        if drag is None:
            now = time.monotonic()
            if now - self._last_hover_pick >= HOVER_PICK_PERIOD:
                self._last_hover_pick = now
                point, entity = self._pick(x, y)
                self.cursor_world = point if point is not None else self._ground_point(x, y)
                self.set_hover(entity, emit=True)
            return
        lx, ly = drag["last"]
        dx, dy = x - lx, y - ly
        drag["last"] = (x, y)
        sx, sy = drag["start"]
        if abs(x - sx) + abs(y - sy) > CLICK_SLOP:
            drag["moved"] = True
        h = self.plotter.render_window.GetSize()[1]
        if drag["mode"] == "orbit":
            self.set_camera(
                nav.orbit(self.camera(), drag["pivot"], dx, -dy, tokens.ORBIT_DEG_PER_PX)
            )
        elif drag["mode"] == "pan":
            self.set_camera(nav.pan(self.camera(), dx, -dy, h))
        self.render()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        """Keys reach SimView first; VTK's defaults (q/e close the window) never see them."""
        if obj is self.plotter and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            return self.key(event.text().lower(), event.key())
        if obj is self.plotter and event.type() == QEvent.Type.KeyRelease:
            return True
        return super().eventFilter(obj, event)

    def key(self, text: str, code: int = 0) -> bool:
        """Viewport shortcuts (§7.8). Returns True when handled."""
        if self.options["fly"] and text in "wasdqe" and text:
            _, radius = self._bounds(self.geom_actors + list(self.marker_actors.values()))
            self.set_camera(nav.fly(self.camera(), text, radius * 2 * tokens.FLY_STEP))
        elif text == "f":
            self.frame_selected()
        elif text == "a":
            self.frame_all()
        elif text in ("1", "3", "7", "0"):
            self.view_preset({"1": "front", "3": "right", "7": "top", "0": "iso"}[text])
        elif code == Qt.Key.Key_Tab:
            self.set_2d(not self.options["2d"])
        else:
            return False
        self.render()
        return True

    def set_theme(self, theme: ThemeName) -> None:
        self.theme = theme
        desc, frame, cam = self.desc, self.frame, self.camera()
        if desc is not None:
            self.load(desc)
        else:
            self._build_static()
        self.set_camera(cam)
        if frame is not None:
            self.update_frame(frame)
        self.render()

    def close_viewport(self) -> None:
        self.plotter.close()
