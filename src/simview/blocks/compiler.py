"""Compile a diagram to an execution graph (BD-05). Qt-free.

1. Flatten subsystems: inner blocks get paths like `ctrl/gain1`; Inports and Outports are
   traced through, so every input names a real source block.
2. Make each block (its parameters checked) and bind it to the scene (entity blocks).
3. Check every input has exactly one wire.
4. Order blocks topologically over direct-feedthrough edges. A cycle there is an algebraic
   loop: reported with every block in it.
5. Probe: evaluate once at t = 0, so shape mismatches are reported on the block that has them.

Problems come back as `Issue(block path, message)`, all of them at once, so the editor can
outline every offending block (§7.7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from simview.blocks.graph import Diagram
from simview.blocks.library import Block, BlockError, block_class


@dataclass(frozen=True)
class Issue:
    block: str  # flat path, e.g. "ctrl/gain1" (empty for the whole diagram)
    message: str

    def __str__(self) -> str:
        return f"{self.block}: {self.message}" if self.block else self.message


class DiagramError(ValueError):
    def __init__(self, issues: list[Issue], name: str = "diagram") -> None:
        self.issues = issues
        listed = "\n".join(f"  {i}" for i in issues)
        super().__init__(f"diagram {name!r} has {len(issues)} problem(s):\n{listed}")


@dataclass
class Node:
    path: str
    block: Block
    inputs: list[tuple[int, int]]  # (node index, output port) per input
    xs: slice = field(default_factory=lambda: slice(0, 0))


@dataclass
class Compiled:
    nodes: list[Node]  # in execution order
    x0: np.ndarray
    shapes: dict[tuple[str, int], tuple[int, ...]]  # (path, output port) -> shape

    def index(self, path: str) -> int:
        return next(i for i, n in enumerate(self.nodes) if n.path == path)

    def reset(self, ts: float) -> None:
        for n in self.nodes:
            n.block.ts = ts
            n.block.reset()

    def outputs(
        self, t: float, x: np.ndarray, held: dict[int, list[np.ndarray]] | None = None
    ) -> list[list[np.ndarray]]:
        """Every block's outputs at time t. `held` gives discrete blocks' outputs between
        samples (they are computed only at samples)."""
        outs: list[list[np.ndarray]] = [[] for _ in self.nodes]
        for i, n in enumerate(self.nodes):
            if held is not None and i in held:
                outs[i] = held[i]
                continue
            u = [outs[j][p] for j, p in n.inputs] if n.block.feedthrough else None
            outs[i] = n.block.output(t, x[n.xs], u)
        return outs

    def inputs(self, i: int, outs: list[list[np.ndarray]]) -> list[np.ndarray]:
        return [outs[j][p] for j, p in self.nodes[i].inputs]

    def derivative(
        self, t: float, x: np.ndarray, held: dict[int, list[np.ndarray]] | None = None
    ) -> np.ndarray:
        outs = self.outputs(t, x, held)
        dx = np.zeros_like(x)
        for i, n in enumerate(self.nodes):
            if n.xs.stop > n.xs.start:
                dx[n.xs] = n.block.derivative(t, x[n.xs], self.inputs(i, outs))
        return dx


# -- flattening ---------------------------------------------------------------------------
_PASS = ("Inport", "Outport")


def _flatten(
    d: Diagram, prefix: str, blocks: dict[str, Any], wires: list[tuple[str, int, str, int]]
) -> None:
    """Leaf blocks by path (Inports/Outports kept as pass-throughs), and wires between them."""

    def port_node(sub_path: str, kind: str, index: int) -> str | None:
        sub = blocks.get(f"__sub__{sub_path}")
        assert sub is not None
        for b in sub.diagram.blocks.values():
            if b.type == kind and int(b.params.get("index", 1)) == index:
                return f"{sub_path}/{b.id}"
        return None

    for b in d.blocks.values():
        path = prefix + b.id
        if b.is_subsystem:
            blocks[f"__sub__{path}"] = b
            _flatten(b.diagram, path + "/", blocks, wires)
        else:
            blocks[path] = b
    for w in d.wires:
        src, sp = prefix + w.src, w.src_port
        dst, dp = prefix + w.dst, w.dst_port
        if f"__sub__{src}" in blocks:
            node = port_node(src, "Outport", sp + 1)
            if node is None:
                continue
            src, sp = node, 0
        if f"__sub__{dst}" in blocks:
            node = port_node(dst, "Inport", dp + 1)
            if node is None:
                continue
            dst, dp = node, 0
        wires.append((src, sp, dst, dp))


def _toposort(n: int, edges: list[tuple[int, int]]) -> tuple[list[int], list[list[int]]]:
    """Kahn's order (ties by index, so it's deterministic) and the cycles (Tarjan SCCs)."""
    adj: list[list[int]] = [[] for _ in range(n)]
    indeg = [0] * n
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1
    import heapq

    ready = [i for i in range(n) if indeg[i] == 0]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        i = heapq.heappop(ready)
        order.append(i)
        for j in adj[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                heapq.heappush(ready, j)
    if len(order) == n:
        return order, []
    # Tarjan, iterative enough for diagram sizes (recursion depth = loop length).
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    stack: list[int] = []
    on: set[int] = set()
    sccs: list[list[int]] = []

    def strong(v: int) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        on.add(v)
        for w in adj[v]:
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or v in adj[v]:
                sccs.append(sorted(comp))

    for v in range(n):
        if v not in index:
            strong(v)
    return order, sccs


def compile_diagram(
    diagram: Diagram, scene: Any = None, base: Path | None = None, ts: float = 0.0
) -> Compiled:
    """The execution graph, or DiagramError with every problem found."""
    compiled, issues = check(diagram, scene, base, ts)
    if issues:
        raise DiagramError(issues, diagram.name)
    assert compiled is not None
    return compiled


def check(
    diagram: Diagram, scene: Any = None, base: Path | None = None, ts: float = 0.0
) -> tuple[Compiled | None, list[Issue]]:
    """Compile without raising: (graph or None, problems). The editor calls this."""
    if base is None and diagram.path is not None:
        base = diagram.path.parent
    raw: dict[str, Any] = {}
    wires: list[tuple[str, int, str, int]] = []
    _flatten(diagram, "", raw, wires)
    leaves = {p: b for p, b in raw.items() if not p.startswith("__sub__")}
    issues: list[Issue] = []

    # Make and bind the blocks.
    made: dict[str, Block] = {}
    for path, model in leaves.items():
        if model.type in _PASS:
            if "/" not in path:
                issues.append(Issue(path, f"an {model.type} only works inside a subsystem"))
            continue
        try:
            block = block_class(model.type)(path, model.params, base)
            if scene is not None:
                block.bind(scene)
        except BlockError as exc:
            issues.append(Issue(path, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - user code in a Python Function block
            issues.append(Issue(path, f"{type(exc).__name__}: {exc}"))
            continue
        made[path] = block

    # Trace each input back through Inports / Outports to a real source.
    feeds: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for s, sp, d, dp in wires:
        feeds.setdefault((d, dp), []).append((s, sp))

    def source(path: str, port: int) -> tuple[str, int] | None:
        seen = set()
        while path in leaves and leaves[path].type in _PASS:
            if path in seen:
                return None
            seen.add(path)
            got = feeds.get((path, 0))
            if not got:
                return None
            path, port = got[0]
        return (path, port) if path in made else None

    paths = list(made)
    pos = {p: i for i, p in enumerate(paths)}
    inputs: dict[str, list[tuple[int, int]]] = {}
    for path, block in made.items():
        names = block.input_names()
        ins: list[tuple[int, int]] = []
        for k in range(block.n_in):
            got = feeds.get((path, k), [])
            if len(got) > 1:
                issues.append(Issue(path, f"input {names[k]} has {len(got)} wires"))
                continue
            src = source(*got[0]) if got else None
            if src is None:
                failed = got and got[0][0] in leaves and got[0][0] not in made
                if not failed or leaves[got[0][0]].type in _PASS:
                    issues.append(Issue(path, f"input {names[k]} is not connected"))
                # else: its source block has a problem of its own, reported there
                continue
            if src[1] >= made[src[0]].n_out:
                issues.append(Issue(path, f"input {names[k]} comes from a missing output"))
                continue
            ins.append((pos[src[0]], src[1]))
        inputs[path] = ins
    for _s, _sp, d, dp in wires:
        if d in made and dp >= made[d].n_in:
            issues.append(Issue(d, f"a wire goes to input {dp + 1}, but it has {made[d].n_in}"))
    if issues:
        return None, issues

    # Order and algebraic loops (BD-05).
    edges = [
        (src, pos[path])
        for path, block in made.items()
        if block.feedthrough
        for src, _ in inputs[path]
    ]
    order, loops = _toposort(len(paths), edges)
    for comp in loops:
        names = [paths[i] for i in comp]
        chain = " → ".join([*names, names[0]])
        for name in names:
            issues.append(Issue(name, f"algebraic loop: {chain}"))
    if issues:
        return None, issues

    new_index = {old: new for new, old in enumerate(order)}
    nodes: list[Node] = []
    start = 0
    x0_parts: list[np.ndarray] = []
    for old in order:
        path = paths[old]
        block = made[path]
        x0 = block.x0()
        node = Node(
            path, block, [(new_index[j], p) for j, p in inputs[path]], slice(start, start + len(x0))
        )
        start += len(x0)
        x0_parts.append(x0)
        nodes.append(node)
    x0 = np.concatenate(x0_parts) if x0_parts else np.zeros(0)
    compiled = Compiled(nodes, x0, {})

    # Probe shapes (and catch blocks that fail on their inputs).
    compiled.reset(ts)
    outs: list[list[np.ndarray]] = [[] for _ in nodes]
    for i, n in enumerate(nodes):
        try:
            u = [outs[j][p] for j, p in n.inputs] if n.block.feedthrough else None
            if u is not None and any(len(outs[j]) <= p for j, p in n.inputs):
                raise BlockError("an input comes from a block that failed")
            got = n.block.output(0.0, x0[n.xs], u)
            if len(got) != n.block.n_out:
                raise BlockError(f"returned {len(got)} outputs, expected {n.block.n_out}")
            outs[i] = [np.asarray(v, dtype=np.float64) for v in got]
        except Exception as exc:  # noqa: BLE001 - reported on the block, never raised
            msg = str(exc) if isinstance(exc, BlockError) else f"{type(exc).__name__}: {exc}"
            issues.append(Issue(n.path, msg))
            outs[i] = []
    if not issues:
        for i, n in enumerate(nodes):
            if n.xs.stop > n.xs.start:
                try:
                    dx = n.block.derivative(0.0, x0[n.xs], compiled.inputs(i, outs))
                    if np.shape(dx) != (n.xs.stop - n.xs.start,):
                        raise BlockError("its state derivative has the wrong size")
                except Exception as exc:  # noqa: BLE001
                    issues.append(Issue(n.path, str(exc)))
    compiled.shapes = {
        (n.path, k): tuple(np.shape(v))
        for n, vals in zip(nodes, outs, strict=True)
        for k, v in enumerate(vals)
    }
    compiled.reset(ts)
    return (None if issues else compiled), issues
