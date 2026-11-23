"""Flagship scene templates (PRD §4, DS-08): one folder per start-screen card, each holding a
`scene.py`. Opening a card loads that scene file; Save Project copies it into the project
(D-098). Templates without a scene yet open an empty window."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def scene_path(template_id: str) -> Path | None:
    """The template's scene file, or None if it has none (yet)."""
    path = ROOT / template_id / "scene.py"
    return path if path.is_file() else None
