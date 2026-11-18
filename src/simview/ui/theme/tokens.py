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

# Motion (ms).
MOTION_FAST: Final = 150
MOTION_PANEL: Final = 250


def color(theme: ThemeName, token: str) -> str:
    """Return the hex value of a semantic color token."""
    return COLORS[theme][token]
