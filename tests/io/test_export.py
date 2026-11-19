"""DA-07: export logged data to CSV, Parquet, and MATLAB .mat."""

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import pytest
from scipy.io import loadmat

from simview.io.export import mat_names, write_table


def table():
    t = np.arange(5) * 0.1
    return pa.table(
        {"t": t, "tick": np.arange(5), "ur5.shoulder.q": np.sin(t), "1st/odd name": t * 2}
    )


def test_csv_and_parquet_round_trip(tmp_path):
    src = table()
    back = pacsv.read_csv(write_table(src, tmp_path / "run.csv"))
    assert back.column_names == src.column_names
    np.testing.assert_allclose(back["ur5.shoulder.q"].to_numpy(), src["ur5.shoulder.q"])
    assert pq.read_table(write_table(src, tmp_path / "out" / "run.parquet")).equals(src)


def test_mat_has_valid_names_and_the_original_ones(tmp_path):
    src = table()
    m = loadmat(write_table(src, tmp_path / "run.MAT"))
    assert {"t", "tick", "ur5_shoulder_q", "s_1st_odd_name", "signal_names"} <= set(m)
    np.testing.assert_allclose(m["ur5_shoulder_q"].ravel(), src["ur5.shoulder.q"])
    assert [str(n[0][0]) for n in m["signal_names"]] == src.column_names


def test_mat_names_are_unique_and_short():
    names = mat_names(["a.b", "a_b", "x" * 80, "x" * 80 + "y"])
    assert names["a.b"] == "a_b" and names["a_b"] == "a_b_2"
    assert len(set(names.values())) == 4 and all(len(n) <= 63 for n in names.values())


def test_unknown_format(tmp_path):
    with pytest.raises(ValueError, match="unknown export format"):
        write_table(table(), tmp_path / "run.xlsx")
