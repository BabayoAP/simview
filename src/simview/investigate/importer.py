"""Import real robot logs as runs (RI-06): CSV or Parquet, with a column mapping.

`mapping` renames log columns to SimView signals (`{"ur5.shoulder_pan_joint.q": "joint1_pos"}`):
mapped columns become entity states, so the run replays in the viewport with that scene. Other
numeric columns are kept under their own names (scannable, plotted in reports). Time comes from
`time_column` (seconds, scaled by `time_scale`, e.g. 1e-3 for ms), shifted to start at 0; the
sample period is the median spacing. Rows are sorted by time and duplicate times dropped.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from simview.investigate.runs import Catalog, RunInfo, read_info, run_stem


def _read(path: Path) -> pa.Table:
    ext = path.suffix.lower()
    if ext == ".csv":
        import pyarrow.csv as pacsv

        return pacsv.read_csv(path)
    if ext == ".parquet":
        return pq.read_table(path)
    raise ValueError(f"can't import {ext!r} files; use .csv or .parquet")


def read_columns(path: str | Path) -> list[str]:
    """The column names of a CSV or Parquet log (for building a mapping)."""
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return list(pq.read_schema(p).names)
    return _read(p).column_names


def import_log(
    path: str | Path,
    catalog: Catalog,
    *,
    mapping: Mapping[str, str] | None = None,
    time_column: str = "t",
    time_scale: float = 1.0,
    scene: str | Path | None = None,
    name: str | None = None,
) -> RunInfo:
    """Write the log into the catalog as a run and return its info."""
    src = Path(path)
    table = _read(src)
    if time_column not in table.column_names:
        raise ValueError(f"{src.name} has no time column {time_column!r}")
    mapping = dict(mapping or {})
    for signal, column in mapping.items():
        if column not in table.column_names:
            raise ValueError(f"{src.name} has no column {column!r} (mapped to {signal})")
    t = table.column(time_column).to_numpy().astype(np.float64) * time_scale
    order = np.argsort(t, kind="stable")
    t = t[order]
    keep = np.concatenate([[True], np.diff(t) > 0]) if len(t) else np.zeros(0, bool)
    t = t[keep] - (t[0] if len(t) else 0.0)
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0

    def column(name: str) -> np.ndarray:
        values = table.column(name).to_numpy(zero_copy_only=False).astype(np.float64)
        return values[order][keep]

    columns: dict[str, pa.Array] = {
        "t": pa.array(t),
        "tick": pa.array(np.round(t / dt).astype(np.int64) if dt > 0 else np.arange(len(t))),
    }
    for signal, col in mapping.items():
        columns[signal] = pa.array(column(col))
    used = {time_column, *mapping.values()}
    for col in table.column_names:
        if col in used or col in columns:
            continue
        if pa.types.is_integer(table.schema.field(col).type) or pa.types.is_floating(
            table.schema.field(col).type
        ):
            columns[col] = pa.array(column(col))
    meta = {
        "dt": dt,
        "duration": float(t[-1]) if len(t) else 0.0,
        "source": "import",
        "mapping": mapping,
    }
    out = catalog.new_path(name or f"{run_stem(None)}-{src.stem}")
    out_table = pa.table(columns).replace_schema_metadata(
        {b"simview": json.dumps(meta, sort_keys=True).encode()}
    )
    pq.write_table(out_table, out)
    context = {"date": datetime.now().isoformat(timespec="seconds"), "file": str(src.resolve())}
    if scene is not None:
        context["scene"] = str(Path(scene).resolve())
    out.with_suffix(".run.json").write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
    return read_info(out)
