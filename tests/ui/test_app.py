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
    # `simview` opens the app; `simview run ...` is the headless runner (D-011).
    assert data["project"]["scripts"]["simview"] == "simview.cli:main"


def test_cli_without_run_opens_app(monkeypatch):
    import simview.ui.app
    from simview.cli import main

    seen = []
    monkeypatch.setattr(simview.ui.app, "main", lambda argv: seen.append(argv) or 0)
    assert main(["--theme", "light"]) == 0
    assert seen == [["--theme", "light"]]


def test_scene_argument_opens_it_directly(monkeypatch, settings, qapp):
    """`simview scene.py` skips the start screen and loads the scene (M4)."""
    from pathlib import Path

    from simview.ui import app as app_mod

    opened = {}

    def fake_exec(self=None):
        window = opened["controller"].window
        opened["path"] = window.scene_path
        window.close_scene()
        return 0

    class Probe(app_mod.Controller):
        def __init__(self, s):
            super().__init__(settings)
            opened["controller"] = self

    monkeypatch.setattr(app_mod, "Controller", Probe)
    monkeypatch.setattr(type(qapp), "exec", fake_exec)
    scene = Path(__file__).parents[2] / "examples" / "ur5_ik_drag.py"
    assert app_mod.main([str(scene)]) == 0
    assert opened["path"] == scene
    assert not opened["controller"].start.isVisible()
    opened["controller"].window.close()
