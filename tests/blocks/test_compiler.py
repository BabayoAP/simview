"""BD-05: execution order, algebraic loops, and per-block errors."""

from simview.blocks import Diagram, check, compile_diagram


def test_topological_order_puts_sources_first():
    d = Diagram("d")
    d.add("Gain", "g2")
    d.add("Gain", "g1")
    d.add("Constant", "c")
    d.connect("c:0", "g1:0")
    d.connect("g1:0", "g2:0")
    order = [n.path for n in compile_diagram(d).nodes]
    assert order.index("c") < order.index("g1") < order.index("g2")


def test_algebraic_loop_is_reported_with_every_block_in_it():
    d = Diagram("d")
    d.add("Constant", "c")
    d.add("Sum", "s", signs="+-")
    d.add("Gain", "a")
    d.add("Gain", "b")
    d.connect("c:0", "s:0")
    d.connect("s:0", "a:0")
    d.connect("a:0", "b:0")
    d.connect("b:0", "s:1")
    compiled, issues = check(d)
    assert compiled is None
    assert {i.block for i in issues} == {"s", "a", "b"}
    assert all("algebraic loop" in i.message for i in issues)
    # An Integrator in the loop breaks it (no direct feedthrough).
    d.remove("b")
    d.add("Integrator", "b")
    d.connect("a:0", "b:0")
    d.connect("b:0", "s:1")
    assert check(d)[1] == []


def test_problems_name_their_block():
    d = Diagram("d")
    d.add("Constant", "v", value=[1.0, 2.0])
    d.add("Constant", "w", value=[1.0, 2.0, 3.0])
    d.add("Sum", "s")
    d.add("Gain", "lonely")
    d.add("Saturation", "bad", lower=2.0, upper=1.0)
    d.add("EntityState", "e", entity="nobody")
    d.connect("v:0", "s:0")
    d.connect("w:0", "s:1")
    _, issues = check(d, scene=_NoEntities())
    by_block = {i.block: i.message for i in issues}
    assert "not connected" in by_block["lonely"]
    assert "lower must not exceed upper" in by_block["bad"]
    assert "no entity 'nobody'" in by_block["e"]
    d.remove("lonely")
    d.remove("bad")
    d.remove("e")
    _, issues = check(d)
    assert [i.block for i in issues] == ["s"] and "different shapes" in issues[0].message


def test_inport_outside_a_subsystem():
    d = Diagram("d")
    d.add("Inport", "i")
    assert "only works inside a subsystem" in check(d)[1][0].message


class _NoEntities:
    entities: dict = {}

    def __getitem__(self, name):
        raise KeyError(name)
