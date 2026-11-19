"""Block diagrams (BD-01, BD-06, BD-07): blocks, wires, subsystems, and the `.svd` file.

A `.svd` file is JSON written with sorted keys and one block or wire per entry, so diagrams
diff cleanly in git:

    {
      "blocks": [
        {"id": "ref", "params": {"value": 1.0}, "pos": [0, 0], "type": "Constant"},
        ...
      ],
      "format": 1,
      "name": "altitude",
      "wires": [{"from": "ref:0", "to": "err:0"}, ...]
    }

Ports are numbered from 0 in the file (`block:port`). A Subsystem block holds its own
diagram, whose Inport / Outport blocks (index 1, 2, ...) are the subsystem's ports. Nothing
here imports Qt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simview.blocks.library import SUBSYSTEM, BlockError, block_class

FORMAT = 1
SUFFIX = ".svd"
_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Wire:
    src: str
    src_port: int
    dst: str
    dst_port: int

    def to_json(self) -> dict[str, str]:
        return {"from": f"{self.src}:{self.src_port}", "to": f"{self.dst}:{self.dst_port}"}

    @staticmethod
    def parse(end: str) -> tuple[str, int]:
        block, sep, port = end.rpartition(":")
        if not sep or not port.isdigit():
            raise ValueError(f"wire end {end!r} must look like 'block:0'")
        return block, int(port)


@dataclass
class Block:
    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    pos: tuple[float, float] = (0.0, 0.0)
    diagram: Diagram | None = None  # a Subsystem's contents

    @property
    def is_subsystem(self) -> bool:
        return self.type == SUBSYSTEM

    def ports(self, base: Path | None = None) -> tuple[list[str], list[str]]:
        """(input names, output names). A block whose parameters are invalid has none."""
        if self.is_subsystem:
            assert self.diagram is not None
            ins = sorted(
                (int(b.params.get("index", 1)), b.id)
                for b in self.diagram.blocks.values()
                if b.type == "Inport"
            )
            outs = sorted(
                (int(b.params.get("index", 1)), b.id)
                for b in self.diagram.blocks.values()
                if b.type == "Outport"
            )
            return [name for _, name in ins], [name for _, name in outs]
        try:
            impl = block_class(self.type)(self.id, self.params, base)
        except BlockError:
            return [], []
        return impl.input_names(), impl.output_names()

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "pos": [round(self.pos[0], 1), round(self.pos[1], 1)],
            "params": self.params,
        }
        if self.diagram is not None:
            out["diagram"] = self.diagram.to_json(top=False)
        return out


class Diagram:
    def __init__(self, name: str = "diagram") -> None:
        self.name = name
        self.blocks: dict[str, Block] = {}
        self.wires: list[Wire] = []
        self.path: Path | None = None  # the .svd file it was loaded from or saved to

    # -- editing ----------------------------------------------------------------------------
    def new_id(self, type_name: str) -> str:
        stem = re.sub(r"[^a-z0-9]", "", type_name.lower()) or "block"
        i = 1
        while f"{stem}{i}" in self.blocks:
            i += 1
        return f"{stem}{i}"

    def free_id(self, wanted: str) -> str:
        name, i = wanted, 2
        while name in self.blocks:
            name, i = f"{wanted}_{i}", i + 1
        return name

    def add(
        self,
        type_name: str,
        id: str | None = None,  # noqa: A002 - matches the file format
        pos: tuple[float, float] = (0.0, 0.0),
        **params: Any,
    ) -> Block:
        if type_name != SUBSYSTEM:
            block_class(type_name)  # raises for an unknown type
        block_id = id or self.new_id(type_name)
        if not _ID.match(block_id):
            raise ValueError(f"block id {block_id!r} must be a Python-style name")
        if block_id in self.blocks:
            raise ValueError(f"a block named {block_id!r} already exists")
        block = Block(block_id, type_name, dict(params), (float(pos[0]), float(pos[1])))
        if type_name == SUBSYSTEM:
            block.diagram = Diagram(block_id)
        self.blocks[block_id] = block
        return block

    def connect(self, src: str | tuple[str, int], dst: str | tuple[str, int]) -> Wire:
        s = Wire.parse(src) if isinstance(src, str) else src
        d = Wire.parse(dst) if isinstance(dst, str) else dst
        for end in (s[0], d[0]):
            if end not in self.blocks:
                raise ValueError(f"no block {end!r}")
        if any(w.dst == d[0] and w.dst_port == d[1] for w in self.wires):
            raise ValueError(f"{d[0]}:{d[1]} already has a wire; an input takes one")
        wire = Wire(s[0], s[1], d[0], d[1])
        self.wires.append(wire)
        return wire

    def disconnect(self, wire: Wire) -> None:
        self.wires.remove(wire)

    def remove(self, block_id: str) -> None:
        del self.blocks[block_id]
        self.wires = [w for w in self.wires if block_id not in (w.src, w.dst)]

    def rename(self, old: str, new: str) -> None:
        if not _ID.match(new) or new in self.blocks:
            raise ValueError(f"can't rename {old!r} to {new!r}")
        self.blocks = {(new if k == old else k): v for k, v in self.blocks.items()}
        self.blocks[new].id = new
        self.wires = [
            Wire(
                new if w.src == old else w.src,
                w.src_port,
                new if w.dst == old else w.dst,
                w.dst_port,
            )
            for w in self.wires
        ]

    def group(self, ids: list[str], id: str | None = None) -> Block:  # noqa: A002
        """BD-07: move blocks into a new Subsystem. Wires that cross the boundary go through
        new Inport / Outport blocks (one per distinct outside source or inside source)."""
        chosen = [i for i in self.blocks if i in set(ids)]  # keep diagram order
        if not chosen:
            raise ValueError("select blocks to group")
        inside = set(chosen)
        xs = [self.blocks[i].pos[0] for i in chosen]
        ys = [self.blocks[i].pos[1] for i in chosen]
        sub = self.add(
            SUBSYSTEM, id or self.new_id("subsystem"), (sum(xs) / len(xs), sum(ys) / len(ys))
        )
        inner = sub.diagram
        assert inner is not None
        x0, y0 = min(xs), min(ys)
        for i in chosen:
            b = self.blocks.pop(i)
            b.pos = (b.pos[0] - x0, b.pos[1] - y0)
            inner.blocks[i] = b
        in_ports: dict[tuple[str, int], str] = {}  # outside source -> its Inport
        out_ports: dict[tuple[str, int], tuple[str, int]] = {}  # inside source -> Outport, k
        right = max(bb.pos[0] for bb in inner.blocks.values()) + 160.0
        kept: list[Wire] = []
        rewired: list[Wire] = []
        for w in self.wires:
            a, b = w.src in inside, w.dst in inside
            key = (w.src, w.src_port)
            if a and b:
                inner.wires.append(w)
            elif b:  # into the subsystem
                if key not in in_ports:
                    k = len(in_ports)
                    port = inner.free_id(f"in{k + 1}")
                    inner.add("Inport", port, (-160.0, 60.0 * k), index=k + 1)
                    in_ports[key] = port
                    rewired.append(Wire(w.src, w.src_port, sub.id, k))
                inner.wires.append(Wire(in_ports[key], 0, w.dst, w.dst_port))
            elif a:  # out of the subsystem
                if key not in out_ports:
                    k = len(out_ports)
                    port = inner.free_id(f"out{k + 1}")
                    inner.add("Outport", port, (right, 60.0 * k), index=k + 1)
                    inner.wires.append(Wire(w.src, w.src_port, port, 0))
                    out_ports[key] = (port, k)
                rewired.append(Wire(sub.id, out_ports[key][1], w.dst, w.dst_port))
            else:
                kept.append(w)
        self.wires = kept + rewired
        return sub

    def ungroup(self, sub_id: str) -> list[str]:
        """Undo `group`: the subsystem's blocks come back (its Inports / Outports go)."""
        sub = self.blocks[sub_id]
        if not sub.is_subsystem or sub.diagram is None:
            raise ValueError(f"{sub_id} is not a subsystem")
        inner = sub.diagram
        ports_in = {
            b.id: int(b.params.get("index", 1)) - 1
            for b in inner.blocks.values()
            if b.type == "Inport"
        }
        ports_out = {
            b.id: int(b.params.get("index", 1)) - 1
            for b in inner.blocks.values()
            if b.type == "Outport"
        }
        clash = [
            i
            for i in inner.blocks
            if i in self.blocks and i != sub_id and i not in ports_in and i not in ports_out
        ]
        if clash:
            raise ValueError(f"block names already used outside: {', '.join(clash)}")
        outer_in = {w.dst_port: (w.src, w.src_port) for w in self.wires if w.dst == sub_id}
        outer_out = [w for w in self.wires if w.src == sub_id]
        inner_src = {
            ports_out[w.dst]: (w.src, w.src_port) for w in inner.wires if w.dst in ports_out
        }
        self.wires = [w for w in self.wires if sub_id not in (w.src, w.dst)]
        del self.blocks[sub_id]
        moved = []
        for b in inner.blocks.values():
            if b.id in ports_in or b.id in ports_out:
                continue
            b.pos = (b.pos[0] + sub.pos[0], b.pos[1] + sub.pos[1])
            self.blocks[b.id] = b
            moved.append(b.id)
        for w in inner.wires:
            if w.src in ports_in:
                src = outer_in.get(ports_in[w.src])
                if src is not None:
                    self.wires.append(Wire(src[0], src[1], w.dst, w.dst_port))
            elif w.dst not in ports_out:
                self.wires.append(w)
        for w in outer_out:
            src = inner_src.get(w.src_port)
            if src is not None:
                self.wires.append(Wire(src[0], src[1], w.dst, w.dst_port))
        return moved

    # -- files ------------------------------------------------------------------------------
    def to_json(self, top: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "blocks": [b.to_json() for b in self.blocks.values()],
            "wires": [w.to_json() for w in self.wires],
        }
        if top:
            out = {"format": FORMAT, "name": self.name, **out}
        return out

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n"

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        if path.suffix != SUFFIX:
            path = path.with_name(path.name + SUFFIX)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(), encoding="utf-8")
        self.path = path
        return path

    @classmethod
    def from_json(cls, data: dict[str, Any], name: str | None = None) -> Diagram:
        if int(data.get("format", FORMAT)) > FORMAT:
            raise ValueError(f"diagram format {data['format']} is newer than this SimView")
        d = cls(str(data.get("name") or name or "diagram"))
        for raw in data.get("blocks", []):
            pos = raw.get("pos", [0.0, 0.0])
            block = Block(
                str(raw["id"]),
                str(raw["type"]),
                dict(raw.get("params") or {}),
                (float(pos[0]), float(pos[1])),
            )
            if block.is_subsystem:
                block.diagram = cls.from_json(raw.get("diagram") or {}, block.id)
            d.blocks[block.id] = block
        for raw in data.get("wires", []):
            s, sp = Wire.parse(raw["from"])
            t, tp = Wire.parse(raw["to"])
            d.wires.append(Wire(s, sp, t, tp))
        return d

    @classmethod
    def loads(cls, text: str, name: str | None = None) -> Diagram:
        return cls.from_json(json.loads(text), name)

    @classmethod
    def load(cls, path: str | Path) -> Diagram:
        path = Path(path)
        d = cls.loads(path.read_text(encoding="utf-8"), path.stem)
        d.path = path
        return d

    def copy(self) -> Diagram:
        d = Diagram.loads(self.dumps(), self.name)
        d.path = self.path
        return d
