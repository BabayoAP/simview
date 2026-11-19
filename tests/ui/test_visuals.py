"""VP-01 visual meshes (STL, OBJ, GLB) and VP-04 trail settings, without OpenGL."""

import json
import struct

import numpy as np
import pytest

import simview as sv
from simview.ipc.protocol import describe
from simview.ui.viewport import model


def write_glb(path, vertices):
    """A minimal glTF 2.0 binary file with one triangle (no external tools needed)."""
    v = np.asarray(vertices, dtype=np.float32)
    idx = np.array([0, 1, 2], dtype=np.uint16)
    vbytes, ibytes = v.tobytes(), idx.tobytes() + b"\x00\x00"  # pad to 4 bytes
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(vbytes) + len(ibytes)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vbytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vbytes), "byteLength": 6, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": v.min(axis=0).tolist(),
                "max": v.max(axis=0).tolist(),
            },
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    binary = vbytes + ibytes
    chunks = (
        struct.pack("<II", len(js), 0x4E4F534A)
        + js
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks)


def test_glb_visual_loads_z_up(tmp_path):
    glb = tmp_path / "tri.glb"
    write_glb(glb, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])  # in glTF's +Y-up frame
    mesh = model.load_visual(str(glb))
    assert mesh.n_points == 3 and mesh.n_cells == 1
    np.testing.assert_allclose(mesh.bounds[4:], [0, 1], atol=1e-6)  # glTF +Y became +Z
    np.testing.assert_allclose(model.load_visual(str(glb), scale=2.0).bounds[1], 2.0, atol=1e-6)


def test_stl_and_obj_visuals(tmp_path):
    import pyvista as pv

    pv.Cube().save(tmp_path / "cube.stl")
    (tmp_path / "tri.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 0 1\nf 1 2 3\n")
    assert model.load_visual(str(tmp_path / "cube.stl")).n_cells > 0
    assert model.load_visual(str(tmp_path / "tri.obj")).n_cells == 1


def test_scene_visuals_and_trails_reach_the_description(tmp_path):
    glb = tmp_path / "tri.glb"
    write_glb(glb, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    scene = sv.Scene()
    pose = np.eye(4)
    pose[:3, 3] = [1, 2, 3]
    scene.add_visual("sign", glb, pose, scale=0.5, color="accent")
    scene.add_box("box", (0.1, 0.1, 0.1), (0, 0, 1), mass=1.0)
    scene.trail("box", seconds=2.0, color="state.warning")
    desc = describe(scene)
    path, got_pose, scale, color = desc.visuals["sign"]
    assert path == str(glb.resolve()) and scale == 0.5 and color == "accent"
    np.testing.assert_allclose(got_pose, pose)
    assert desc.trails["box"] == (2.0, "state.warning")


def test_visual_and_trail_errors(tmp_path):
    scene = sv.Scene()
    with pytest.raises(FileNotFoundError):
        scene.add_visual("x", tmp_path / "missing.glb")
    (tmp_path / "a.txt").write_text("not a mesh")
    with pytest.raises(ValueError, match="STL, OBJ, GLB"):
        scene.add_visual("x", tmp_path / "a.txt")
    (tmp_path / "ok.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 0 1\nf 1 2 3\n")
    scene.add_visual("x", tmp_path / "ok.obj")
    with pytest.raises(ValueError, match="already exists"):
        scene.add_visual("x", tmp_path / "ok.obj")
    with pytest.raises(ValueError, match=">= 0"):
        scene.trail("x", seconds=-1)
