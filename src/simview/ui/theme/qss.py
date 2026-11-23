"""Compile design tokens into a Qt stylesheet (DS-01)."""

from __future__ import annotations

from simview.ui.theme import tokens as t
from simview.ui.theme.tokens import ThemeName


def build_qss(theme: ThemeName, combo_arrow: str | None = None) -> str:
    c = t.COLORS[theme]
    arrow = (
        f"QComboBox::down-arrow {{ image: url({combo_arrow}); "
        f"width: {t.ICON_SIZE_INLINE}px; height: {t.ICON_SIZE_INLINE}px; }}"
        if combo_arrow
        else ""
    )
    body = t.FONT_SIZE["body"]
    on_accent = c["text.on_accent"]
    return f"""
* {{
    font-family: "{t.FONT_UI}";
    font-size: {body}px;
    color: {c["text.primary"]};
}}
QMainWindow, QWidget#StartScreen, QWidget#CentralArea {{
    background: {c["bg.app"]};
}}
QDockWidget, QDockWidget > QWidget {{
    background: {c["bg.panel"]};
}}
QDockWidget::title {{
    background: {c["bg.panel"]};
    padding: {t.SPACING[1]}px {t.SPACING[2]}px;
    border-bottom: {t.HAIRLINE}px solid {c["border.subtle"]};
    font-size: {t.FONT_SIZE["panel_title"]}px;
    font-weight: {t.WEIGHT_SEMIBOLD};
}}
QMainWindow::separator {{
    background: {c["border.subtle"]};
    width: {t.HAIRLINE}px;
    height: {t.HAIRLINE}px;
}}
QToolBar {{
    background: {c["bg.panel"]};
    border: none;
    border-bottom: {t.HAIRLINE}px solid {c["border.subtle"]};
    spacing: {t.SPACING[1]}px;
    padding: {t.SPACING[0]}px {t.SPACING[1]}px;
}}
QToolBar::separator {{
    background: {c["border.subtle"]};
    width: {t.HAIRLINE}px;
    margin: {t.SPACING[0]}px {t.SPACING[1]}px;
}}
QToolBar QToolButton {{
    min-height: {t.CONTROL_HEIGHT_COMPACT}px;
    max-height: {t.CONTROL_HEIGHT_COMPACT}px;
    padding: 0 {t.SPACING[1]}px;
    border-radius: {t.RADIUS_CONTROL}px;
    border: {t.FOCUS_RING}px solid transparent;
    background: transparent;
}}
QToolButton:hover, QPushButton:hover {{
    background: {c["bg.elevated"]};
}}
QToolBar QToolButton:checked {{
    background: {c["bg.elevated"]};
    color: {c["accent"]};
}}
QToolButton:focus, QPushButton:focus, QLineEdit:focus, QListWidget:focus {{
    border: {t.FOCUS_RING}px solid {c["accent"]};
}}
QPushButton {{
    min-height: {t.CONTROL_HEIGHT - 2 * t.FOCUS_RING}px;
    padding: 0 {t.SPACING[2]}px;
    border-radius: {t.RADIUS_CONTROL}px;
    border: {t.FOCUS_RING}px solid {c["border.subtle"]};
    background: {c["bg.panel"]};
}}
QPushButton[primary="true"] {{
    background: {c["accent.fill"]};
    border-color: {c["accent.fill"]};
    color: {on_accent};
    font-weight: {t.WEIGHT_SEMIBOLD};
}}
QLineEdit {{
    min-height: {t.CONTROL_HEIGHT - 2 * t.FOCUS_RING}px;
    padding: 0 {t.SPACING[1]}px;
    border-radius: {t.RADIUS_CONTROL}px;
    border: {t.FOCUS_RING}px solid {c["border.subtle"]};
    background: {c["bg.app"]};
    selection-background-color: {c["accent.fill"]};
    selection-color: {on_accent};
}}
QComboBox {{
    min-height: {t.CONTROL_HEIGHT - 2 * t.FOCUS_RING}px;
    padding: 0 {t.SPACING[1]}px;
    border-radius: {t.RADIUS_CONTROL}px;
    border: {t.FOCUS_RING}px solid {c["border.subtle"]};
    background: {c["bg.app"]};
}}
QToolBar QComboBox {{
    min-height: {t.CONTROL_HEIGHT_COMPACT - 2 * t.FOCUS_RING}px;
}}
QComboBox::drop-down {{
    border: none;
    background: transparent;
    width: {t.SPACING[3]}px;
}}
{arrow}
QComboBox:focus {{
    border-color: {c["accent"]};
}}
QComboBox QAbstractItemView {{
    background: {c["bg.elevated"]};
    border: {t.HAIRLINE}px solid {c["border.subtle"]};
    selection-background-color: {c["accent.fill"]};
    selection-color: {on_accent};
}}
QLabel[role="secondary"] {{
    color: {c["text.secondary"]};
    font-size: {t.FONT_SIZE["secondary"]}px;
}}
QLabel[role="caption"] {{
    color: {c["text.secondary"]};
    font-size: {t.FONT_SIZE["caption"]}px;
}}
QLabel[role="title"] {{
    font-size: {t.FONT_SIZE["title"]}px;
    font-weight: {t.WEIGHT_SEMIBOLD};
}}
QLabel[role="panelTitle"] {{
    font-size: {t.FONT_SIZE["panel_title"]}px;
    font-weight: {t.WEIGHT_SEMIBOLD};
}}
QLabel[role="mono"] {{
    font-family: "{t.FONT_MONO}";
    color: {c["text.secondary"]};
    font-size: {t.FONT_SIZE["secondary"]}px;
}}
QLabel[role="error"] {{
    color: {c["state.error"]};
    font-size: {t.FONT_SIZE["secondary"]}px;
}}
QLineEdit[role="mono"] {{
    font-family: "{t.FONT_MONO}";
    font-size: {t.FONT_SIZE["secondary"]}px;
}}
QPlainTextEdit[role="code"], QTextEdit[role="code"] {{
    font-family: "{t.FONT_MONO}";
    font-size: {t.FONT_SIZE["secondary"]}px;
}}
QFrame#Card {{
    background: {c["bg.panel"]};
    border: {t.HAIRLINE}px solid {c["border.subtle"]};
    border-radius: {t.RADIUS_FLOATING}px;
}}
QFrame#Card:hover {{
    border-color: {c["accent"]};
}}
QFrame#CommandPalette {{
    background: {c["bg.elevated"]};
    border: {t.HAIRLINE}px solid {c["border.subtle"]};
    border-radius: {t.RADIUS_FLOATING}px;
}}
QListWidget {{
    background: transparent;
    border: {t.FOCUS_RING}px solid transparent;
    outline: none;
}}
QListWidget::item {{
    min-height: {t.CONTROL_HEIGHT}px;
    padding: 0 {t.SPACING[1]}px;
    border-radius: {t.RADIUS_CONTROL}px;
}}
QListWidget::item:selected {{
    background: {c["accent.fill"]};
    color: {on_accent};
}}
QTabWidget::pane {{
    border: none;
}}
QTabBar::tab {{
    background: transparent;
    padding: {t.SPACING[1]}px {t.SPACING[2]}px;
    color: {c["text.secondary"]};
    border-bottom: {t.FOCUS_RING}px solid transparent;
}}
QTabBar::tab:selected {{
    color: {c["text.primary"]};
    border-bottom-color: {c["accent"]};
}}
QMenuBar, QMenu {{
    background: {c["bg.elevated"]};
}}
QMenu::item:selected {{
    background: {c["accent.fill"]};
    color: {on_accent};
}}
QTreeView::item {{
    min-height: {t.CONTROL_HEIGHT_COMPACT - t.SPACING[0]}px;
}}
QTreeView::item:hover {{
    background: {c["bg.elevated"]};
}}
QTreeView::item:selected {{
    background: {c["accent.fill"]};
    color: {on_accent};
}}
QSlider::groove:horizontal {{
    height: {t.SLIDER_GROOVE}px;
    background: {c["border.subtle"]};
    border-radius: {t.SLIDER_GROOVE // 2}px;
}}
QSlider::sub-page:horizontal {{
    background: {c["accent"]};
    border-radius: {t.SLIDER_GROOVE // 2}px;
}}
QSlider::handle:horizontal {{
    width: {t.SLIDER_HANDLE}px;
    margin: -{(t.SLIDER_HANDLE - t.SLIDER_GROOVE) // 2}px 0;
    background: {c["text.primary"]};
    border: {t.HAIRLINE}px solid {c["border.subtle"]};
    border-radius: {t.SLIDER_HANDLE // 2}px;
}}
QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {{
    border-color: {c["accent"]};
}}
QSlider::sub-page:horizontal:disabled {{
    background: {c["text.secondary"]};
}}
QStatusBar {{
    background: {c["bg.panel"]};
    border-top: {t.HAIRLINE}px solid {c["border.subtle"]};
    color: {c["text.secondary"]};
}}
"""
