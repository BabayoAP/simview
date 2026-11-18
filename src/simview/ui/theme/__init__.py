"""Theme: tokens, QSS, fonts, and icons. The only UI module allowed to hold style values."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from qtpy.QtCore import QByteArray, QSize, Qt
from qtpy.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
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
    app.setStyleSheet(build_qss(theme))


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
