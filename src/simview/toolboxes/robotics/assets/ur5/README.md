# UR5 (CB3) robot description

`ur5.urdf` is a plain URDF for the Universal Robots UR5 (CB3), written for SimView by expanding
Universal Robots' `urdf/ur_macro.xacro` with the values in `config/ur5/default_kinematics.yaml`,
`joint_limits.yaml`, `physical_parameters.yaml`, and `visual_parameters.yaml` from
[UniversalRobots/Universal_Robots_ROS2_Description](https://github.com/UniversalRobots/Universal_Robots_ROS2_Description)
at commit `0eb1a861f7772fceb38510d90fa2f98ec668070c`.

- Links, joints, frames (`base_link`, `base`, `flange`, `tool0`), joint limits, masses, centers
  of mass, and inertia tensors match the upstream xacro output for `ur_type:=ur5`.
- `meshes/*.stl` are the upstream collision meshes (`meshes/ur5/collision/`), unmodified. They
  are used for both visual and collision geometry, because MuJoCo can't load the upstream
  COLLADA (`.dae`) visual meshes.
- Not included: `ros2_control` tags, the `ft_frame`, and safety-controller limits.

License: BSD-3-Clause, by the Universal_Robots_ROS2_Description authors (the upstream license
file names no copyright holder). The upstream `LICENSE` is copied unmodified into this folder.
