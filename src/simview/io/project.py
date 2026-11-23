"""Projects (IO-04): a `.svproj` folder holding a whole project.

    my_robot.svproj/
      project.json   format version, name, the open scene and script (relative paths)
      scenes/        scene files (`scene.py`)
      diagrams/      block diagrams (M7)
      scripts/       editor scripts
      runs/          run logs (Parquet + `.run.json`), the project's run catalog (RI-01)

Everything lives in the folder, so saving writes `project.json` and the open script, and a
project moves or copies as one folder. Nothing here imports Qt.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUFFIX = ".svproj"
MANIFEST = "project.json"
FORMAT = 1
FOLDERS = ("scenes", "diagrams", "scripts", "runs")


class ProjectError(ValueError):
    pass


@dataclass
class Project:
    path: Path
    name: str
    scene: str | None = None  # relative to the project folder
    script: str | None = None
    diagram: str | None = None  # the diagram open in the block editor (M7)
    extra: dict[str, Any] = field(default_factory=dict)  # keys from newer versions, kept

    # -- folders ----------------------------------------------------------------------------
    def folder(self, name: str) -> Path:
        return self.path / name

    @property
    def runs_dir(self) -> Path:
        return self.folder("runs")

    @property
    def scene_path(self) -> Path | None:
        return self.path / self.scene if self.scene else None

    @property
    def script_path(self) -> Path | None:
        return self.path / self.script if self.script else None

    @property
    def diagram_path(self) -> Path | None:
        return self.path / self.diagram if self.diagram else None

    def relative(self, path: Path) -> str | None:
        """`path` relative to the project (posix), or None if it's outside."""
        try:
            return Path(path).resolve().relative_to(self.path.resolve()).as_posix()
        except ValueError:
            return None

    # -- contents ---------------------------------------------------------------------------
    def add_file(self, src: str | Path, folder: str) -> Path:
        """Copy a file into one of the project's folders (no copy if it's already inside the
        project). Returns its path in the project."""
        src = Path(src)
        if self.relative(src) is not None:
            return src.resolve()
        dest = self.folder(folder) / src.name
        if dest.exists() and dest.resolve() != src.resolve():
            stem, i = dest.stem, 1
            while dest.exists():
                dest = dest.with_name(f"{stem}-{i}{dest.suffix}")
                i += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest

    def set_scene(self, path: str | Path | None) -> Path | None:
        """Make a scene file the project's scene (copied into `scenes/` if needed)."""
        if path is None:
            self.scene = None
            return None
        dest = self.add_file(path, "scenes")
        self.scene = self.relative(dest)
        return dest

    def set_script(self, path: str | Path | None) -> Path | None:
        if path is None:
            self.script = None
            return None
        dest = self.add_file(path, "scripts")
        self.script = self.relative(dest)
        return dest

    def files(self, folder: str, pattern: str = "*") -> list[Path]:
        return sorted(p for p in self.folder(folder).glob(pattern) if p.is_file())

    # -- saving -----------------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        return {
            **self.extra,
            "format": FORMAT,
            "name": self.name,
            "scene": self.scene,
            "script": self.script,
            **({"diagram": self.diagram} if self.diagram else {}),
        }

    def save(self) -> Path:
        for f in FOLDERS:
            self.folder(f).mkdir(parents=True, exist_ok=True)
        manifest = self.path / MANIFEST
        manifest.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
        return manifest


def project_path(path: str | Path) -> Path:
    """`path` with the `.svproj` suffix."""
    path = Path(path)
    return path if path.suffix == SUFFIX else path.with_name(path.name + SUFFIX)


def is_project(path: str | Path) -> bool:
    return (Path(path) / MANIFEST).is_file()


def create(path: str | Path, name: str | None = None) -> Project:
    """A new, empty project folder (adds `.svproj` to the name if missing)."""
    path = project_path(path)
    if path.exists() and any(path.iterdir()):
        raise ProjectError(f"{path} already exists and isn't empty")
    project = Project(path=path, name=name or path.stem)
    project.save()
    return project


def load(path: str | Path) -> Project:
    path = Path(path)
    manifest = path / MANIFEST
    if not manifest.is_file():
        raise ProjectError(f"{path} isn't a SimView project (no {MANIFEST})")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{manifest} is not valid JSON: {exc}") from exc
    if int(data.get("format", 0)) > FORMAT:
        raise ProjectError(f"{path.name} was saved by a newer SimView (format {data['format']})")
    for key in ("scene", "script", "diagram"):  # D-136: files stay inside the project
        rel = data.get(key)
        if rel is not None and not (isinstance(rel, str) and _inside(path, rel)):
            raise ProjectError(f"{manifest}: {key} {rel!r} is not a file inside the project")
    known = {"format", "name", "scene", "script", "diagram"}
    project = Project(
        path=path,
        name=str(data.get("name") or path.stem),
        scene=data.get("scene"),
        script=data.get("script"),
        diagram=data.get("diagram"),
        extra={k: v for k, v in data.items() if k not in known},
    )
    for f in FOLDERS:  # a hand-made or older project may lack some
        project.folder(f).mkdir(parents=True, exist_ok=True)
    return project


def _inside(root: Path, rel: str) -> bool:
    """Whether `rel` is a relative path that stays inside `root` (symlinks resolved), so a
    hand-edited project.json can't point the editor's saves outside the folder (D-136)."""
    if not rel or Path(rel).is_absolute() or Path(rel).drive:
        return False
    base = root.resolve()
    return (base / rel).resolve().is_relative_to(base)
