"""The code editor (SC-02): Python highlighting, line numbers, run file, and run selection.

A QPlainTextEdit with a Pygments highlighter (PRD §8.1; no QScintilla). Run File saves the
file and runs it in the console with `%run`, so its variables land in the workspace; Run
Selection runs the selected lines (or the current line) as if typed at the prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pygments.lexers import PythonLexer
from pygments.token import _TokenType
from qtpy.QtCore import QRect, QSize, Qt, Signal
from qtpy.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from simview.ui import theme
from simview.ui.theme import icon, tokens
from simview.ui.theme.syntax import pygments_style
from simview.ui.theme.tokens import ThemeName

RUN_FILE_KEY = "F5"
RUN_SELECTION_KEY = "F9"


class PythonHighlighter(QSyntaxHighlighter):
    """Pygments tokens -> character formats. Each block (line) is lexed with the state of
    the previous one, so multi-line strings stay colored."""

    def __init__(self, document: QTextDocument, theme_name: ThemeName) -> None:
        super().__init__(document)
        self.lexer = PythonLexer(stripnl=False, ensurenl=False)
        self.formats: dict[_TokenType, QTextCharFormat] = {}
        self.set_theme(theme_name)

    def set_theme(self, theme_name: ThemeName) -> None:
        style = pygments_style(theme_name)
        self.formats = {}
        for token, spec in style:
            fmt = QTextCharFormat()
            if spec["color"]:
                fmt.setForeground(QColor(f"#{spec['color']}"))
            if spec["bold"]:
                fmt.setFontWeight(QFont.Weight.Bold)
            if spec["italic"]:
                fmt.setFontItalic(True)
            self.formats[token] = fmt
        self.rehighlight()

    def _format(self, token: _TokenType) -> QTextCharFormat | None:
        while token is not None:
            fmt = self.formats.get(token)
            if fmt is not None:
                return fmt
            token = token.parent
        return None

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt API)
        # Block state 1: this line ends inside a triple-quoted string. The next line is lexed
        # with a `"""` in front, so its text is colored as the string it continues.
        inside = self.previousBlockState() == 1
        prefix = '"""' if inside else ""
        pos = -len(prefix)
        for token, value in self.lexer.get_tokens(prefix + text):
            start, end = max(pos, 0), pos + len(value)
            fmt = self._format(token)
            if fmt is not None and end > start:
                self.setFormat(start, end - start, fmt)
            pos = end
        self.setCurrentBlockState(1 if inside != (text.count('"""') % 2 == 1) else 0)


class _Gutter(QWidget):
    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """Plain text editing with line numbers and highlighting."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        font = QFont(tokens.FONT_MONO)
        font.setPixelSize(tokens.FONT_SIZE["secondary"])
        self.setFont(font)
        self.setProperty("role", "code")  # mono font from the stylesheet
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        metrics = QFontMetricsF(font)
        self.setTabStopDistance(metrics.horizontalAdvance(" ") * tokens.EDITOR_TAB_SPACES)
        self.highlighter = PythonHighlighter(self.document(), theme.current_theme())
        self.gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda _n: self._update_margins())
        self.updateRequest.connect(self._scroll_gutter)
        self._update_margins()

    # -- line numbers ---------------------------------------------------------------------
    def gutter_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        advance = self.fontMetrics().horizontalAdvance("9")
        return advance * digits + 2 * tokens.EDITOR_GUTTER_PAD

    def _update_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        r = self.contentsRect()
        self.gutter.setGeometry(QRect(r.left(), r.top(), self.gutter_width(), r.height()))

    def paint_gutter(self, event: QPaintEvent) -> None:
        name = theme.current_theme()
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor(tokens.color(name, "bg.elevated")))
        painter.setPen(QColor(tokens.color(name, "text.secondary")))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        width = self.gutter.width() - tokens.EDITOR_GUTTER_PAD
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                painter.drawText(
                    0,
                    top,
                    width,
                    height,
                    int(Qt.AlignmentFlag.AlignRight),
                    str(block.blockNumber() + 1),
                )
            top += round(self.blockBoundingRect(block).height())
            block = block.next()
        painter.end()

    def line_numbers(self) -> list[int]:
        """The numbers the gutter shows, top to bottom (tests)."""
        out, block = [], self.document().firstBlock()
        while block.isValid():
            out.append(block.blockNumber() + 1)
            block = block.next()
        return out

    # -- editing --------------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText(" " * tokens.EDITOR_TAB_SPACES)  # spaces, never tabs
            return
        super().keyPressEvent(event)

    def selected_code(self) -> str:
        """The selected lines, whole (or the current line when nothing is selected)."""
        cursor = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        if (
            cursor.hasSelection()
            and cursor.selectionEnd() == doc.findBlockByNumber(last).position()
            and last > first
        ):
            last -= 1  # a selection ending at the start of a line doesn't include it
        lines = [doc.findBlockByNumber(i).text() for i in range(first, last + 1)]
        return _dedent("\n".join(lines))


def _dedent(code: str) -> str:
    import textwrap

    return textwrap.dedent(code)


class EditorPanel(QWidget):
    """The Editor tab: a toolbar (New, Open, Save, Run File, Run Selection) over the editor."""

    run_code = Signal(str)  # source to run in the console
    run_file = Signal(str)  # path of a saved file to run with %run
    file_changed = Signal(object)  # the file shown (Path or None), e.g. for the project

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path: Path | None = None
        self.editor = CodeEditor(self)
        self.editor.setPlaceholderText(
            f"Write Python here and press {RUN_FILE_KEY} to run it in the console, "
            "or open a script."
        )
        self.label = QLabel("untitled.py", self)
        self.label.setProperty("role", "secondary")
        bar = QHBoxLayout()
        pad = tokens.SPACING[1]
        bar.setContentsMargins(pad, tokens.SPACING[0], pad, tokens.SPACING[0])
        bar.setSpacing(tokens.SPACING[0])
        self.buttons: dict[str, QToolButton] = {}
        for key, ic, tip, fn in (
            ("new", "file-plus", "New Script", self.new),
            ("open", "folder-open", "Open Script…", self.open_dialog),
            ("save", "save", "Save Script", self.save),
            ("run", "play", f"Run File ({RUN_FILE_KEY})", self.run),
            (
                "run_selection",
                "text-cursor-input",
                f"Run Selection ({RUN_SELECTION_KEY})",
                self.run_selection,
            ),
        ):
            b = QToolButton(self)
            b.setIcon(icon(ic, "accent" if key == "run" else "text.secondary"))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(_ignore_checked(fn))
            bar.addWidget(b)
            self.buttons[key] = b
        bar.addSpacing(pad)
        bar.addWidget(self.label, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.editor, 1)
        self._shortcut(RUN_FILE_KEY, self.run)
        self._shortcut(RUN_SELECTION_KEY, self.run_selection)
        self.editor.document().modificationChanged.connect(lambda _m: self._show_name())

    def _shortcut(self, key: str, fn: Callable[[], object]) -> None:
        from qtpy.QtGui import QShortcut

        sc = QShortcut(QKeySequence(key), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(fn)

    def _show_name(self) -> None:
        name = self.path.name if self.path is not None else "untitled.py"
        if self.editor.document().isModified():
            name += " •"
        self.label.setText(name)
        self.label.setToolTip(str(self.path) if self.path is not None else "")

    def set_theme(self, name: ThemeName) -> None:
        self.editor.highlighter.set_theme(name)
        self.editor.gutter.update()

    # -- files ----------------------------------------------------------------------------
    def new(self) -> None:
        if not self._discard_ok():
            return
        self.editor.setPlainText("")
        self.path = None
        self.editor.document().setModified(False)
        self._show_name()
        self.file_changed.emit(None)

    def open_dialog(self) -> None:
        start = str(self.path.parent) if self.path is not None else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open Script", start, "Python (*.py)")
        if path:
            self.open(path)

    def open(self, path: str | Path) -> None:
        if not self._discard_ok():
            return
        self.path = Path(path)
        self.editor.setPlainText(self.path.read_text(encoding="utf-8"))
        self.editor.document().setModified(False)
        self._show_name()
        self.file_changed.emit(self.path)

    def save(self) -> bool:
        if self.path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save Script", "", "Python (*.py)")
            if not path:
                return False
            self.path = Path(path)
            self.file_changed.emit(self.path)
        self.save_to(self.path)
        return True

    def save_to(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.editor.toPlainText(), encoding="utf-8")
        self.editor.document().setModified(False)
        self._show_name()

    def _discard_ok(self) -> bool:
        if not self.editor.document().isModified():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Script",
            "Discard the changes to this script?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    # -- running --------------------------------------------------------------------------
    def run(self) -> None:
        """Run File: an unsaved new script runs as typed; a file is saved and `%run`."""
        if self.path is None:
            code = self.editor.toPlainText()
            if code.strip():
                self.run_code.emit(code)
            return
        self.save_to(self.path)
        self.run_file.emit(str(self.path))

    def run_selection(self) -> None:
        code = self.editor.selected_code()
        if code.strip():
            self.run_code.emit(code)


def _ignore_checked(fn: Callable[[], object]) -> Callable[[bool], None]:
    return lambda _checked=False: (fn(), None)[1]
