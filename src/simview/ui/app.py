"""Application entry point: start screen first, then the main window."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qtpy.QtCore import QSettings, Qt
from qtpy.QtGui import QFont
from qtpy.QtWidgets import QApplication

from simview.ui import theme
from simview.ui.main_window import UNTITLED, MainWindow
from simview.ui.start_screen import StartScreen, add_recent_project
from simview.ui.theme import tokens
from simview.ui.theme.tokens import ThemeName


def default_settings() -> QSettings:
    return QSettings("SimView", "SimView")


def create_app(argv: list[str] | None = None, theme_name: ThemeName | None = None) -> QApplication:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        # VTK's view is a native window; by default Qt then makes its siblings (the docks)
        # native too, and those skip their themed background (black panels in the light theme).
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("SimView")
    app.setOrganizationName("SimView")
    theme.load_fonts()
    app.setFont(QFont(tokens.FONT_UI, tokens.FONT_SIZE["body"]))
    theme.apply_theme(app, theme_name or "dark")
    return app


class Controller:
    """Switches between the start screen and the main window."""

    def __init__(self, settings: QSettings) -> None:
        self.settings = settings
        self.window: MainWindow | None = None
        self.start = StartScreen(settings)
        self.start.template_chosen.connect(self.open_template)
        self.start.new_scene.connect(lambda: self.open_window(UNTITLED, "Untitled"))
        self.start.project_opened.connect(self.open_project)

    def open_template(self, template_id: str) -> None:
        from simview.templates import scene_path, template

        spec = template(template_id)
        title = spec.title if spec is not None else template_id
        window = self.open_window(f"template/{template_id}", title)
        path = scene_path(template_id)
        if path is not None:
            window.load_scene(path)  # D-098

    def open_project(self, path: str) -> None:
        add_recent_project(self.settings, path)
        self.start.refresh_recent()
        self.open_window(path, Path(path).name).open_project(path)

    def open_window(self, project_key: str, title: str) -> MainWindow:
        if self.window is not None:
            self.window.close()
        self.window = MainWindow(self.settings, project_key, title)
        self.window.show_start_screen.connect(self.show_start)
        self.window.show()
        self.start.hide()
        return self.window

    def show_start(self) -> None:
        self.start.refresh_recent()
        self.start.show()
        self.start.raise_()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simview")
    parser.add_argument("--theme", choices=["dark", "light"], help="override the saved theme")
    parser.add_argument("scene", nargs="?", type=Path, help="a scene.py file to open directly")
    args, qt_args = parser.parse_known_args(argv)
    settings = default_settings()
    from simview.toolboxes.registry import discover

    discover()  # TB-01: find installed toolboxes at startup
    chosen: ThemeName = args.theme or str(settings.value("theme", "dark"))  # type: ignore[assignment]
    app = create_app([sys.argv[0], *qt_args], chosen)
    controller = Controller(settings)
    if args.scene is not None:
        if not args.scene.is_file():
            parser.error(f"no scene file at {args.scene}")
        controller.open_window(UNTITLED, args.scene.name).load_scene(args.scene)
    else:
        controller.start.show()
    from simview.ui.console.kernel import shutdown

    app.aboutToQuit.connect(shutdown)
    return app.exec()
