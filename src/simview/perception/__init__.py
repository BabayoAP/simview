"""Vision world model (PRD §5.12, VW-01..VW-07, VW-10): camera rigs, frame streams, recorded
datasets, and a perception pipeline that fuses depth into a 3D occupancy grid and a BEV map.

    rig = ego.attach(sv.perception.CameraRig.surround(n=8, width=160, height=120, rate=10))
    perceive = scene.add_pipeline(sv.perception.Pipeline(
        [sv.perception.BackProject(max_range=40), sv.perception.OccupancyGrid(res=0.2, extent=60),
         sv.perception.BevMap(z_band=(0.2, 2.5))], inputs=rig, name="ego"))

    @scene.controller(rate=20)
    def drive(t, state, ctx):
        grid = ctx.streams["ego.occupancy"].latest()

Runs log the perceived world beside the Parquet log (VW-09): `load_snapshots(run).at(t)`.

Frames: metres, world frame, Z up; camera poses are world-from-camera of the OpenCV optical
frame (x right, y down, z forward); depth is float32 z-depth (D-122..D-129).
"""

from simview.perception.backproject import BackProject, PointCloud
from simview.perception.bev import Bev, BevMap
from simview.perception.dataset import (
    CameraInfo,
    Dataset,
    DatasetError,
    DatasetWriter,
    FrameInfo,
    Record,
    write_dataset,
)
from simview.perception.evaluate import Accuracy, evaluate, truth_grid
from simview.perception.occupancy import OccupancyGrid
from simview.perception.pipeline import Pipeline
from simview.perception.rig import CameraRig, camera_K
from simview.perception.runlog import (
    CameraFrame,
    Snapshot,
    Snapshots,
    load_snapshots,
    perception_dir,
    snapshot_pipelines,
)
from simview.perception.stream import SENSOR_FROM_OPTICAL, Frame, Reader, Stream

__all__ = [
    "SENSOR_FROM_OPTICAL",
    "Accuracy",
    "BackProject",
    "Bev",
    "BevMap",
    "CameraFrame",
    "CameraInfo",
    "CameraRig",
    "Dataset",
    "DatasetError",
    "DatasetWriter",
    "Frame",
    "FrameInfo",
    "OccupancyGrid",
    "Pipeline",
    "PointCloud",
    "Reader",
    "Record",
    "Snapshot",
    "Snapshots",
    "Stream",
    "camera_K",
    "evaluate",
    "load_snapshots",
    "perception_dir",
    "snapshot_pipelines",
    "truth_grid",
    "write_dataset",
]
