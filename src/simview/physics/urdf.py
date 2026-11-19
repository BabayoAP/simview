"""Load URDF and MJCF robot descriptions into MuJoCo (IO-01)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco

# Robots bundled with SimView, found by bare filename: `scene.add_robot("ur5.urdf")`.
BUNDLED = Path(__file__).resolve().parent.parent / "toolboxes" / "robotics" / "assets"

# MuJoCo can load these mesh formats; anything else (e.g. COLLADA .dae) cannot be imported.
MESH_SUFFIXES = (".stl", ".obj", ".msh")


def resolve(path: str | Path) -> Path:
    """An existing file path, or the name of a bundled robot (`ur5.urdf` or `ur5`)."""
    p = Path(path)
    if p.is_file():
        return p.resolve()
    stem = p.name.removesuffix(".urdf").removesuffix(".xml")
    for candidate in (BUNDLED / stem / f"{stem}.urdf", BUNDLED / stem / f"{stem}.xml"):
        if candidate.is_file():
            return candidate
    from simview.toolboxes.robotics import library  # RB-11: downloaded on first use

    if stem in library.ROBOTS:
        return library.fetch(stem)
    raise FileNotFoundError(
        f"no robot file at {path!s} and no bundled or library robot named {stem!r} "
        f"(library: {', '.join(sorted(library.ROBOTS))})"
    )


def _mesh_path(filename: str, base: Path) -> Path:
    """Resolve a URDF mesh filename: relative to the URDF, or `package://<pkg>/<rel>`."""
    if filename.startswith("package://"):
        rel = filename.removeprefix("package://").split("/", 1)[-1]
        p = base / rel
    elif filename.startswith("file://"):
        p = Path(filename.removeprefix("file://"))
    else:
        p = Path(filename)
        if not p.is_absolute():
            p = base / p
    if p.suffix.lower() not in MESH_SUFFIXES:
        raise ValueError(f"mesh {filename!r}: MuJoCo loads {MESH_SUFFIXES} only, convert it first")
    if not p.is_file():
        raise FileNotFoundError(f"mesh {filename!r} not found (looked for {p})")
    return p


def urdf_to_mujoco_xml(path: Path) -> str:
    """Prepare a URDF for MuJoCo's URDF importer.

    Mesh paths become absolute, and static links (e.g. `tool0`, `flange`) are kept as bodies
    instead of being fused into their parent, so they can be used as kinematic frames.
    Visual geoms are dropped; the collision geoms are what MuJoCo simulates and renders.
    """
    root = ET.parse(path).getroot()
    if root.tag != "robot":
        raise ValueError(f"{path} is not a URDF (root element is <{root.tag}>)")
    for link in root.iter("link"):
        for visual in link.findall("visual"):
            link.remove(visual)
    for mesh in root.iter("mesh"):
        mesh.set("filename", _mesh_path(mesh.get("filename", ""), path.parent).as_posix())
    for old in root.findall("mujoco"):
        root.remove(old)
    ext = ET.Element("mujoco")
    ET.SubElement(ext, "compiler", strippath="false", fusestatic="false", discardvisual="false")
    root.insert(0, ext)
    return ET.tostring(root, encoding="unicode")


def load_model(path: str | Path) -> mujoco.MjModel:
    """Load a `.urdf` or an MJCF (`.xml`) file, or a bundled robot by name, as an MjModel."""
    p = resolve(path)
    if p.suffix.lower() == ".urdf":
        return mujoco.MjModel.from_xml_string(urdf_to_mujoco_xml(p))
    return mujoco.MjModel.from_xml_path(str(p))
