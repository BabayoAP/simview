"""The run catalog (RI-01): every run's Parquet log in a folder, with its metadata.

A run is a Parquet file with columns `t`, `tick`, and one per signal (SE-06), and a `simview`
JSON entry in the schema metadata: dt, seed, duration, scene, date, source, params. Simulated
runs (`sv.run`, or the app when a run is stopped) and imported robot logs (RI-06) look the same.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

DEFAULT_FOLDER = "runs"


@dataclass(frozen=True)
class RunInfo:
    path: Path
    dt: float
    rows: int
    signals: tuple[str, ...]
    scene: str | None = None  # the scene file the run came from (needed to replay it)
    seed: int | None = None
    date: str = ""  # ISO 8601
    duration: float = 0.0  # s
    source: str = "sim"  # "sim", "app", or "import"
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.stem

    def matches(self, text: str) -> bool:
        """Case-insensitive search over name, scene, source, date, and seed."""
        hay = " ".join(
            str(v) for v in (self.name, self.scene or "", self.source, self.date, self.seed)
        )
        return text.lower() in hay.lower()


def read_info(path: str | Path) -> RunInfo:
    """A run's metadata from its Parquet footer (the data isn't read)."""
    path = Path(path)
    schema = pq.read_schema(path)
    meta: dict[str, Any] = {}
    raw = (schema.metadata or {}).get(b"simview")
    if raw:
        meta = json.loads(raw)
    side = path.with_suffix(".run.json")  # context: date, scene file (D-056)
    if side.exists():
        try:
            meta.update(json.loads(side.read_text(encoding="utf-8")))
        except ValueError:
            pass
    rows = pq.ParquetFile(path).metadata.num_rows
    signals = tuple(n for n in schema.names if n not in ("t", "tick"))
    date = meta.get("date") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(
        timespec="seconds"
    )
    dt = float(meta.get("dt", 0.0))
    duration = float(meta.get("duration", max(rows - 1, 0) * dt))
    return RunInfo(
        path=path,
        dt=dt,
        rows=rows,
        signals=signals,
        scene=meta.get("scene"),
        seed=meta.get("seed"),
        date=date,
        duration=duration,
        source=meta.get("source", "sim"),
        params=dict(meta.get("params", {})),
    )


class RunData:
    """One run's logged signals, read on first use."""

    def __init__(self, info: RunInfo) -> None:
        self.info = info
        self._table = pq.read_table(info.path)
        self.t = self._table.column("t").to_numpy().astype(np.float64)
        self._cache: dict[str, np.ndarray] = {}

    @property
    def signals(self) -> tuple[str, ...]:
        return self.info.signals

    @property
    def dt(self) -> float:
        """The sample period: from the metadata, or the median spacing of `t`."""
        if self.info.dt > 0:
            return self.info.dt
        return float(np.median(np.diff(self.t))) if len(self.t) > 1 else 0.0

    def __contains__(self, name: str) -> bool:
        return name == "t" or name in self.info.signals

    def __getitem__(self, name: str) -> np.ndarray:
        if name == "t":
            return self.t
        if name not in self._cache:
            if name not in self.info.signals:
                raise KeyError(name)
            self._cache[name] = self._table.column(name).to_numpy().astype(np.float64)
        return self._cache[name]

    def index_at(self, t: float) -> int:
        return int(np.clip(np.searchsorted(self.t, t), 0, len(self.t) - 1))


class Catalog:
    """Every run in a folder (RI-01). Runs are listed newest first."""

    def __init__(self, folder: str | Path = DEFAULT_FOLDER) -> None:
        self.folder = Path(folder)

    def runs(self) -> list[RunInfo]:
        if not self.folder.is_dir():
            return []
        infos = []
        for p in self.folder.glob("*.parquet"):
            try:
                infos.append(read_info(p))
            except Exception:  # noqa: BLE001, S112 - a broken file mustn't hide the others
                continue
        return sorted(infos, key=lambda r: (r.date, r.name), reverse=True)

    def filter(
        self,
        text: str = "",
        *,
        scene: str | None = None,
        source: str | None = None,
        seed: int | None = None,
    ) -> list[RunInfo]:
        out = []
        for r in self.runs():
            if text and not r.matches(text):
                continue
            if scene is not None and (r.scene is None or Path(r.scene).name != Path(scene).name):
                continue
            if source is not None and r.source != source:
                continue
            if seed is not None and r.seed != seed:
                continue
            out.append(r)
        return out

    def get(self, name: str) -> RunInfo:
        """A run by file name (with or without `.parquet`) or path."""
        p = Path(name)
        if p.suffix != ".parquet":
            p = p.with_suffix(".parquet")
        if not p.is_absolute() and not p.exists():
            p = self.folder / p.name
        if not p.exists():
            raise FileNotFoundError(f"no run {name!r} in {self.folder}")
        return read_info(p)

    def open(self, run: RunInfo | str | Path) -> RunData:
        return RunData(run if isinstance(run, RunInfo) else self.get(str(run)))

    def new_path(self, stem: str) -> Path:
        """A free `<folder>/<stem>.parquet` (adds -1, -2, … if taken)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{stem}.parquet"
        i = 1
        while path.exists():
            path = self.folder / f"{stem}-{i}.parquet"
            i += 1
        return path


def run_stem(seed: int | None, when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-seed{seed}" if seed is not None else stamp
