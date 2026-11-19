"""Block diagrams (PRD §5.3): the model, the library, the compiler, and the runtime."""

from simview.blocks.compiler import DiagramError, Issue, check, compile_diagram
from simview.blocks.graph import Diagram
from simview.blocks.library import BLOCKS, CATEGORIES, register

__all__ = [
    "BLOCKS",
    "CATEGORIES",
    "Diagram",
    "DiagramError",
    "Issue",
    "check",
    "compile_diagram",
    "register",
]
