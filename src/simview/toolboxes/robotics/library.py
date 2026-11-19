"""Robot library (RB-11): MuJoCo Menagerie robots, downloaded on first use.

Robots are fetched at one pinned Menagerie commit into the user cache
(`$SIMVIEW_CACHE`, default `~/.cache/simview`), with the robot's LICENSE and README beside
its files, and then load by name: `scene.add_robot("panda")`. Only the files a robot's MJCF
references are downloaded (its includes, meshes, and textures), not the whole folder.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

MENAGERIE_COMMIT = "370c43965323c0944b433b202aac5058b5f907a9"
RAW = "https://raw.githubusercontent.com/google-deepmind/mujoco_menagerie/{commit}/{path}"


@dataclass(frozen=True)
class Entry:
    folder: str
    file: str
    frame: str  # default frame for FK/IK
    license: str
    description: str


ROBOTS: dict[str, Entry] = {
    "panda": Entry(
        "franka_emika_panda", "panda.xml", "hand", "Apache-2.0", "Franka Emika Panda arm with hand"
    ),
    "panda_nohand": Entry(
        "franka_emika_panda", "panda_nohand.xml", "link7", "Apache-2.0", "Franka Emika Panda arm"
    ),
    "ur10e": Entry(
        "universal_robots_ur10e",
        "ur10e.xml",
        "attachment_site",
        "BSD-3-Clause",
        "Universal Robots UR10e arm",
    ),
    "robotiq_2f85": Entry(
        "robotiq_2f85", "2f85.xml", "pinch", "BSD-2-Clause", "Robotiq 2F-85 parallel gripper"
    ),
}


class FetchError(RuntimeError):
    pass


def cache_root() -> Path:
    return Path(os.environ.get("SIMVIEW_CACHE", Path.home() / ".cache" / "simview"))


def robot_dir(name: str) -> Path:
    entry = ROBOTS[name]
    return cache_root() / "menagerie" / MENAGERIE_COMMIT[:12] / entry.folder


def _download(rel: str, dest: Path) -> None:
    url = RAW.format(commit=MENAGERIE_COMMIT, path=rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https host
            tmp.write_bytes(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FetchError(
            f"could not download {rel} from MuJoCo Menagerie ({exc}). Robots are downloaded "
            "once on first use; connect to the internet, or copy the files into "
            f"{dest.parent} by hand."
        ) from exc
    tmp.replace(dest)


def _referenced(xml_path: Path, folder: str) -> list[str]:
    """Files an MJCF needs: <include>d files (recursively), meshes, textures, and hfields."""
    root = ET.parse(xml_path).getroot()
    compiler = root.find("compiler")
    meshdir = texturedir = assetdir = ""
    if compiler is not None:
        assetdir = compiler.get("assetdir", "")
        meshdir = compiler.get("meshdir", assetdir)
        texturedir = compiler.get("texturedir", assetdir)
    files: list[str] = []
    for el in root.iter():
        name = el.get("file")
        if not name:
            continue
        if el.tag == "include":
            files.append(name)
        elif el.tag == "mesh" or el.tag == "hfield":
            files.append(f"{meshdir}/{name}" if meshdir else name)
        elif el.tag in ("texture", "skin"):
            files.append(f"{texturedir}/{name}" if texturedir else name)
    return files


def fetch(name: str) -> Path:
    """Download robot `name` (if not cached yet) and return the path of its MJCF file."""
    if name not in ROBOTS:
        raise KeyError(f"no library robot {name!r}; available: {', '.join(sorted(ROBOTS))}")
    entry = ROBOTS[name]
    base = robot_dir(name)
    main = base / entry.file
    for extra in ("LICENSE", "README.md"):
        if not (base / extra).exists():
            _download(f"{entry.folder}/{extra}", base / extra)
    todo, seen = [entry.file], set()
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        dest = base / rel
        if not dest.exists():
            _download(f"{entry.folder}/{rel}", dest)
        if dest.suffix == ".xml":
            todo.extend(_referenced(dest, entry.folder))
    return main


def available() -> dict[str, str]:
    """{name: description} of the library robots."""
    return {k: v.description for k, v in ROBOTS.items()}
