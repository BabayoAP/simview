import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from qtpy.QtCore import QSettings  # noqa: E402

from simview.ui.app import create_app  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return create_app([], "dark")


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
