"""Run manifests (RP-01): what is needed to reproduce a run later or elsewhere.

Every run's context sidecar (`<run>.run.json`, D-056) carries a `manifest`: SimView, Python and
key package versions, installed toolboxes, OS and CPU, the project's git commit and dirty flag,
hashes of the scene's source files, diagrams and datasets, and the run's seed, parameters and
duration (read back from the log's own metadata). The log itself is untouched, so the same seed
still gives a byte-identical Parquet file (NF-06).

Machine info (OS, CPU, hostname) is on by default; set `SIMVIEW_NO_MACHINE_INFO=1` (or pass
`--no-machine-info` to `simview run` / `simview test`) to leave it out (D-141).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Any

FORMAT = 1
MANIFEST_KEY = "manifest"
NO_MACHINE_ENV = "SIMVIEW_NO_MACHINE_INFO"
PACKAGES = ("numpy", "mujoco", "scipy", "pyarrow")
# Files next to the scene that are hashed (not recursive: a scene in a big folder stays cheap)
SOURCE_SUFFIXES = frozenset(
    {".py", ".svd", ".toml", ".json", ".xml", ".urdf", ".mjcf", ".yaml", ".yml", ".csv"}
)
MAX_HASH_BYTES = 64 * 1024 * 1024  # bigger files are listed as "skipped (size)"
_GIT_TIMEOUT = 5.0


def machine_info_enabled() -> bool:
    return os.environ.get(NO_MACHINE_ENV, "").strip().lower() not in ("1", "true", "yes")


def file_hash(path: Path) -> str:
    """`sha256:<hex>` of a file, or a note when it's too big or unreadable."""
    try:
        if path.stat().st_size > MAX_HASH_BYTES:
            return "skipped (size)"
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return "sha256:" + h.hexdigest()
    except OSError as exc:
        return f"unreadable ({exc.__class__.__name__})"


def folder_hash(folder: Path) -> str:
    """One hash over every file in a folder (relative names and contents, sorted)."""
    h = hashlib.sha256()
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    for p in files:
        h.update(p.relative_to(folder).as_posix().encode())
        h.update(b"\0")
        h.update(file_hash(p).encode())
        h.update(b"\0")
    return f"sha256:{h.hexdigest()} ({len(files)} files)"


@lru_cache(maxsize=1)
def environment() -> dict[str, Any]:
    """Versions and installed toolboxes (cached per process: they don't change in a run)."""
    import simview

    packages: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    try:
        from simview.toolboxes.registry import discover

        toolboxes = {name: info.version for name, info in sorted(discover().items())}
    except Exception as exc:  # noqa: BLE001 - a manifest never fails a run
        toolboxes = {"?": f"discovery failed: {exc}"}
    return {
        "simview": simview.__version__,
        "python": platform.python_version(),
        "packages": packages,
        "toolboxes": toolboxes,
    }


@lru_cache(maxsize=1)
def machine() -> dict[str, Any]:
    cpu = platform.processor() or platform.machine()
    if platform.system() == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    return {
        "os": platform.platform(),
        "cpu": cpu,
        "cores": os.cpu_count(),
        "hostname": socket.gethostname(),
    }


def git_state(folder: Path) -> dict[str, Any] | None:
    """The commit and dirty flag of the git repo holding `folder` (None if not a repo or no
    git)."""

    def git(*args: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(folder), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=True,
        )
        return out.stdout.strip()

    try:
        commit = git("rev-parse", "HEAD")
        dirty = bool(git("status", "--porcelain"))
        root = git("rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return None
    return {"commit": commit, "dirty": dirty, "root": root}


def _key(path: Path, base: Path | None) -> str:
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def source_files(scene_file: Path) -> list[Path]:
    """The scene file and the source files beside it (not recursive)."""
    folder = scene_file.parent
    out = {scene_file}
    try:
        out |= {p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES}
    except OSError:
        pass
    return sorted(out)


def file_hashes(scene: Any = None, scene_file: str | Path | None = None) -> dict[str, str]:  # noqa: ANN401
    """Hashes of the scene's source files, its diagrams and the datasets opened while it
    loaded and ran. Keys are relative to the scene's folder when inside it."""
    path: Path | None = None
    if scene_file is not None:
        path = Path(scene_file).resolve()
    elif scene is not None and getattr(scene, "file", None) is not None:
        path = Path(scene.file).resolve()
    base = path.parent if path is not None else None
    hashes: dict[str, str] = {}
    if path is not None and path.is_file():
        for p in source_files(path):
            hashes[_key(p, base)] = file_hash(p)
    if scene is not None:
        for run in getattr(scene, "diagrams", {}).values():
            dpath = getattr(getattr(run, "diagram", None), "path", None)
            if dpath is not None and Path(dpath).is_file():
                p = Path(dpath).resolve()
                hashes.setdefault(_key(p, base), file_hash(p))
    from simview.perception.dataset import opened_datasets

    for folder in sorted(opened_datasets()):
        if folder.is_dir():
            hashes.setdefault(_key(folder, base) + "/", folder_hash(folder))
    return hashes


def _log_meta(log: Path | None) -> dict[str, Any]:
    if log is None or not log.exists():
        return {}
    try:
        import pyarrow.parquet as pq

        raw = (pq.read_schema(log).metadata or {}).get(b"simview")
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001 - not a SimView log
        return {}


def build_manifest(
    scene: Any = None,  # noqa: ANN401 - a simview.Scene
    *,
    scene_file: str | Path | None = None,
    log: str | Path | None = None,
    machine_info: bool | None = None,
) -> dict[str, Any]:
    """The manifest for a run of `scene` (or of `scene_file`, for runs whose scene lives in
    another process). Seed, parameters and duration come from the log's metadata."""
    meta = _log_meta(Path(log) if log is not None else None)
    out: dict[str, Any] = {"format": FORMAT, **environment()}
    if machine_info if machine_info is not None else machine_info_enabled():
        out["machine"] = machine()
    path = scene_file or (getattr(scene, "file", None) if scene is not None else None)
    out["git"] = git_state(Path(path).resolve().parent) if path is not None else None
    out["files"] = file_hashes(scene, scene_file)
    seed = meta.get("seed", getattr(scene, "seed", None))
    out["seed"] = seed
    if "params" in meta:
        out["params"] = meta["params"]
    elif scene is not None:
        out["params"] = scene.params.to_json()
    if "duration" in meta:
        out["duration"] = meta["duration"]
    return out


def read_manifest(run: str | Path) -> dict[str, Any] | None:
    """A run's manifest from its context sidecar (None for runs made before RP-01)."""
    side = Path(run).with_suffix(".run.json")
    try:
        return json.loads(side.read_text(encoding="utf-8")).get(MANIFEST_KEY)
    except (OSError, ValueError, AttributeError):
        return None


def differences(run: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """Human-readable environment differences between a run's manifest and now (RP-02)."""
    out: list[str] = []

    def diff(label: str, a: Any, b: Any) -> None:  # noqa: ANN401
        if a != b:
            was, now_ = ("—" if v is None else v for v in (a, b))
            out.append(f"{label}: {was} (run) vs {now_} (now)")

    diff("SimView", run.get("simview"), now.get("simview"))
    diff("Python", run.get("python"), now.get("python"))
    rp, np_ = run.get("packages", {}), now.get("packages", {})
    for name in sorted(set(rp) | set(np_)):
        diff(name, rp.get(name), np_.get(name))
    rt, nt = run.get("toolboxes", {}), now.get("toolboxes", {})
    for name in sorted(set(rt) | set(nt)):
        diff(f"toolbox {name}", rt.get(name), nt.get(name))
    rm, nm = run.get("machine"), now.get("machine")
    if rm and nm:
        for k in ("os", "cpu", "hostname"):
            diff(k.upper() if k != "hostname" else "hostname", rm.get(k), nm.get(k))
    rg, ng = run.get("git") or {}, now.get("git") or {}
    if rg or ng:
        diff("git commit", rg.get("commit"), ng.get("commit"))
        if ng.get("dirty") and not rg.get("dirty"):
            out.append("git: the working tree has uncommitted changes now")
    rf, nf = run.get("files", {}), now.get("files", {})
    for name in sorted(set(rf) | set(nf)):
        if name not in nf:
            out.append(f"file {name}: missing now")
        elif name not in rf:
            out.append(f"file {name}: new since the run")
        elif rf[name] != nf[name]:
            out.append(f"file {name}: changed since the run")
    return out
