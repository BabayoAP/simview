"""DS-01, DS-14: token-based theme, no stray hex colors, WCAG contrast."""

import re
from pathlib import Path

import pytest

from simview.ui.theme import tokens
from simview.ui.theme.contrast import contrast_ratio
from simview.ui.theme.qss import build_qss

HEX = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b")
UI_DIR = Path(__file__).resolve().parents[2] / "src" / "simview" / "ui"


def test_themes_define_same_tokens():
    assert set(tokens.COLORS["dark"]) == set(tokens.COLORS["light"])
    for theme in tokens.COLORS.values():
        for value in theme.values():
            assert re.fullmatch(r"#[0-9A-F]{6}", value)


def test_prd_token_values():
    assert tokens.COLORS["dark"]["accent"] == "#0A84FF"
    assert tokens.COLORS["light"]["accent"] == "#0071E3"
    assert tokens.OKABE_ITO[0] == "#0072B2" and len(tokens.OKABE_ITO) == 7
    assert set(tokens.SPACING) == {4, 8, 12, 16, 24, 32}


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_qss_compiles_from_tokens(theme):
    qss = build_qss(theme)
    assert tokens.COLORS[theme]["bg.app"] in qss
    assert tokens.COLORS[theme]["accent"] in qss
    assert "{" in qss and qss.count("{") == qss.count("}")
    # every hex in the stylesheet comes from the token table
    allowed = set(tokens.COLORS[theme].values())
    assert set(HEX.findall(qss)) <= allowed


def test_no_hex_colors_outside_theme():
    offenders = []
    for path in UI_DIR.rglob("*.py"):
        if "theme" in path.relative_to(UI_DIR).parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HEX.search(line):
                offenders.append(f"{path.relative_to(UI_DIR)}:{n}: {line.strip()}")
    assert not offenders, "hard-coded colors outside ui/theme/:\n" + "\n".join(offenders)


def test_hex_lint_catches_a_color():
    assert HEX.search('label.setStyleSheet("color: #FF0000")')


TEXT = ("text.primary", "text.secondary")
SURFACES = ("bg.app", "bg.panel", "bg.elevated")


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("fg", TEXT)
@pytest.mark.parametrize("bg", SURFACES)
def test_text_contrast_wcag_aa(theme, fg, bg):
    c = tokens.COLORS[theme]
    assert contrast_ratio(c[fg], c[bg]) >= 4.5


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("bg", SURFACES)
def test_focus_ring_contrast_non_text(theme, bg):
    # WCAG 1.4.11: UI components need 3:1 against adjacent colors.
    c = tokens.COLORS[theme]
    assert contrast_ratio(c["accent"], c[bg]) >= 3.0


def test_contrast_ratio_reference_values():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_text_on_accent_contrast(theme):
    # Filled accent controls use `accent.fill` so white text clears AA (D-005).
    c = tokens.COLORS[theme]
    assert c["text.on_accent"] == "#FFFFFF"
    assert contrast_ratio(c["text.on_accent"], c["accent.fill"]) >= 4.5


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("bg", SURFACES)
def test_accent_fill_non_text_contrast(theme, bg):
    c = tokens.COLORS[theme]
    assert contrast_ratio(c["accent.fill"], c[bg]) >= 3.0


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("state", ["state.success", "state.warning", "state.error"])
def test_state_colors_non_text_contrast(theme, state):
    # State colors are status-only and paired with an icon/label (§7.9), so the
    # non-text 3:1 bar applies.
    c = tokens.COLORS[theme]
    assert contrast_ratio(c[state], c["bg.panel"]) >= 3.0


def test_light_success_is_text_safe():
    # D-005: light `state.success` darkened from #248A3D so it also works as text.
    c = tokens.COLORS["light"]
    for bg in SURFACES:
        assert contrast_ratio(c["state.success"], c[bg]) >= 4.5
