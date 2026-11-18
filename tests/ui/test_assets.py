"""DS-02: bundled Inter, JetBrains Mono, and Lucide icons."""

from qtpy.QtGui import QFontDatabase

from simview.ui import theme
from simview.ui.theme import FONT_DIR, ICON_DIR, tokens


def test_fonts_bundled_with_licenses():
    names = {p.name for p in FONT_DIR.iterdir()}
    for f in (
        "Inter-Regular.ttf",
        "Inter-SemiBold.ttf",
        "JetBrainsMono-Regular.ttf",
        "JetBrainsMono-SemiBold.ttf",
        "Inter-OFL.txt",
        "JetBrainsMono-OFL.txt",
    ):
        assert f in names


def test_fonts_register_with_qt(qapp):
    theme.load_fonts()
    families = set(QFontDatabase.families())
    assert tokens.FONT_UI in families
    assert tokens.FONT_MONO in families


def test_lucide_icons_bundled():
    assert (ICON_DIR / "LICENSE").exists()
    assert len(list(ICON_DIR.glob("*.svg"))) > 1000


def test_icon_tinted_with_token_and_thin_stroke(qapp):
    svg = theme.svg_for("play", tokens.color("dark", "accent")).decode()
    assert tokens.color("dark", "accent") in svg
    assert "currentColor" not in svg
    assert f'stroke-width="{tokens.ICON_STROKE}"' in svg


def test_icon_renders(qapp):
    ic = theme.icon("play", "accent")
    assert not ic.isNull()
    assert not ic.pixmap(tokens.ICON_SIZE_TOOLBAR).isNull()
