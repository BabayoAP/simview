"""The diagram being edited (BD-01, BD-05, BD-06, BD-07): the model behind the canvas.

It owns the top diagram, which subsystem the canvas shows (`level`), undo / redo as JSON
snapshots of the whole diagram (an `.svd` file is small), and the compiler's problems and
signal shapes, re-checked after every edit. Entity blocks are checked against a stand-in for
the open scene's entities (names and state names from the sim process), so the editor never
needs the scene itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from qtpy.QtCore import QObject, Signal

from simview.blocks import Diagram, Issue, check
from simview.blocks.graph import Block, Wire
from simview.blocks.library import SUBSYSTEM, BlockError, block_class

UNTITLED = "untitled"


# -- a stand-in scene for checking entity blocks ---------------------------------------------
@dataclass
class _Entity:
    state_names: tuple[str, ...]
    x: np.ndarray = field(init=False)
    u: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def __post_init__(self) -> None:
        self.x = np.zeros(len(self.state_names))


class StandInScene:
    """Entity names and state names, enough to bind Entity State / Entity Input blocks."""

    def __init__(self, entities: dict[str, tuple[str, ...]] | None = None) -> None:
        self.entities = {k: _Entity(tuple(v)) for k, v in (entities or {}).items()}

    def __getitem__(self, name: str) -> _Entity:
        return self.entities[name]


@dataclass(frozen=True)
class Ports:
    inputs: list[str]
    outputs: list[str]


class Document(QObject):
    changed = Signal()  # the diagram, the level, or the problems changed: redraw
    saved = Signal(object)  # Path

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.scene = StandInScene()
        self._port_cache: dict[str, Ports] = {}
        self._reset(Diagram(UNTITLED))

    def _reset(self, root: Diagram) -> None:
        self.root = root
        self.level: list[str] = []  # subsystem ids from the top to the shown diagram
        self._snapshots = [root.dumps()]
        self._at = 0
        self._saved = self._snapshots[0]
        self._recheck()

    # -- files (BD-06) ------------------------------------------------------------------------
    @property
    def path(self) -> Path | None:
        return self.root.path

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def modified(self) -> bool:
        return self._snapshots[self._at] != self._saved

    @property
    def is_blank(self) -> bool:
        return self.path is None and not self.root.blocks and not self.modified

    def new(self) -> None:
        self._reset(Diagram(UNTITLED))
        self.changed.emit()

    def open(self, path: str | Path) -> None:
        self._reset(Diagram.load(path))
        self.changed.emit()

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("choose a file to save the diagram to")
        if path is not None:
            self.root.name = Path(target).stem
            self._commit(recheck=False)  # the name is in the file
        saved = self.root.save(target)
        self._saved = self._snapshots[self._at]
        self._recheck()
        self.changed.emit()
        self.saved.emit(saved)
        return saved

    # -- what's shown -------------------------------------------------------------------------
    @property
    def current(self) -> Diagram:
        d = self.root
        for sub in self.level:
            inner = d.blocks[sub].diagram
            assert inner is not None
            d = inner
        return d

    def prefix(self) -> str:
        """The flat path prefix of blocks on the shown level ("" at the top, "ctrl/" ...)."""
        return "".join(f"{s}/" for s in self.level)

    def enter(self, sub_id: str) -> None:
        if self.current.blocks[sub_id].is_subsystem:
            self.level.append(sub_id)
            self.changed.emit()

    def up(self, levels: int = 1) -> None:
        if self.level:
            del self.level[len(self.level) - min(levels, len(self.level)) :]
            self.changed.emit()

    # -- undo / redo --------------------------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return self._at > 0

    @property
    def can_redo(self) -> bool:
        return self._at < len(self._snapshots) - 1

    def undo(self) -> None:
        if self.can_undo:
            self._at -= 1
            self._restore()

    def redo(self) -> None:
        if self.can_redo:
            self._at += 1
            self._restore()

    def _restore(self) -> None:
        path = self.root.path
        self.root = Diagram.loads(self._snapshots[self._at])
        self.root.path = path
        # Stay as deep as the restored diagram allows.
        d, kept = self.root, []
        for sub in self.level:
            b = d.blocks.get(sub)
            if b is None or b.diagram is None:
                break
            kept.append(sub)
            d = b.diagram
        self.level = kept
        self._recheck()
        self.changed.emit()

    def _commit(self, recheck: bool = True) -> bool:
        snap = self.root.dumps()
        if snap == self._snapshots[self._at]:
            return False
        del self._snapshots[self._at + 1 :]
        self._snapshots.append(snap)
        self._at += 1
        if recheck:
            self._recheck()
            self.changed.emit()
        return True

    # -- edits (each one is one undo step) ----------------------------------------------------
    def add(self, type_name: str, pos: tuple[float, float]) -> str:
        block = self.current.add(type_name, pos=pos)
        self._commit()
        return block.id

    def connect(self, src: tuple[str, int], dst: tuple[str, int]) -> None:
        d = self.current
        # An input takes one wire: connecting to a used input replaces its wire.
        d.wires = [w for w in d.wires if (w.dst, w.dst_port) != dst]
        d.connect(src, dst)
        self._commit()

    def delete(self, blocks: list[str], wires: list[Wire] | None = None) -> None:
        d = self.current
        for w in wires or []:
            if w in d.wires:
                d.disconnect(w)
        for b in blocks:
            if b in d.blocks:
                d.remove(b)
        self._commit()

    def move(self, positions: dict[str, tuple[float, float]]) -> None:
        for bid, pos in positions.items():
            self.current.blocks[bid].pos = (float(pos[0]), float(pos[1]))
        self._commit()

    def rename(self, old: str, new: str) -> None:
        self.current.rename(old, new)
        self._commit()

    def set_param(self, block_id: str, key: str, value: Any) -> None:
        json.dumps(value)  # parameters are JSON values (D-079)
        self.current.blocks[block_id].params[key] = value
        self._commit()

    def group(self, ids: list[str]) -> str:
        sub = self.current.group(ids)
        self._commit()
        return sub.id

    def ungroup(self, sub_id: str) -> list[str]:
        moved = self.current.ungroup(sub_id)
        self._commit()
        return moved

    # -- checking (BD-05) ---------------------------------------------------------------------
    def set_entities(self, entities: dict[str, tuple[str, ...]]) -> None:
        self.scene = StandInScene(entities)
        self._port_cache.clear()
        self._recheck()
        self.changed.emit()

    def _recheck(self) -> None:
        base = self.path.parent if self.path is not None else None
        compiled, issues = check(self.root, scene=self.scene, base=base)
        self.issues: list[Issue] = issues
        self.shapes: dict[tuple[str, int], tuple[int, ...]] = (
            compiled.shapes if compiled is not None else {}
        )

    def issues_for(self, block_id: str) -> list[str]:
        """Messages for a block on the shown level; a subsystem collects its insides'."""
        path = self.prefix() + block_id
        out = []
        for issue in self.issues:
            if issue.block == path:
                out.append(issue.message)
            elif issue.block.startswith(path + "/"):
                out.append(f"{issue.block[len(path) + 1 :]}: {issue.message}")
        return out

    def general_issues(self) -> list[str]:
        return [i.message for i in self.issues if not i.block]

    def shape(self, block_id: str, port: int) -> tuple[int, ...] | None:
        """The shape of an output on the shown level (None when the diagram doesn't compile).
        A subsystem's output is its Outport's source."""
        path = self.prefix() + block_id
        block = self.current.blocks[block_id]
        if block.is_subsystem:
            src = _outport_source(block, port)
            if src is None:
                return None
            path, port = f"{path}/{src[0]}", src[1]
            # follow nested subsystems
            inner = block.diagram
            while inner is not None and src is not None:
                b = inner.blocks.get(src[0])
                if b is None or not b.is_subsystem:
                    break
                src = _outport_source(b, src[1])
                if src is None:
                    return None
                path, port = f"{path}/{src[0]}", src[1]
                inner = b.diagram
        return self.shapes.get((path, port))

    def ports(self, block: Block) -> Ports:
        """Port names, from the block bound to the stand-in scene when that works (so an
        Entity State block shows one port per state of its entity)."""
        if block.is_subsystem:
            ins, outs = block.ports()
            return Ports(ins, outs)
        base = self.path.parent if self.path is not None else None
        key = json.dumps([block.type, block.params, str(base)], sort_keys=True, default=str)
        got = self._port_cache.get(key)
        if got is None:
            try:
                impl = block_class(block.type)(block.id, block.params, base)
            except Exception:  # noqa: BLE001 - bad parameters: no ports until fixed
                got = Ports([], [])
            else:
                try:
                    impl.bind(self.scene)
                except Exception:  # noqa: BLE001 - unbound: the unbound ports
                    pass
                got = Ports(impl.input_names(), impl.output_names())
            self._port_cache[key] = got
        return got

    def category(self, block: Block) -> str:
        if block.is_subsystem:
            return SUBSYSTEM
        try:
            return block_class(block.type).category
        except BlockError:
            return SUBSYSTEM


def _outport_source(sub: Block, port: int) -> tuple[str, int] | None:
    inner = sub.diagram
    if inner is None:
        return None
    out = next(
        (
            b.id
            for b in inner.blocks.values()
            if b.type == "Outport" and int(b.params.get("index", 1)) == port + 1
        ),
        None,
    )
    if out is None:
        return None
    w = next((w for w in inner.wires if w.dst == out), None)
    return (w.src, w.src_port) if w is not None else None


def parse_value(text: str) -> Any:
    """A parameter typed in the editor: JSON (numbers, lists, strings in quotes, true/false),
    or Python-style literals, or else the text itself as a string."""
    import ast

    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        value = ast.literal_eval(text)
        json.dumps(value)
        return value
    except (ValueError, SyntaxError, TypeError):
        return text


def format_value(value: Any) -> str:
    return json.dumps(value)
