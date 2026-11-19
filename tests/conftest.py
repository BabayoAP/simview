import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if "SIMVIEW_RUNS" not in os.environ:  # runs the app saves go to a temp folder, not the repo
    import tempfile

    os.environ["SIMVIEW_RUNS"] = tempfile.mkdtemp(prefix="simview-runs-")

import pytest  # noqa: E402
from qtpy.QtCore import QEvent, QSettings  # noqa: E402
from qtpy.QtWidgets import QWidget  # noqa: E402

from simview.ui.app import create_app  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = create_app([], "dark")
    yield app
    # Tear windows down while the QApplication is still alive. Leaving them to Python's
    # exit-time GC segfaults (Linux) or exits non-zero (Windows) after the tests pass.
    # Only unparented windows (a parented popup, like pyqtgraph's menus, goes with its owner),
    # and plain QWidgets last: pyqtgraph keeps a hidden, parentless options widget per plot
    # that must outlive the plot.
    for strays in (False, True):
        for widget in app.topLevelWidgets():
            if widget.parent() is None and (type(widget) is QWidget) == strays:
                widget.close()
                widget.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def pytest_collection_modifyitems(config, items):
    """Skip `network` tests when SIMVIEW_OFFLINE=1 (RB-11 downloads robots on first use), and
    `gl` tests unless SIMVIEW_GL=1 (they need a real OpenGL display)."""
    import os

    offline = os.environ.get("SIMVIEW_OFFLINE") == "1"
    gl = os.environ.get("SIMVIEW_GL") == "1"
    for item in items:
        if offline and "network" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="SIMVIEW_OFFLINE=1"))
        if not gl and "gl" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="needs an OpenGL display: set SIMVIEW_GL=1"))
