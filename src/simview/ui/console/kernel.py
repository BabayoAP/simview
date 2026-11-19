"""The IPython console (SC-01): qtconsole on an in-process ipykernel (PRD §8.1, D-008).

The kernel lives in the UI process (one per process: IPython's shell is a singleton), so the
console sees the same `simview` module the UI uses. It reaches the running scene through the
`sim` handle (`handle.py`), which talks to the sim process. Output and tracebacks from the sim
process are written above the prompt (NF-10).
"""

from __future__ import annotations

import html
import os
from collections.abc import Callable
from functools import cache
from typing import Any

os.environ.setdefault("PYDEVD_DISABLE_FILE_VALIDATION", "1")  # no debugger warning on start

from qtconsole.inprocess import QtInProcessKernelManager  # noqa: E402
from qtconsole.rich_jupyter_widget import RichJupyterWidget  # noqa: E402
from qtpy.QtCore import Signal  # noqa: E402
from qtpy.QtGui import QFont  # noqa: E402
from qtpy.QtWidgets import QWidget  # noqa: E402

from simview.ui import theme  # noqa: E402
from simview.ui.theme import tokens  # noqa: E402
from simview.ui.theme.syntax import console_stylesheet, pygments_style  # noqa: E402
from simview.ui.theme.tokens import ThemeName  # noqa: E402

BANNER = (
    "SimView console. `sim` is the running simulation (sim.params, sim.state(), sim.data()),\n"
    "`sv` is simview, `np` is NumPy.\n"
)


@cache
def kernel_manager() -> QtInProcessKernelManager:
    km = QtInProcessKernelManager()
    km.start_kernel(show_banner=False)
    km.kernel.gui = "qt"
    km.kernel.shell.banner1 = BANNER  # the kernel's banner (instead of IPython's tips)
    km.kernel.shell.banner2 = ""
    km.kernel.shell.enable_tip = False
    import numpy

    import simview

    km.kernel.shell.push({"np": numpy, "sv": simview}, interactive=False)
    return km


class ConsoleWidget(RichJupyterWidget):
    """The console panel. `executed` fires after every cell, from any source (typed, the
    editor's Run, an import), so the workspace browser can refresh."""

    executed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.banner = ""  # the kernel sends BANNER
        font = QFont(tokens.FONT_MONO)
        font.setPixelSize(tokens.FONT_SIZE["secondary"])
        self.font = font
        self._control.setProperty("role", "code")  # mono font from the stylesheet
        km = kernel_manager()
        self.kernel_manager = km
        self.kernel_client = km.client()
        self.kernel_client.start_channels()
        self.set_theme(theme.current_theme())
        self._hook: Callable[[], None] = self.executed.emit
        self.shell.events.register("post_execute", self._hook)
        self.destroyed.connect(lambda _o=None, hook=self._hook: _unregister(hook))

    @property
    def shell(self) -> Any:
        return self.kernel_manager.kernel.shell

    @property
    def namespace(self) -> dict[str, Any]:
        return self.shell.user_ns

    @property
    def hidden(self) -> dict[str, Any]:
        """Names the workspace browser doesn't list (IPython internals, `sim`, `sv`, `np`)."""
        return self.shell.user_ns_hidden

    def set_theme(self, name: ThemeName) -> None:
        self.style_sheet = console_stylesheet(name)
        self._highlighter.set_style(pygments_style(name))
        self._control.document().setDefaultStyleSheet(self.style_sheet)

    def push(self, values: dict[str, Any], hidden: bool = False) -> None:
        """Put variables in the console's namespace (hidden ones stay out of the workspace)."""
        self.shell.push(values, interactive=not hidden)
        self.executed.emit()

    def run_code(self, source: str) -> None:
        """Run code as if typed at the prompt (shown in the console with its output)."""
        self.execute(source, hidden=False)

    def write(self, text: str, token: str = "text.primary") -> None:
        """Text from the sim process, above the prompt (NF-10), on a line of its own."""
        pos = self._append_before_prompt_pos
        before = self._control.document().characterAt(pos - 1) if pos > 0 else "\n"
        if before not in ("\n", "\u2029"):  # Qt stores line breaks as U+2029
            text = "\n" + text
        if token == "text.primary":
            self._append_plain_text(text, before_prompt=True)
            return
        color = tokens.color(theme.current_theme(), token)
        body = html.escape(text).replace(" ", "&nbsp;").replace("\n", "<br>")
        self._append_html(f'<span style="color:{color}">{body}</span>', before_prompt=True)

    def text(self) -> str:
        """Everything shown so far (tests)."""
        return self._control.toPlainText()


def _unregister(hook: Callable[[], None]) -> None:
    try:
        kernel_manager().kernel.shell.events.unregister("post_execute", hook)
    except ValueError:
        pass
