"""SimView's own toolboxes, registered through the same entry point as third-party ones
(TB-01, TB-02, PRD §8 layout). Kept import-light: everything is named by string."""

from __future__ import annotations

from simview.toolboxes.registry import Toolbox


def robotics(tb: Toolbox) -> None:
    tb.add_module("robotics", "simview.toolboxes.robotics")
    tb.add_entity("simview.physics.mujoco_world:Robot")


def aero(tb: Toolbox) -> None:
    tb.add_module("aero", "simview.toolboxes.aero")
    tb.add_entity("simview.toolboxes.aero:Quadrotor")
    tb.add_entity("simview.toolboxes.aero:Wind")


def vehicles(tb: Toolbox) -> None:
    tb.add_module("vehicles", "simview.toolboxes.vehicles")
    tb.add_entity("simview.toolboxes.vehicles:KinematicBicycle")
    tb.add_entity("simview.toolboxes.vehicles:ScriptedNPC")
