"""IO-02: CSV and .mat data as NumPy objects."""

import numpy as np
import pytest
from scipy.io import savemat

from simview.io.data import load_csv, load_data, load_mat, variable_name


def test_csv_becomes_a_record_array(tmp_path):
    p = tmp_path / "log.csv"
    p.write_text("\ufefft,x,label,\n0,1.5,a,\n0.5,,b,9\n\n", encoding="utf-8")
    data = load_csv(p)
    assert data.dtype.names == ("t", "x", "label", "col3")
    np.testing.assert_array_equal(data["t"], [0.0, 0.5])
    assert np.isnan(data["x"][1])  # empty cells are NaN
    assert list(data["label"]) == ["a", "b"]


def test_csv_edge_cases(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("a,a\n1,2\n")
    assert load_csv(p).dtype.names == ("a", "a_")
    empty = tmp_path / "empty.csv"
    empty.write_text("\n")
    with pytest.raises(ValueError, match="empty"):
        load_csv(empty)


def test_mat_variables_by_name(tmp_path):
    p = tmp_path / "m.mat"
    savemat(p, {"A": np.eye(2), "v": np.arange(3.0)})
    out = load_mat(p)
    assert set(out) == {"A", "v"}
    np.testing.assert_array_equal(out["A"], np.eye(2))


def test_load_data_names_and_rejects(tmp_path):
    p = tmp_path / "2nd run.csv"
    p.write_text("t\n0\n")
    assert list(load_data(p)) == ["_2nd_run"]
    with pytest.raises(ValueError, match="expected"):
        load_data(tmp_path / "x.xlsx")
    assert variable_name("class") == "class_" and variable_name("") == "data"
