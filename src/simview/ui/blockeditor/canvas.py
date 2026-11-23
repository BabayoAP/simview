"""The block diagram canvas (BD-01, DS-10, §7.7).

A dot grid with 8 px snap; blocks as rounded rectangles with a semibold title and a category
strip; ports colored by signal type; orthogonal wires with rounded corners that show their
live value on hover; problems as a red outline with the message under the block. Pan with the
middle mouse button (or Alt + drag), zoom with the wheel, drag from a port to a port to
connect, double-click the canvas to add a block, double-click a subsystem to open it.

The canvas draws a `Document` and reports what the user did; the editor applies it to the
document, which redraws the canvas.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from qtpy.QtCore import QLineF, QPoint, QPointF, QRectF, Qt, Signal
from qtpy.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QShowEvent,
    QWheelEvent,
)
from qtpy.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSceneHoverEvent,
    QGraphicsTextItem,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
)
from shiboken6 import isValid  # items die with the scene at exit, before its last signal

from simview.blocks.graph import Block, Wire
from simview.ui.blockeditor.document import Document
from simview.ui.theme import tokens
from simview.ui.theme.tokens import ThemeName

# (flat block path, output port name) -> the value text, or None when nothing is recorded.
ValueLookup = Callable[[str, str], "str | None"]

T = tokens


def snap(v: float) -> float:
    return round(v / T.GRID_SNAP) * T.GRID_SNAP


def block_height(n_in: int, n_out: int) -> float:
    return T.BLOCK_HEADER + T.BLOCK_PORT_PITCH * max(1, n_in, n_out) + T.BLOCK_PAD


def port_offset(output: bool, index: int) -> QPointF:
    y = T.BLOCK_HEADER + T.BLOCK_PORT_PITCH * (index + 0.5)
    return QPointF(T.BLOCK_WIDTH if output else 0.0, y)


def kind_of(shape: tuple[int, ...] | None) -> str | None:
    """Signal type of a shape: scalar, vector, matrix (None when unknown)."""
    if shape is None:
        return None
    if len(shape) == 0:
        return "scalar"
    return "vector" if len(shape) == 1 else "matrix"


def route(a: QPointF, b: QPointF, below: float) -> list[QPointF]:
    """Orthogonal corner points from an output at `a` to an input at `b`. Forward wires take
    one vertical run halfway; a wire going back left (a feedback loop) runs under both blocks
    (`below`)."""
    stub = T.WIRE_STUB
    if b.x() > a.x():
        if abs(a.y() - b.y()) < 0.5:
            return [a, b]
        mx = snap((a.x() + b.x()) / 2)
        return [a, QPointF(mx, a.y()), QPointF(mx, b.y()), b]
    x1, x2 = a.x() + stub, b.x() - stub
    return [a, QPointF(x1, a.y()), QPointF(x1, below), QPointF(x2, below), QPointF(x2, b.y()), b]


def rounded_path(points: list[QPointF], radius: float = T.WIRE_RADIUS) -> QPainterPath:
    path = QPainterPath(points[0])
    for i in range(1, len(points) - 1):
        p0, p, p1 = points[i - 1], points[i], points[i + 1]
        d0, d1 = QLineF(p, p0).length(), QLineF(p, p1).length()
        r = min(radius, d0 / 2, d1 / 2)
        if r <= 0:
            path.lineTo(p)
            continue
        u0 = (p0 - p) / d0
        u1 = (p1 - p) / d1
        path.lineTo(p + u0 * r)
        path.quadTo(p, p + u1 * r)
    path.lineTo(points[-1])
    return path


def _font(size: str, semibold: bool = False) -> QFont:
    f = QFont(T.FONT_UI)
    f.setPixelSize(T.FONT_SIZE[size])
    if semibold:
        f.setWeight(QFont.Weight(T.WEIGHT_SEMIBOLD))
    return f


# -- items ------------------------------------------------------------------------------------
class PortItem(QGraphicsEllipseItem):
    def __init__(
        self, block: BlockItem, output: bool, index: int, name: str, kind: str | None
    ) -> None:
        r = T.PORT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, block)
        self.block, self.output, self.index, self.name, self.kind = (
            block,
            output,
            index,
            name,
            kind,
        )
        self.setPos(port_offset(output, index))
        self.setZValue(2)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(
            f"{'output' if output else 'input'} {name}" + (f" ({kind})" if kind else "")
        )

    def style(self, theme: ThemeName) -> None:
        colors = T.PORT_COLORS[theme]
        c = QColor(colors[self.kind or "scalar"])
        self.setPen(QPen(c, T.HAIRLINE + 0.5))
        bg = QColor(T.color(theme, "bg.elevated"))
        self.setBrush(QBrush(c if self.kind else bg))

    @property
    def end(self) -> tuple[str, int]:
        return (self.block.block.id, self.index)


class BlockItem(QGraphicsItem):
    def __init__(
        self,
        block: Block,
        category: str,
        inputs: list[str],
        outputs: list[str],
        kinds: list[str | None],
        issues: list[str],
        theme: ThemeName,
    ) -> None:
        super().__init__()
        self.block, self.category, self.issues, self.theme = block, category, issues, theme
        self.inputs, self.outputs = inputs, outputs
        self.height = block_height(len(inputs), len(outputs))
        self.wires: list[WireItem] = []
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(1)
        self.setPos(QPointF(*block.pos))
        self.in_ports = [PortItem(self, False, i, n, None) for i, n in enumerate(inputs)]
        self.out_ports = [PortItem(self, True, i, n, kinds[i]) for i, n in enumerate(outputs)]
        for p in (*self.in_ports, *self.out_ports):
            p.style(theme)
        tip = f"{block.type}" if block.type == block.id else f"{block.id} ({block.type})"
        if block.is_subsystem:
            tip += " — double-click to open"
        self.setToolTip(tip)
        self.error: QGraphicsTextItem | None = None
        if issues:
            self.error = QGraphicsTextItem(self)
            self.error.setDefaultTextColor(QColor(T.color(theme, "state.error")))
            self.error.setFont(_font("caption"))
            self.error.setTextWidth(T.ERROR_TEXT_WIDTH)
            self.error.setPlainText("\n".join(issues))
            self.error.setPos(0, self.height + T.SPACING[0])

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt API)
        m = T.ERROR_OUTLINE
        return QRectF(-m, -m, T.BLOCK_WIDTH + 2 * m, self.height + 2 * m)

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        p.addRoundedRect(QRectF(0, 0, T.BLOCK_WIDTH, self.height), T.BLOCK_RADIUS, T.BLOCK_RADIUS)
        return p

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        c = T.COLORS[self.theme]
        rect = QRectF(0, 0, T.BLOCK_WIDTH, self.height)
        body = self.shape()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(body, QColor(c["bg.elevated"]))
        painter.save()
        painter.setClipPath(body)
        strip = T.BLOCK_CATEGORY_COLORS[self.theme][self.category]
        painter.fillRect(QRectF(0, 0, T.BLOCK_STRIP, self.height), QColor(strip))
        painter.restore()
        if self.issues:
            pen = QPen(QColor(c["state.error"]), T.ERROR_OUTLINE)
        elif self.isSelected():
            pen = QPen(QColor(c["accent"]), T.BLOCK_SELECT_WIDTH)
        else:
            pen = QPen(QColor(c["border.subtle"]), T.HAIRLINE)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, T.BLOCK_RADIUS, T.BLOCK_RADIUS)

        pad = T.BLOCK_STRIP + T.SPACING[1]
        title = _font("body", semibold=True)
        painter.setFont(title)
        painter.setPen(QColor(c["text.primary"]))
        head = QRectF(pad, 0, T.BLOCK_WIDTH - pad - T.SPACING[1], T.BLOCK_HEADER)
        text = QFontMetricsF(title).elidedText(
            self.block.id, Qt.TextElideMode.ElideRight, head.width()
        )
        painter.drawText(head, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        small = _font("caption")
        painter.setFont(small)
        painter.setPen(QColor(c["text.secondary"]))
        fm = QFontMetricsF(small)
        plain = self.inputs in ([], ["u"]) and self.outputs in ([], ["y"])
        if plain:  # one port each side at most: show the type instead of "u" and "y"
            r = QRectF(pad, T.BLOCK_HEADER, T.BLOCK_WIDTH - 2 * pad, T.BLOCK_PORT_PITCH)
            label = "Subsystem" if self.block.is_subsystem else self.block.type
            painter.drawText(
                r,
                Qt.AlignmentFlag.AlignCenter,
                fm.elidedText(label, Qt.TextElideMode.ElideRight, r.width()),
            )
            return
        half = T.BLOCK_WIDTH / 2 - pad
        for ports, left in ((self.in_ports, True), (self.out_ports, False)):
            for p in ports:
                y = p.pos().y() - T.BLOCK_PORT_PITCH / 2
                x = pad if left else T.BLOCK_WIDTH / 2
                align = Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight
                r = QRectF(x, y, half if left else half, T.BLOCK_PORT_PITCH)
                painter.drawText(
                    r,
                    align | Qt.AlignmentFlag.AlignVCenter,
                    fm.elidedText(p.name, Qt.TextElideMode.ElideRight, r.width()),
                )

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(
            value, QPointF
        ):
            return QPointF(snap(value.x()), snap(value.y()))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for w in self.wires:
                w.update_path()
        return super().itemChange(change, value)


class WireItem(QGraphicsPathItem):
    def __init__(
        self,
        wire: Wire,
        src: PortItem,
        dst: PortItem,
        theme: ThemeName,
        value: Callable[[], str | None],
    ) -> None:
        super().__init__()
        self.wire, self.src, self.dst, self.theme, self.value = wire, src, dst, theme, value
        self.hovered = False
        self.setZValue(0)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        src.block.wires.append(self)
        dst.block.wires.append(self)
        self.update_path()
        self.restyle()

    def update_path(self) -> None:
        a = self.src.scenePos()
        b = self.dst.scenePos()
        below = (
            max(
                self.src.block.scenePos().y() + self.src.block.height,
                self.dst.block.scenePos().y() + self.dst.block.height,
            )
            + T.WIRE_STUB
        )
        self.setPath(rounded_path(route(a, b, below)))

    def shape(self) -> QPainterPath:
        s = QPainterPathStroker()
        s.setWidth(T.WIRE_HIT_WIDTH)
        return s.createStroke(self.path())

    def restyle(self) -> None:
        c = T.COLORS[self.theme]
        if self.isSelected():
            color = QColor(c["accent"])
        else:
            color = QColor(T.PORT_COLORS[self.theme][self.src.kind or "scalar"])
        width = T.WIRE_HOVER_WIDTH if self.hovered or self.isSelected() else T.WIRE_WIDTH
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)

    def tooltip_text(self) -> str:
        src = f"{self.src.block.block.id}.{self.src.name}"
        value = self.value()
        return f"{src} = {value}" if value is not None else f"{src} (run the sim to see its value)"

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:  # noqa: N802
        self.hovered = True
        self.setToolTip(self.tooltip_text())  # §7.7: the live value during simulation
        self.restyle()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:  # noqa: N802
        self.hovered = False
        self.restyle()
        super().hoverLeaveEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.restyle()
        return super().itemChange(change, value)


# -- the view ---------------------------------------------------------------------------------
class DiagramView(QGraphicsView):
    quick_add = Signal(QPointF, QPoint)  # scene position, global position
    open_subsystem = Signal(str)
    connect_ports = Signal(object, object)  # (block, output port), (block, input port)
    moved = Signal(dict)  # block id -> new position
    delete_pressed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self.setObjectName("DiagramCanvas")
        self.theme: ThemeName = "dark"
        self.blocks: dict[str, BlockItem] = {}
        self.wire_items: list[WireItem] = []
        self.empty = True
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scene.setSceneRect(QRectF(-1e5, -1e5, 2e5, 2e5))  # room to pan anywhere
        self._pan: QPoint | None = None
        self._drag_from: PortItem | None = None
        self._ghost: QGraphicsPathItem | None = None
        self._press_pos: dict[str, QPointF] = {}

    # -- drawing a document -------------------------------------------------------------------
    def show_document(self, doc: Document, theme: ThemeName, lookup: ValueLookup | None) -> None:
        selected = {bid for bid, it in self.blocks.items() if it.isSelected()}
        self.theme = theme
        self.blocks, self.wire_items = {}, []
        self._scene.blockSignals(True)  # no selection signals from half-built items
        self._scene.clear()
        d = doc.current
        prefix = doc.prefix()
        for b in d.blocks.values():
            ports = doc.ports(b)
            kinds = [kind_of(doc.shape(b.id, k)) for k in range(len(ports.outputs))]
            item = BlockItem(
                b, doc.category(b), ports.inputs, ports.outputs, kinds, doc.issues_for(b.id), theme
            )
            self._scene.addItem(item)
            item.setSelected(b.id in selected)
            self.blocks[b.id] = item
        for w in d.wires:
            s, t = self.blocks.get(w.src), self.blocks.get(w.dst)
            if (
                s is None
                or t is None
                or w.src_port >= len(s.out_ports)
                or w.dst_port >= len(t.in_ports)
            ):
                continue  # drawn once its block has the port again (parameters fixed)
            src = s.out_ports[w.src_port]

            def value(src: PortItem = src) -> str | None:
                if lookup is None:
                    return None
                return lookup(prefix + src.block.block.id, src.name)

            wi = WireItem(w, src, t.in_ports[w.dst_port], theme, value)
            self._scene.addItem(wi)
            self.wire_items.append(wi)
        self._scene.blockSignals(False)
        self.empty = not d.blocks
        self.viewport().update()

    def selected_blocks(self) -> list[str]:
        return [bid for bid, it in self.blocks.items() if isValid(it) and it.isSelected()]

    def selected_wires(self) -> list[Wire]:
        return [w.wire for w in self.wire_items if isValid(w) and w.isSelected()]

    def select(self, ids: list[str]) -> None:
        self._scene.clearSelection()
        for i in ids:
            if i in self.blocks:
                self.blocks[i].setSelected(True)

    def fit(self) -> None:
        if not self.isVisible():  # a hidden view has no real size yet: fit when it's shown
            self._fit_pending = True
            return
        self._fit_pending = False
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            self.resetTransform()
            self.centerOn(0, 0)
            return
        m = 4 * T.GRID_DOT_SPACING
        self.fitInView(rect.adjusted(-m, -m, m, m), Qt.AspectRatioMode.KeepAspectRatio)
        s = self.transform().m11()
        lo, hi = T.CANVAS_ZOOM
        if not lo <= s <= min(hi, 1.0):  # don't blow small diagrams up past 100 %
            k = min(max(s, lo), 1.0) / s
            self.scale(k, k)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if getattr(self, "_fit_pending", False):
            self.fit()

    @property
    def zoom(self) -> float:
        return self.transform().m11()

    # -- background: the dot grid, and the empty canvas's hint (§7.8) ---------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        c = T.COLORS[self.theme]
        painter.fillRect(rect, QColor(c["bg.panel"]))
        step = T.GRID_DOT_SPACING
        if self.zoom * step < T.SPACING[1]:
            step *= 4  # zoomed far out: fewer dots
        x0 = math.floor(rect.left() / step) * step
        y0 = math.floor(rect.top() / step) * step
        pen = QPen(QColor(c["border.subtle"]), T.GRID_DOT_SIZE / max(self.zoom, 1e-3))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        xs = np.arange(x0, rect.right() + step, step)
        ys = np.arange(y0, rect.bottom() + step, step)
        if len(xs) * len(ys) < 40_000:
            painter.drawPoints([QPointF(x, y) for y in ys for x in xs])

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        if not self.empty:
            return
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(T.color(self.theme, "text.secondary")))
        painter.setFont(_font("body"))
        painter.drawText(
            QRectF(self.viewport().rect()),
            Qt.AlignmentFlag.AlignCenter,
            "Double-click to add a block.",
        )
        painter.restore()

    # -- mouse ------------------------------------------------------------------------------------
    def _port_at(self, pos: QPoint) -> PortItem | None:
        for it in self.items(pos):
            if isinstance(it, PortItem):
                return it
        # a little slack around small ports
        r = T.PORT_RADIUS
        area = QRectF(self.mapToScene(pos) - QPointF(r, r), self.mapToScene(pos) + QPointF(r, r))
        for it in self._scene.items(area):
            if isinstance(it, PortItem):
                return it
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pan = event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        )
        if pan:
            self._pan = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            port = self._port_at(event.position().toPoint())
            if port is not None:
                self._drag_from = port
                self._ghost = QGraphicsPathItem()
                pen = QPen(QColor(T.color(self.theme, "accent")), T.WIRE_WIDTH)
                pen.setStyle(Qt.PenStyle.DashLine)
                self._ghost.setPen(pen)
                self._ghost.setZValue(3)
                self._scene.addItem(self._ghost)
                event.accept()
                return
        self._press_pos = {bid: it.pos() for bid, it in self.blocks.items()}
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan is not None:
            d = event.position().toPoint() - self._pan
            self._pan = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            event.accept()
            return
        if self._drag_from is not None and self._ghost is not None:
            a = self._drag_from.scenePos()
            b = self.mapToScene(event.position().toPoint())
            path = QPainterPath(a)
            path.lineTo(b)
            self._ghost.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
            event.accept()
            return
        if self._drag_from is not None:
            start, self._drag_from = self._drag_from, None
            if self._ghost is not None:
                self._scene.removeItem(self._ghost)
                self._ghost = None
            end = self._port_at(event.position().toPoint())
            self.finish_connect(start, end)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        moved = {
            bid: (it.pos().x(), it.pos().y())
            for bid, it in self.blocks.items()
            if bid in self._press_pos and it.pos() != self._press_pos[bid]
        }
        self._press_pos = {}
        if moved:
            self.moved.emit(moved)

    def finish_connect(self, a: PortItem, b: PortItem | None) -> bool:
        """A drag between two ports: one output, one input, on different blocks."""
        if b is None or a.output == b.output or a.block is b.block:
            return False
        src, dst = (a, b) if a.output else (b, a)
        self.connect_ports.emit(src.end, dst.end)
        return True

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseDoubleClickEvent(event)
        for it in self.items(event.position().toPoint()):
            while it is not None and not isinstance(it, BlockItem):
                it = it.parentItem()
            if isinstance(it, BlockItem):
                if it.block.is_subsystem:
                    self.open_subsystem.emit(it.block.id)
                event.accept()
                return
            if isinstance(it, WireItem):
                return
        pos = self.mapToScene(event.position().toPoint())
        self.quick_add.emit(QPointF(snap(pos.x()), snap(pos.y())), event.globalPosition().toPoint())
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120
        if not steps:
            return
        k = T.CANVAS_ZOOM_STEP**steps
        lo, hi = T.CANVAS_ZOOM
        k = min(max(self.zoom * k, lo), hi) / self.zoom
        self.scale(k, k)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)
