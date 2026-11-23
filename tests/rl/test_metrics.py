"""ML-03: training metrics from SimView's own log and from TensorBoard event files."""

import struct

import pytest

from simview.rl.metrics import (
    TRAINING_ENV,
    TailReader,
    TrainingRun,
    latest_training_dir,
    log_metric,
    read_tfevents,
    training_dir,
)


def _varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _field(num, wire, payload):
    key = _varint(num << 3 | wire)
    if wire == 2:
        return key + _varint(len(payload)) + payload
    return key + payload


def _event(step, tag, value, tensor=False):
    if tensor:  # TF2 style: a TensorProto with dtype float and float_val
        proto = _field(1, 0, _varint(1)) + _field(5, 5, struct.pack("<f", value))
        val = _field(1, 2, tag.encode()) + _field(8, 2, proto)
    else:  # simple_value
        val = _field(1, 2, tag.encode()) + _field(2, 5, struct.pack("<f", value))
    ev = _field(1, 1, struct.pack("<d", 1.0)) + _field(2, 0, _varint(step))
    ev += _field(5, 2, _field(1, 2, val))
    return struct.pack("<Q", len(ev)) + b"\0" * 4 + ev + b"\0" * 4  # CRCs aren't checked


def test_reads_tensorboard_scalars_including_a_partial_record(tmp_path):
    f = tmp_path / "events.out.tfevents.1.host"
    head = _field(1, 1, struct.pack("<d", 1.0)) + _field(3, 2, b"brain.Event:2")
    data = struct.pack("<Q", len(head)) + b"\0" * 4 + head + b"\0" * 4
    data += _event(10, "rollout/ep_rew_mean", 1.5) + _event(300, "train/loss", 0.25, tensor=True)
    partial = _event(400, "train/loss", 0.5)
    f.write_bytes(data + partial[:9])
    scalars, used = read_tfevents(f)
    assert scalars == [("rollout/ep_rew_mean", 10, 1.5), ("train/loss", 300, 0.25)]
    assert used == len(data)
    f.write_bytes(data + partial)  # the writer finishes the record
    tr = TrainingRun(tmp_path)
    assert tr.refresh() and tr.series["train/loss"].values == [0.25, 0.5]


def test_log_metric_and_tail_reading(tmp_path, monkeypatch):
    monkeypatch.delenv(TRAINING_ENV, raising=False)
    monkeypatch.setenv("SIMVIEW_RUNS", str(tmp_path))
    folder = training_dir()
    assert folder.parent == tmp_path.resolve() and folder.name.startswith("train-")
    assert latest_training_dir(tmp_path) == folder
    log_metric("a", 2, 1.0)
    log_metric("a", 1, 3.0)
    tr = TrainingRun(folder)
    assert tr.refresh()
    steps, values = tr.series["a"].arrays()
    assert list(steps) == [1, 2] and list(values) == [3.0, 1.0]  # sorted by step
    with open(folder / "metrics.jsonl", "a") as f:
        f.write('{"name": "a", "step": 3, "va')  # half-written line: left for next time
    assert not tr.refresh()
    with open(folder / "metrics.jsonl", "a") as f:
        f.write('lue": 2.0}\n')
    assert tr.refresh() and tr.names() == ["a"] and len(tr.series["a"].values) == 3
    assert TailReader(tmp_path / "missing.jsonl").new_lines() == []


def test_sb3_logger_writes_scalars(tmp_path, monkeypatch):
    pytest.importorskip("stable_baselines3")
    from simview.rl.metrics import sb3_logger

    monkeypatch.delenv(TRAINING_ENV, raising=False)
    logger = sb3_logger(tmp_path / "t", stdout=False)
    logger.record("train/loss", 0.5)
    logger.record("rollout/name", "text")  # non-numbers are skipped
    logger.dump(step=64)
    tr = TrainingRun(tmp_path / "t")
    tr.refresh()
    assert tr.names() == ["train/loss"] and tr.series["train/loss"].steps == [64]
