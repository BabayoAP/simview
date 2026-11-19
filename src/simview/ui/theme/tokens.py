"""Design tokens (PRD §7.3). The only place visual values are defined."""

from __future__ import annotations

from typing import Final, Literal

ThemeName = Literal["dark", "light"]

COLORS: Final[dict[ThemeName, dict[str, str]]] = {
    "dark": {
        "bg.app": "#1C1C1E",
        "bg.panel": "#242426",
        "bg.elevated": "#2C2C2E",
        "border.subtle": "#3A3A3C",
        "text.primary": "#F5F5F7",
        "text.secondary": "#A1A1A6",
        "accent": "#0A84FF",
        "accent.fill": "#0A6FEE",
        "text.on_accent": "#FFFFFF",
        "state.success": "#30D158",
        "state.warning": "#FFD60A",
        "state.error": "#FF453A",
        "viewport.bg_top": "#2A2A2E",
        "viewport.grid_major": "#5A5A60",
        "viewport.grid_minor": "#3C3C42",
    },
    "light": {
        "bg.app": "#F5F5F7",
        "bg.panel": "#FFFFFF",
        "bg.elevated": "#FFFFFF",
        "border.subtle": "#D2D2D7",
        "text.primary": "#1D1D1F",
        "text.secondary": "#6E6E73",
        "accent": "#0071E3",
        "accent.fill": "#0071E3",
        "text.on_accent": "#FFFFFF",
        "state.success": "#1F7A35",
        "state.warning": "#B25000",
        "state.error": "#D70015",
        "viewport.bg_top": "#FFFFFF",
        "viewport.grid_major": "#A8A8B0",
        "viewport.grid_minor": "#D8D8DE",
    },
}

# Code colors (SC-01, SC-02: editor and console), each >= 4.5:1 on bg.panel and bg.elevated.
# Plain code uses text.primary.
SYNTAX: Final[dict[ThemeName, dict[str, str]]] = {
    "dark": {
        "keyword": "#FF7AB2",
        "string": "#FC6A5D",
        "number": "#D9C97C",
        "comment": "#8E9AA6",
        "function": "#67B7FF",
        "class": "#5DD8FF",
        "builtin": "#B78CF2",
        "decorator": "#FD8F3F",
    },
    "light": {
        "keyword": "#AD3DA4",
        "string": "#C41A16",
        "number": "#1C00CF",
        "comment": "#5D6C79",
        "function": "#0F68A0",
        "class": "#0B4F79",
        "builtin": "#6C36A9",
        "decorator": "#8A4500",
    },
}

# Fixed engineering conventions (do not change).
AXIS_COLORS: Final[dict[str, str]] = {"x": "#FF0000", "y": "#00FF00", "z": "#0000FF"}
OKABE_ITO: Final[tuple[str, ...]] = (
    "#0072B2",
    "#E69F00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#D55E00",
    "#F0E442",
)

# Typography.
FONT_UI: Final = "Inter"
FONT_MONO: Final = "JetBrains Mono"
FONT_SIZE: Final[dict[str, int]] = {
    "caption": 11,
    "secondary": 12,
    "body": 13,
    "panel_title": 15,
    "title": 20,
}
WEIGHT_REGULAR: Final = 400
WEIGHT_SEMIBOLD: Final = 600

# Spacing and shape (px).
SPACING: Final[tuple[int, ...]] = (4, 8, 12, 16, 24, 32)
RADIUS_CONTROL: Final = 6
RADIUS_FLOATING: Final = 10
CONTROL_HEIGHT: Final = 28
CONTROL_HEIGHT_COMPACT: Final = 24
HAIRLINE: Final = 1
SLIDER_GROOVE: Final = 4  # px, slider track (timeline scrubber, inspector sliders)
SLIDER_HANDLE: Final = 12  # px, slider knob
FOCUS_RING: Final = 2

# Layout (px), default Simulate workspace (§7.4).
WINDOW_DEFAULT: Final = (1440, 900)
SIDE_PANEL_WIDTH: Final = (180, 200)  # left, right
TIMELINE_HEIGHT: Final = 56
BOTTOM_ROW_HEIGHT: Final = 200
PLOTS_SHARE: Final = 0.75  # plots vs console width in the bottom row
PALETTE_WIDTH: Final = 560
START_WINDOW: Final = (880, 600)
TEMPLATE_CARD: Final = (180, 150)
TEMPLATE_GLYPH: Final = 48

# Icons.
ICON_SIZE_TOOLBAR: Final = 16
ICON_SIZE_START: Final = 20
ICON_STROKE: Final = 1.5

# Viewport (§7.5).
VIEWPORT_MSAA: Final = 4  # anti-aliasing samples
VIEWPORT_FPS: Final = 60  # render and state-poll rate
GRID_EXTENT: Final = 20.0  # m, half-width of the ground grid
GRID_MAJOR: Final = 1.0  # m between major lines
GRID_MINOR: Final = 0.1  # m between minor lines
GRID_FADE: Final = (0.25, 1.0)  # fraction of the extent where lines start / finish fading out
TRAIL_SECONDS: Final = 5.0  # default trail length (VP-04)
TRAIL_WIDTH: Final = 2  # px
OUTLINE_HOVER: Final = 1  # px, at HOVER_OPACITY
OUTLINE_SELECT: Final = 2  # px
HOVER_OPACITY: Final = 0.5
FRAME_AXIS_LENGTH: Final = 0.1  # m, "show frames" RGB axes on every body
WORLD_AXIS_LENGTH: Final = 0.25  # m, RGB axes at the world origin (VP-01)
GIZMO_SIZE: Final = 0.2  # m, length of the translate/rotate gizmo arrows (VP-10)
TARGET_MARKER: Final = 0.03  # m, radius of a drag target's sphere
ORBIT_DEG_PER_PX: Final = 0.4
ZOOM_STEP: Final = 0.15  # fraction of the distance to the cursor point per wheel notch
FLY_STEP: Final = 0.02  # fraction of the scene size per fly-mode key event
DRAW_POINT_SIZE: Final = 8  # px, debug-draw default (VP-07)

# Timeline (§7.4) and plots (§7.6).
TIMELINE_READOUT_WIDTH: Final = 230  # px, fits "t = 1234.567 s / 1234.567 s  replay"
PLOT_LINE_WIDTH: Final = 1.5  # px, data
PLOT_REF_WIDTH: Final = 1  # px, reference lines and the time cursor
PLOT_SELECTED_WIDTH: Final = 3  # px, traces of the selected entity (DS-06)
PLOT_GRID_ALPHA: Final = 0.35  # light grid
PLOT_FILL_ALPHA: Final = 90  # 0-255, histogram bar fill
PLOT_SYMBOL_SIZE: Final = 5  # px, scatter points
PLOT_CURSOR_SYMBOL: Final = 9  # px, the time-cursor dot on XY and scatter plots
PLOT_MIN_HEIGHT: Final = 100  # one plot fits the default bottom row without scrolling
PLOT_FPS: Final = 30  # redraw rate while data streams in (DA-01)
PLOT_EXPORT_SCALE: Final = 2  # PNG exports at 2x the on-screen size
RUNS_LIST_MIN_HEIGHT: Final = 40  # px, the Runs panel's lists (they scroll below this)

# Motion (ms).
MOTION_FAST: Final = 150
MOTION_PANEL: Final = 250


def color(theme: ThemeName, token: str) -> str:
    """Return the hex value of a semantic color token."""
    return COLORS[theme][token]


# Console, editor, and workspace (SC-01-SC-03).
EDITOR_TAB_SPACES: Final = 4
EDITOR_GUTTER_PAD: Final = 8  # px either side of the line numbers
WORKSPACE_PREVIEW_CHARS: Final = 60  # value preview length in the workspace browser
WORKSPACE_VALUE_WIDTH: Final = 96  # px, starting width of the Value column (resizable)
ARRAY_VIEWER_SIZE: Final = (640, 420)
ARRAY_VIEWER_MAX_CELLS: Final = 1_000_000  # bigger arrays show their first rows
