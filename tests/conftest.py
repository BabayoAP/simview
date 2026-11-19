import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from qtpy.QtCore import QEvent, QSettings  # noqa: E402

from simview.ui.app import create_app  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = create_app([], "dark")
    yield app
    # Tear windows down while the QApplication is still alive. Leaving them to Python's
    # exit-time GC segfaults (Linux) or exits non-zero (Windows) after the tests pass.
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def pytest_collection_modifyitems(config, items):
    """Skip `network` tests when SIMVIEW_OFFLINE=1 (RB-11 downloads robots on first use)."""
    import os

    if os.environ.get("SIMVIEW_OFFLINE") != "1":
        return
    skip = pytest.mark.skip(reason="SIMVIEW_OFFLINE=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
