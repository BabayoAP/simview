"""VW-03: the dataset folder format: PNG I/O, validation, replay, and export."""

import json
import struct
import time
import zlib

import numpy as np
import pytest

from simview.perception import Dataset, DatasetError, Frame, write_dataset
from simview.perception.png import SIGNATURE, _chunk, read_png, write_png


def _encode_filtered(img: np.ndarray, ftype: int) -> bytes:
    """A reference PNG encoder using one filter type for every row (8-bit RGB)."""
    h, w, _ = img.shape
    bpp, stride = 3, w * 3
    rows = img.reshape(h, stride).astype(int)
    out = bytearray()
    prev = [0] * stride
    for y in range(h):
        line = rows[y].tolist()
        out.append(ftype)
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = [0, a, b, (a + b) // 2, 0][ftype]
            if ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            out.append((line[i] - pred) & 0xFF)
        prev = line
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(out)))
        + _chunk(b"IEND", b"")
    )


def test_png_round_trip_rgb_and_16_bit(tmp_path):
    rng = np.random.default_rng(1)
    rgb = rng.integers(0, 256, (7, 9, 3), dtype=np.uint8)
    write_png(tmp_path / "a.png", rgb)
    np.testing.assert_array_equal(read_png(tmp_path / "a.png"), rgb)
    depth = rng.integers(0, 65536, (5, 4), dtype=np.uint16)
    write_png(tmp_path / "d.png", depth)
    back = read_png(tmp_path / "d.png")
    assert back.dtype == np.uint16
    np.testing.assert_array_equal(back, depth)
    with pytest.raises(ValueError):
        write_png(tmp_path / "x.png", np.zeros((2, 2), np.float32))


@pytest.mark.parametrize("ftype", [0, 1, 2, 3, 4])
def test_png_reader_handles_every_filter(tmp_path, ftype):
    rng = np.random.default_rng(ftype)
    img = rng.integers(0, 256, (6, 5, 3), dtype=np.uint8)
    (tmp_path / "f.png").write_bytes(_encode_filtered(img, ftype))
    np.testing.assert_array_equal(read_png(tmp_path / "f.png"), img)


def make_frames(n_cams=2, n=3, depth=True):
    rng = np.random.default_rng(0)
    frames = []
    k = np.array([[50.0, 0, 15.5], [0, 50.0, 11.5], [0, 0, 1]])
    for i in range(n):
        for c in range(n_cams):
            pose = np.eye(4)
            pose[:3, 3] = [i * 0.5, c, 1.0]
            frames.append(
                Frame(
                    t=i * 0.1,
                    seq=i,
                    source=f"ego.cam{c}",
                    K=k,
                    pose=pose,
                    rgb=rng.integers(0, 256, (24, 32, 3), dtype=np.uint8),
                    depth=rng.uniform(0.5, 30, (24, 32)).astype(np.float32) if depth else None,
                    ego=np.eye(4),
                )
            )
    return frames


def test_write_and_read_back_exactly(tmp_path):
    frames = make_frames()
    ds = write_dataset(tmp_path / "ds", frames)
    assert [c.name for c in ds.cameras] == ["ego.cam0", "ego.cam1"]
    assert len(ds) == 6 and ds.duration == pytest.approx(0.2)
    back = list(ds.frames())
    assert [(f.t, f.source) for f in back] == [(f.t, f.source) for f in frames]
    for a, b in zip(frames, back, strict=True):
        assert a.seq == b.seq
        np.testing.assert_array_equal(a.rgb, b.rgb)
        assert a.depth.tobytes() == b.depth.tobytes()  # .npy keeps float32 depth exactly
        assert a.pose.tobytes() == b.pose.tobytes() and a.K.tobytes() == b.K.tobytes()
        np.testing.assert_array_equal(a.ego, b.ego)
    meta = json.loads((tmp_path / "ds" / "cameras.json").read_text())
    assert meta["format"] == "simview-dataset" and meta["version"] == 1


def test_depth_as_16_bit_millimetres(tmp_path):
    frames = make_frames(n_cams=1, n=1)
    frames[0].depth[0, 0] = np.inf
    ds = write_dataset(tmp_path / "ds", frames, depth="png16")
    assert ds.cameras[0].frames[0].depth.endswith(".png")
    back = next(ds.frames())
    assert np.isinf(back.depth[0, 0])
    np.testing.assert_allclose(back.depth[1:], frames[0].depth[1:], atol=0.0005 + 1e-6)


def test_frames_without_depth(tmp_path):
    ds = write_dataset(tmp_path / "ds", make_frames(n_cams=1, n=2, depth=False))
    assert all(f.depth is None for f in ds.frames())


def _broken(tmp_path, edit):
    write_dataset(tmp_path / "ds", make_frames(n_cams=1, n=2))
    p = tmp_path / "ds" / "cameras.json"
    meta = json.loads(p.read_text())
    edit(meta)
    p.write_text(json.dumps(meta))
    return tmp_path / "ds"


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda m: m["cameras"][0].pop("K"), "missing required field 'K'"),
        (lambda m: m["cameras"][0]["frames"][0].pop("pose"), "missing required field 'pose'"),
        (lambda m: m["cameras"][0]["frames"][1].pop("t"), "missing required field 't'"),
        (lambda m: m["cameras"][0].update(K=[[1, 0], [0, 1]]), "3x3"),
        (lambda m: m["cameras"][0]["frames"][0].update(pose=[[1, 0, 0, 0]] * 3), "4x4"),
        (lambda m: m["cameras"][0]["frames"][0]["pose"][0].__setitem__(0, 3.0), "rigid"),
        (lambda m: m["cameras"][0]["frames"][1].update(t=-1.0), "back in time"),
        (lambda m: m["cameras"][0]["frames"][0].update(rgb="nope.png"), "not found"),
        (lambda m: m.update(cameras=[]), "empty"),
        (lambda m: m["cameras"][0].update(width=0), "positive integers"),
    ],
)
def test_validation_errors_are_clear(tmp_path, edit, message):
    with pytest.raises(DatasetError, match=message):
        Dataset(_broken(tmp_path, edit))


def test_missing_folder_and_size_mismatch(tmp_path):
    with pytest.raises(DatasetError, match="cameras.json"):
        Dataset(tmp_path)
    path = _broken(tmp_path, lambda m: m["cameras"][0].update(width=31))
    with pytest.raises(DatasetError, match="32x24"):
        list(Dataset(path).frames())


def test_replay_feeds_streams_at_the_chosen_speed(tmp_path):
    ds = write_dataset(tmp_path / "ds", make_frames(n_cams=2, n=3))  # 0.2 s long
    start = time.perf_counter()
    got = list(ds.replay(speed=None))
    fast = time.perf_counter() - start
    assert len(got) == 6
    assert ds.streams["ego.cam1"].seq == 2 and ds.streams["ego.cam1"].latest().t == 0.2
    start = time.perf_counter()
    list(ds.replay(speed=1.0))
    assert time.perf_counter() - start >= 0.19
    start = time.perf_counter()
    list(ds.replay(speed=4.0))
    assert time.perf_counter() - start >= 0.045
    assert fast < 1.0
    with pytest.raises(ValueError):
        list(ds.replay(speed=0))
