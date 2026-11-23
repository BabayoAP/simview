"""Minimal PNG reading and writing with NumPy and zlib (no imaging dependency, D-128).

Writes 8-bit RGB and 16-bit grayscale, unfiltered (byte-identical for identical pixels).
Reads non-interlaced grayscale, gray+alpha, RGB and RGBA at 8 or 16 bits, with every filter
type; alpha is dropped.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def write_png(path: str | Path, image: np.ndarray) -> None:
    """Write an (H, W, 3) uint8 RGB image or an (H, W) uint16 grayscale image."""
    a = np.asarray(image)
    if a.ndim == 3 and a.shape[2] == 3 and a.dtype == np.uint8:
        depth, color, raw = 8, 2, a
    elif a.ndim == 2 and a.dtype == np.uint16:
        depth, color, raw = 16, 0, a.astype(">u2")
    else:
        raise ValueError(
            f"write_png takes (H, W, 3) uint8 or (H, W) uint16, got {a.dtype} {a.shape}"
        )
    h, w = a.shape[:2]
    rows = np.ascontiguousarray(raw).reshape(h, -1).view(np.uint8)
    data = np.hstack([np.zeros((h, 1), np.uint8), rows]).tobytes()
    ihdr = struct.pack(">IIBBBBB", w, h, depth, color, 0, 0, 0)
    Path(path).write_bytes(
        SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(data, 6))
        + _chunk(b"IEND", b"")
    )


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(data: bytes, h: int, stride: int, bpp: int) -> np.ndarray:
    buf = np.frombuffer(data, dtype=np.uint8)
    if len(buf) < h * (stride + 1):
        raise ValueError("PNG image data is truncated")
    buf = buf[: h * (stride + 1)].reshape(h, stride + 1)
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    for y in range(h):
        ftype, line = int(buf[y, 0]), buf[y, 1:]
        if ftype == 0:
            cur = line.copy()
        elif ftype == 2:
            cur = line + prev
        elif ftype == 1:
            run = np.cumsum(line.reshape(-1, bpp).astype(np.int64), axis=0)
            cur = (run & 0xFF).astype(np.uint8).reshape(-1)
        elif ftype in (3, 4):
            cur_l = [0] * stride
            ln, pv = line.tolist(), prev.tolist()
            for i in range(stride):
                a = cur_l[i - bpp] if i >= bpp else 0
                b = pv[i]
                if ftype == 3:
                    cur_l[i] = (ln[i] + ((a + b) >> 1)) & 0xFF
                else:
                    c = pv[i - bpp] if i >= bpp else 0
                    cur_l[i] = (ln[i] + _paeth(a, b, c)) & 0xFF
            cur = np.array(cur_l, dtype=np.uint8)
        else:
            raise ValueError(f"PNG has an unknown filter type {ftype}")
        out[y] = cur
        prev = cur
    return out


def read_png(path: str | Path) -> np.ndarray:
    """(H, W, 3) for color images, (H, W) for grayscale; uint8 or uint16 as stored."""
    raw = Path(path).read_bytes()
    if raw[:8] != SIGNATURE:
        raise ValueError(f"{path}: not a PNG file")
    pos, idat, header = 8, [], None
    while pos + 8 <= len(raw):
        (n,) = struct.unpack(">I", raw[pos : pos + 4])
        kind = raw[pos + 4 : pos + 8]
        body = raw[pos + 8 : pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError(f"{path}: PNG has no header")
    w, h, depth, color, _, _, interlace = header
    if color not in _CHANNELS or depth not in (8, 16) or interlace:
        raise ValueError(
            f"{path}: unsupported PNG (color type {color}, {depth}-bit, interlace {interlace}); "
            "use 8/16-bit gray, RGB or RGBA without interlacing"
        )
    ch = _CHANNELS[color]
    bpp = ch * depth // 8
    rows = _unfilter(zlib.decompress(b"".join(idat)), h, w * bpp, bpp)
    if depth == 16:
        px = rows.view(">u2").astype(np.uint16).reshape(h, w, ch)
    else:
        px = rows.reshape(h, w, ch)
    if ch in (1, 2):
        return np.ascontiguousarray(px[:, :, 0])
    return np.ascontiguousarray(px[:, :, :3])
