"""Sensors (SN-01..SN-03): mount one with `entity.attach(...)`, read it as
`entity.sensors.<name>`. Scalar readings are logged as `<entity>.<sensor>.<field>`."""

from simview.sensors.base import Sensor
from simview.sensors.camera import Camera
from simview.sensors.gps import GPS
from simview.sensors.imu import IMU
from simview.sensors.lidar import Lidar
from simview.sensors.seeker import Seeker, rbe, rbe_to_position

__all__ = ["GPS", "IMU", "Camera", "Lidar", "Seeker", "Sensor", "rbe", "rbe_to_position"]


def __getattr__(name: str) -> type:
    """Sensors added by toolboxes (TB-02) read as `simview.sensors.<Name>`."""
    if not name.startswith("_"):
        from simview.toolboxes import registry

        try:
            return registry.sensor_type(name)
        except KeyError:
            pass
    raise AttributeError(f"module 'simview.sensors' has no attribute {name!r}")
