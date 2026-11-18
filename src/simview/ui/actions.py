"""Action registry: every UI action is registered here so the command palette can list it."""

from __future__ import annotations

from collections.abc import Callable

from qtpy.QtGui import QAction, QKeySequence
from qtpy.QtWidgets import QWidget


class ActionRegistry:
    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._actions: dict[str, QAction] = {}

    def register(
        self,
        action_id: str,
        text: str,
        callback: Callable[[], object],
        shortcut: str | QKeySequence.StandardKey | None = None,
        category: str = "General",
    ) -> QAction:
        if action_id in self._actions:
            raise ValueError(f"duplicate action id: {action_id}")
        action = QAction(text, self._parent)
        action.setObjectName(action_id)
        action.setData(category)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: callback())
        self._parent.addAction(action)
        self._actions[action_id] = action
        return action

    def get(self, action_id: str) -> QAction:
        return self._actions[action_id]

    def all(self) -> list[QAction]:
        return list(self._actions.values())


def fuzzy_score(query: str, text: str) -> int | None:
    """Subsequence match score, higher is better; None if `query` doesn't match.

    Rewards consecutive characters and matches at word starts.
    """
    q, s = query.lower().strip(), text.lower()
    if not q:
        return 0
    score, pos, prev = 0, 0, -2
    for ch in q:
        if ch == " ":
            continue
        idx = s.find(ch, pos)
        if idx < 0:
            return None
        score += 1
        if idx == prev + 1:
            score += 5
        if idx == 0 or s[idx - 1] in " -_/:":
            score += 8
        prev, pos = idx, idx + 1
    return score - len(s) // 10


def fuzzy_filter(query: str, labels: list[str]) -> list[str]:
    scored = [(fuzzy_score(query, lbl), i, lbl) for i, lbl in enumerate(labels)]
    hits = [(sc, i, lbl) for sc, i, lbl in scored if sc is not None]
    hits.sort(key=lambda h: (-h[0], h[1]))
    return [lbl for _, _, lbl in hits]
