"""Import CSV and `.mat` data (IO-02) as plain NumPy objects for the workspace.

- `load_csv(path)`: a record array with one field per column (`data["t"]`), read with a
  header row. Numeric columns are float64; others stay text.
- `load_mat(path)`: the file's variables by name, via `scipy.io.loadmat` (MATLAB v5-v7.2
  files; v7.3 files are HDF5 and need re-saving with `-v7`).
"""

from __future__ import annotations

import csv
import keyword
import re
from pathlib import Path
from typing import Any

import numpy as np


def variable_name(text: str) -> str:
    """A valid Python identifier from a file name or column header."""
    name = re.sub(r"\W", "_", text.strip()) or "data"
    if name[0].isdigit():
        name = "_" + name
    if keyword.iskeyword(name):
        name += "_"
    return name


def load_csv(path: str | Path) -> np.ndarray:
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if not rows:
        raise ValueError(f"{path.name} is empty")
    header, body = rows[0], rows[1:]
    names: list[str] = []
    for i, h in enumerate(header):
        name = h.strip() or f"col{i}"
        while name in names:
            name += "_"
        names.append(name)
    width = len(names)
    columns: list[list[str]] = [[] for _ in names]
    for r in body:
        r = (r + [""] * width)[:width]
        for i, cell in enumerate(r):
            columns[i].append(cell.strip())
    arrays: list[np.ndarray] = []
    for col in columns:
        try:
            arrays.append(np.array([float(v) if v else np.nan for v in col], dtype=np.float64))
        except ValueError:
            arrays.append(np.array(col, dtype=str))
    dtype = [(n, a.dtype) for n, a in zip(names, arrays, strict=True)]
    out = np.empty(len(body), dtype=dtype)
    for n, a in zip(names, arrays, strict=True):
        out[n] = a
    return out


def load_mat(path: str | Path) -> dict[str, Any]:
    from scipy.io import loadmat

    raw = loadmat(str(path), squeeze_me=True)
    return {k: v for k, v in raw.items() if not k.startswith("__")}


def load_data(path: str | Path) -> dict[str, Any]:
    """Workspace variables from a data file: a `.mat` file's variables, or a CSV file as one
    record array named after the file."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".mat":
        return load_mat(path)
    if suffix in (".csv", ".txt"):
        return {variable_name(path.stem): load_csv(path)}
    raise ValueError(f"can't import {path.name}: expected a .csv or .mat file")
