"""Theme: tokens, QSS, fonts, and icons. The only UI module allowed to hold style values."""

from __future__ import annotations

import tempfile
from functools import cache
from pathlib import Path

from qtpy.QtCore import QByteArray, QSize, Qt
from qtpy.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from qtpy.QtSvg import QSvgRenderer
from qtpy.QtWidgets import QApplication

from simview.ui.theme import tokens
from simview.ui.theme.qss import build_qss
from simview.ui.theme.tokens import ThemeName

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_DIR = ASSETS / "fonts"
ICON_DIR = ASSETS / "icons" / "lucide"

_current: ThemeName = "dark"


def load_fonts() -> list[str]:
    """Register the bundled fonts with Qt and return the loaded family names."""
    families: set[str] = set()
    for path in sorted(FONT_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families.update(QFontDatabase.applicationFontFamilies(font_id))
    return sorted(families)


def apply_theme(app: QApplication, theme: ThemeName) -> None:
    global _current
    _current = theme
    _icon.cache_clear()
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_qss(theme, _combo_arrow(theme), _check_mark(theme)))


def _icon_file(name: str, theme: ThemeName, token: str) -> str:
    """Write a tinted Lucide icon to a file for a QSS `image: url(...)` (QSS images need a
    path; styled combo boxes and check boxes drop the native glyphs) and return the path
    with forward slashes."""
    path = Path(tempfile.gettempdir()) / "simview-theme" / f"{name}-{theme}-{token}.svg"
    data = svg_for(name, tokens.color(theme, token))
    if not path.is_file() or path.read_bytes() != data:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path.as_posix()


def _combo_arrow(theme: ThemeName) -> str:
    return _icon_file("chevron-down", theme, "text.secondary")


def _check_mark(theme: ThemeName) -> str:
    return _icon_file("check", theme, "text.on_accent")


def build_palette(theme: ThemeName) -> QPalette:
    """The Qt palette from the tokens, for widgets the stylesheet doesn't reach (scroll areas,
    text views, plain frames). Without it they follow the OS (dark panels in the light theme
    when Windows is in dark mode)."""
    c = tokens.COLORS[theme]
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: "bg.app",
        QPalette.ColorRole.Base: "bg.panel",
        QPalette.ColorRole.AlternateBase: "bg.elevated",
        QPalette.ColorRole.Button: "bg.elevated",
        QPalette.ColorRole.ToolTipBase: "bg.elevated",
        QPalette.ColorRole.WindowText: "text.primary",
        QPalette.ColorRole.Text: "text.primary",
        QPalette.ColorRole.ButtonText: "text.primary",
        QPalette.ColorRole.ToolTipText: "text.primary",
        QPalette.ColorRole.PlaceholderText: "text.secondary",
        QPalette.ColorRole.Highlight: "accent.fill",
        QPalette.ColorRole.HighlightedText: "text.on_accent",
        QPalette.ColorRole.Accent: "accent",
        QPalette.ColorRole.Link: "accent",
        QPalette.ColorRole.Mid: "border.subtle",
    }
    for role, token in roles.items():
        pal.setColor(role, QColor(c[token]))
    return pal


def current_theme() -> ThemeName:
    return _current


def svg_for(name: str, color: str) -> bytes:
    """Lucide SVG source, tinted and set to the design stroke width."""
    src = (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
    src = src.replace("currentColor", color).replace(
        'stroke-width="2"', f'stroke-width="{tokens.ICON_STROKE}"'
    )
    return src.encode("utf-8")


def icon(name: str, token: str = "text.secondary", size: int = tokens.ICON_SIZE_TOOLBAR) -> QIcon:
    """A Lucide icon tinted with a color token from the current theme."""
    return _icon(name, tokens.color(_current, token), size)


@cache
def _icon(name: str, color: str, size: int) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg_for(name, color)))
    result = QIcon()
    for scale in (1, 2):  # crisp on high-DPI displays
        pm = QPixmap(QSize(size * scale, size * scale))
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        pm.setDevicePixelRatio(scale)
        result.addPixmap(pm)
    return result


__all__ = ["apply_theme", "current_theme", "icon", "load_fonts", "svg_for", "tokens"]
