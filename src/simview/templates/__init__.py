"""Scene templates (PRD §4, DS-08): one folder per start-screen card, each holding a
`scene.py`. Opening a card loads that scene file; Save Project copies it into the project
(D-098). Templates without a scene yet open an empty window. Toolboxes add more cards after
the 4 flagship ones (TB-02)."""

from __future__ import annotations

from pathlib import Path

from simview.toolboxes.registry import TemplateSpec

ROOT = Path(__file__).resolve().parent


def _flagship(id: str, title: str, description: str, icon: str) -> TemplateSpec:  # noqa: A002
    path = ROOT / id / "scene.py"
    return TemplateSpec(id, title, description, icon, path if path.is_file() else None, "simview")


FLAGSHIP: tuple[TemplateSpec, ...] = (
    _flagship(
        "av_scenario", "Autonomous Vehicle", "Bicycle-model car with lidar and camera.", "car"
    ),
    _flagship(
        "drone_delivery", "Drone Delivery", "Quadrotor fleet, wind, GPS + IMU EKF.", "package"
    ),
    _flagship("ur5_ik", "Robotic Arm (UR5)", "Drag the end effector, watch IK solve.", "bot"),
    _flagship(
        "drone_landing", "Drone Landing (RL)", "Gymnasium env for PPO training.", "plane-landing"
    ),
)


def templates() -> list[TemplateSpec]:
    """Every start-screen card: the flagship templates, then those toolboxes add."""
    from simview.toolboxes import registry

    return [*FLAGSHIP, *registry.templates()]


def template(template_id: str) -> TemplateSpec | None:
    return next((t for t in templates() if t.id == template_id), None)


def scene_path(template_id: str) -> Path | None:
    """The template's scene file, or None if it has none (yet)."""
    spec = template(template_id)
    return spec.scene if spec is not None and spec.scene and spec.scene.is_file() else None
