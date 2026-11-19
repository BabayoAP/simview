"""Export logged data to CSV, Parquet, or MATLAB `.mat` (DA-07)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pyarrow as pa

FORMATS = {".csv": "CSV", ".parquet": "Parquet", ".mat": "MATLAB"}
_MAT_NAME_MAX = 63  # MATLAB's namelengthmax


def mat_names(columns: list[str]) -> dict[str, str]:
    """Column -> valid, unique MATLAB variable name (`ur5.shoulder.q` -> `ur5_shoulder_q`)."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for col in columns:
        name = re.sub(r"\W", "_", col)
        if not name or not name[0].isalpha():
            name = f"s_{name}"
        name = name[:_MAT_NAME_MAX]
        base, k = name, 2
        while name in used:
            suffix = f"_{k}"
            name = base[: _MAT_NAME_MAX - len(suffix)] + suffix
            k += 1
        used.add(name)
        out[col] = name
    return out


def write_table(table: pa.Table, path: str | Path) -> Path:
    """Write every column of `table`; the format follows the file extension."""
    path = Path(path)
    ext = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".csv":
        import pyarrow.csv as pacsv

        pacsv.write_csv(table, path)
    elif ext == ".parquet":
        import pyarrow.parquet as pq

        pq.write_table(table, path)
    elif ext == ".mat":
        from scipy.io import savemat

        names = mat_names(table.column_names)
        data: dict[str, object] = {
            names[c]: np.asarray(table.column(c).to_numpy(), dtype=np.float64).reshape(-1, 1)
            for c in table.column_names
        }
        # The original signal names, in column order, as a cell array.
        data["signal_names"] = np.array(table.column_names, dtype=object).reshape(-1, 1)
        savemat(path, data, do_compression=True)
    else:
        raise ValueError(f"unknown export format {ext!r}; use one of {', '.join(FORMATS)}")
    return path
