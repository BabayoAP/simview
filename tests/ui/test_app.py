"""M1 done-when: launches into the start screen in dark and light themes."""

import pytest

from simview.ui import theme
from simview.ui.app import Controller
from simview.ui.main_window import MainWindow
from simview.ui.theme import tokens


@pytest.mark.parametrize("name", ["dark", "light"])
def test_launch_into_start_screen(qapp, settings, name):
    theme.apply_theme(qapp, name)
    c = Controller(settings)
    c.start.show()
    qapp.processEvents()
    assert c.start.isVisible() and c.window is None
    assert tokens.COLORS[name]["bg.app"] in qapp.styleSheet()
    c.start.close()
    theme.apply_theme(qapp, "dark")


def test_theme_toggle_persists(qapp, settings):
    w = MainWindow(settings)
    w.toggle_theme()
    assert theme.current_theme() == "light"
    assert settings.value("theme") == "light"
    w.toggle_theme()
    assert theme.current_theme() == "dark"


def test_cli_entry_point_declared():
    import tomllib
    from pathlib import Path

    data = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["simview"] == "simview.ui.app:main"
