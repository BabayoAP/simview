# Decisions

Ambiguities resolved with the simplest reading (PRD §0 rule 6). Newest last.

## M1

**D-001 — Layout persistence before projects exist.** DS-03 asks for the layout to persist
per project, but projects (`.svproj`, IO-04) arrive in M6. The main window saves its dock state
to `QSettings` under `layout/<project key>`. The key is `untitled`, `template/<id>`, or the
project folder path. M6 can move this into the `.svproj` folder without changing the window API.

**D-002 — Template cards before templates exist.** DS-08 needs the 4 template cards, but the
templates are built in M8. Clicking a card opens the main window titled with the template
name and an empty scene. The card thumbnail is a Lucide glyph until real renders exist (M10).

**D-003 — Only part of the Lucide set is used, but all of it is bundled.** All 1,540 SVGs
from `lucide-static@0.460.0` are bundled (about 1.5 MB) so later milestones don't need a
re-fetch. Icons are tinted at load time by swapping `currentColor` for a token color and
`stroke-width="2"` for the §7.3 value of 1.5.

**D-004 — Layout sizes are tokens.** §7.3 bans hard-coded sizes outside the theme, so the
default window, side-panel, timeline, bottom-row, palette, and card sizes live in `tokens.py`.

**D-005 — Text on accent and light `state.success` contrast.** White on the dark `accent`
`#0A84FF` measures 3.35:1, below AA. Resolved (approved 2026-11-18): a new `accent.fill` token
is used only for filled controls (primary buttons, selected list rows, selected menu items,
text selection), with `text.on_accent` (white) on top. Dark `accent.fill` is `#0A6FEE`: 4.64:1
for white text, and at least 3.0:1 against every dark surface, so the control edge still
reads. Light `accent.fill` equals the light `accent` (`#0071E3`, 4.70:1 with white).
`accent` itself is unchanged for focus rings, selection outlines, and the time cursor.
Separately, light `state.success` is darkened from the PRD's `#248A3D` (4.40:1 on white) to
`#1F7A35` (5.39:1 on white, 4.95:1 on `bg.app`), so it is safe as text too.

**D-006 — The content-area target in §7.2.1.** With the original §7.4 panel sizes at 1440×900,
the viewport plus plots took 55.7% of the window. Fixed chrome (menu, toolbar, status bar,
timeline) is about 18% of the window by itself, so 70% of the whole window would need side
panels near 100 px. Resolved (approved 2026-11-18): side panels default to 180/200 px, plots
take 75% of the bottom row, and the timeline dock has no title bar (it is a thin strip). The
70% target is measured against the work area between the toolbar and the status bar. That
measures 68.6% offscreen (61.7% of the full window). Getting to a strict 70% of the work area
would also need plots at 80% of the bottom row (console about 287 px wide). The timeline can't
be dragged by a title bar; it returns to place with Reset Layout.

**D-007 — Icons don't re-tint on a live theme switch.** Toggling the theme re-applies the QSS,
but existing icons keep the old theme's tint until the window is reopened. Both themes'
`text.secondary` and `accent` stay legible on either background, so this is cosmetic. It will be
fixed when the panels gain real content.

**D-008 — R5 verified.** qtconsole's `RichJupyterWidget` with an in-process kernel ran under
PySide6 via qtpy (tested in a throwaway venv on macOS, Python 3.12, PySide6 6.12). It is not a
project dependency until M6.

**D-009 — License.** MIT, the PRD Q3 default, confirmed 2026-11-18.

**D-010 — pytest-cov.** Added as a dev dependency (approved 2026-11-18) for NF-09
(≥80% line coverage of `simview/core`). CI reports coverage now; the 80% gate will be enforced
on `simview/core` once M2 creates it.

## M2

**D-011 — One `simview` command.** SE-05 asks for `simview run scene.py --headless`, so the
console script now points at `simview.cli:main`. It sends `run ...` to the headless runner and
everything else to `simview.ui.app.main` unchanged, so `simview [--theme light]` behaves as in M1.
The headless path never imports Qt.

**D-012 — Ground contact without events.** Events (`on_collision`, SE-11) are v1, so the
bouncing ball's ground is a stiff spring-damper (k = 1e4 N/m, c = 20 N·s/m) inside its
`derivative`. That gives a restitution of about 0.73 and under 4 cm of penetration at dt = 1 ms.

**D-013 — RK45 is adaptive inside each tick.** SE-01 fixes the tick, so `rk45` runs SciPy's
`solve_ivp(method="RK45")` across each `dt` with `rtol=1e-8`, `atol=1e-10`, and the input `u`
held constant over the tick. Euler and RK4 take one step per tick.

**D-014 — Scene files.** A `scene.py` defines a module-level `scene = simview.Scene(...)`;
`load_scene` runs it with `runpy`. The CLI's `--duration` defaults to 10 s, `--seed` overrides
the scene's seed, and the default log path is `runs/<YYYYmmdd-HHMMSS>-seed<seed>.parquet` in the
working directory (with a numeric suffix if taken). The GUI will build the same `Scene` object.

**D-015 — Log layout.** One row per tick, including tick 0: `t`, `tick`, then
`<entity>.<state>` for every entity state, then tagged channels from `scene.log(name, fn)`,
where `fn(sim)` returns a float. `t` is `tick * dt` (no summed drift). Run settings go in the
Parquet schema metadata under `simview` as sorted-key JSON, with no timestamps, so
same seed + same scene gives byte-identical files. Block signals join the log in M5.

**D-016 — Left for later milestones.** `scene.controller(rate=...)` and `ctx.draw` from the
§8.3 sketch, live (non-headless) runs, and the 60 Hz render clock in SE-01 need the viewport
or blocks, so they arrive in M4/M5. `run(..., headless=False)` raises `NotImplementedError` until
then. `Run.to_pandas()` works if pandas is installed; pandas is not a dependency (not in §8),
and `run["column"]` returns a NumPy array.

## M3

**D-017 — The bundled UR5.** There is no license-clean plain UR5 URDF to copy: MuJoCo Menagerie
only has the UR5e (a different robot), and Universal Robots ships xacro. `toolboxes/robotics/
assets/ur5/ur5.urdf` is Universal Robots' `ur_macro.xacro` expanded by hand with the UR5 values
from `Universal_Robots_ROS2_Description` @ `0eb1a861` (BSD-3-Clause, `LICENSE` copied alongside,
provenance in that folder's `README.md`). The 7 upstream collision STLs (about 250 KB) are
bundled unmodified and used for visuals too, because MuJoCo can't load the upstream `.dae`
visual meshes. Left out: `ros2_control` tags, `ft_frame`, safety-controller limits.

**D-018 — How MuJoCo entities fit the M2 API.** `Entity` gains two methods, `validate()` (the
shape check `Sim` used to do inline) and `advance(t, dt)` (integrate `derivative`, as before).
`Sim` now calls these. MuJoCo robots override both; custom models behave exactly as in M2. No
existing signature changed; this is additive, so it was not treated as a public-API change.

**D-019 — Robot state and input.** A `Robot` is one entity whose `x` is `[qpos, qvel]`, logged as
`<robot>.<joint>.q` / `.v` (multi-DOF joints: `.q0..`, `.v0..`). `x` is the source of truth: each
tick it is copied into `MjData`, MuJoCo takes one `mj_step` with the scene's `dt`, and the result
is copied back, so code that edits `x` (IK, a slider) takes effect on the next tick. `u` drives
the actuators (`ctrl`) if the model has any, otherwise it is applied as joint forces
(`qfrc_applied`): a URDF has no actuators, so `u` is joint torques. `integrator` doesn't apply.

**D-020 — URDF import details.** Static links (`tool0`, `flange`, `base`) are kept as bodies
(`fusestatic="false"`) so they work as kinematic frames. `<visual>` elements are dropped; MuJoCo
simulates the collision geoms and the viewport (M4) will draw them. Mesh paths resolve relative to
the URDF, and `package://<pkg>/<rel>` resolves to `<rel>` relative to the URDF (no ROS package
lookup). Mesh formats MuJoCo can't read (anything but STL/OBJ/MSH) fail with a clear error instead
of being converted. MJCF files load unchanged, so MuJoCo's rules apply, including angles in
degrees unless the file sets `<compiler angle="radian"/>`. Bundled robots resolve by bare name:
`scene.add_robot("ur5.urdf")` or `"ur5"` (an existing file path wins).

**D-021 — The FK reference.** "FK matches a reference within 1e-6" uses Universal Robots'
published UR5 DH parameters, which share nothing with the URDF or MuJoCo code path. The DH chain
gives `base`→`tool0`; `base` is `base_link` rotated π about z. Measured worst error over 1,000
random configurations: 6e-10. The Jacobian is MuJoCo's geometric Jacobian of the frame origin,
rows `[linear; angular]` in the world frame, checked against finite differences.

**D-022 — What the IK target means, and how IK meets it.** "Random reachable poses" are the FK of
joint vectors drawn uniformly from [-π, π]^6, solved from one fixed seed configuration, with
tolerances of 1e-6 m and 1e-6 rad. Plain damped least squares reached only about 80%: most
failures were local minima, some were joints stopped at a limit, and the rest were targets near
singularities. The solver therefore (a) scales damping with the error, (b) wraps joints whose
range covers [-π, π] instead of clipping them, and (c) restarts from a seeded random configuration
when 3 updates fail to cut the error by 20%. Every update and every restart counts toward the 50.
Measured: 98.3–99.0% on three fresh sets of 1,000 targets, median 9 iterations, about 4 ms per
solve. The test uses 300 targets and requires ≥95%. Results are deterministic (`seed=0` default).

**D-023 — TB-ROBOT is partly built in M3.** The §10 deliverable for M3 is "FK/Jacobian/IK in the
Robotics toolbox", so M3 builds FK, the Jacobian, DLS IK, and the SE(3) basics they need
(`make`, `inv`, `rot_log`, `error`). The rest of the §9 Robotics row (trajectory generation,
inverse dynamics, transform-tree utilities) is not built yet; see the M3 gate question in
PROGRESS.md. `robot.fk(q)`, `robot.jacobian(q)`, and `robot.ik(T)` exist as methods for UC-3.

**D-024 — Math names in lint.** Robotics code uses `T`, `R`, `J` for transforms, rotations, and
Jacobians. `pyproject.toml` turns off ruff's N803/N806 naming rules for
`src/simview/toolboxes/robotics/` and for tests, instead of scattering `noqa` comments.

## M3b

**D-025 — Alloy's robotics, rebuilt natively.** *Superseded by D-037: this decision identified the
wrong Alloy. The text below is kept as the record of what was decided at the time.* The owner asked (2026-11-18) for "all the
necessary functionality of Alloy robotics", the Alloy physics engine from Argon Robotics
(`github.com/argonrobotics-ai/alloy`, Apache-2.0). Alloy runs only on Linux and Apple-silicon
macOS and pins `mujoco==3.17.0`, so it is not a dependency. Its rigid-body robotics is rebuilt on
SimView's own MuJoCo backend instead, and works on all three OSes. The owner chose the "necessary"
set: shared world and objects, joint driving, controllers, grippers and a robot library. Everything
else is listed as `[Future]` in PRD §5.10 (RB-20..RB-28). No Alloy code was copied; its API names
and units were followed where they fit (full sizes in metres, `set_targets`, ramps). PRD → 1.1,
new milestone M3b, which also finishes TB-ROBOT (trajectories, inverse dynamics, transform tree).

**D-026 — One world per scene, and what changed for M3's `Robot`.** A scene has one `World`
(`physics/world.py`), made on first use, that compiles every robot and object into one MuJoCo
model with `MjSpec.attach` (robot names prefixed `<robot>/`). It recompiles whenever an item is
added; scenes are small. Each member entity owns a slice of the state through index arrays
(`qidx`, `vidx`, `act_ids`), and the scheduler steps the world once per tick after controllers
and ODE entities. M3's public `Robot` API is kept: the same constructor argument, state names,
`q`, `qd`, `set_q`, `u`, `fk`/`jacobian`/`ik`, and `robot.model` (now the world's model). A robot
made on its own gets a private world and moves into the scene's world when added. Frame names that
contain `/` are full world names, so an arm's kinematics can use a mounted tool's frame
(`"grip/pinch"`).

**D-027 — World options belong to the world.** Once attached, a robot file's own `<option>` no
longer applies (MuJoCo warns: "keeping parent value"). The world's integrator defaults to
`implicitfast`, MuJoCo's recommendation for servo-driven robots; M3 robots used their file's
option (Euler for the UR5). `scene.physics().integrator` / `.gravity` change it; the MJCF-vs-ODE
pendulum test now selects RK4 explicitly.

**D-028 — Friction cone for grasping.** `World.cone` / `.impratio` are exposed, with MuJoCo's
defaults (pyramidal, 1). Grasping scenes set `"elliptic"` and `10`, as Menagerie grippers ask for
and MuJoCo recommends, so a squeezed object doesn't creep out of the fingers.

**D-029 — Adjacent links never collide.** Building M3b's controllers found the UR5's shoulder in
permanent contact with its base, a bug present since M3. MuJoCo skips parent-child contacts except
when the parent is welded to the world, and URDF's `base_link_inertia` is. Every robot now
excludes contacts between each body and its parent (the URDF/ROS convention). Non-adjacent
self-contacts (a folded arm) are physical and stay.

**D-030 — Differential IK integrates from its last command.** Stepping from the measured joints
made a servo-driven arm creep: a servo always lags its target, so each new target was only a small
step ahead. `DifferentialIK` keeps `q_cmd`, starts from the measured q on its first call or after
`reset()`, and takes each step from the previous command, as position-controlled arms do.

**D-031 — Objects.** Sizes are full lengths in metres (easier to read than MuJoCo's half sizes,
which are derived): box (x, y, z), sphere (diameter), cylinder and capsule (diameter, length). A free
object needs `mass=` and is an entity with 13 logged states (`x y z qw qx qy qz vx vy vz wx wy
wz`). `static=True` makes fixed geometry that is not an entity. One ground plane per scene.

**D-032 — Servos and targets.** `servos="position"` / `"velocity"` adds a servo to each hinge or
slide joint that has no actuator (defaults kp = 1000, kv = 100; one value or a dict by joint), with
`ctrlrange` set to the joint range. MJCF actuators are used as they are. `set_targets` checks the
servo kind, clamps position targets to the joint range with a warning, and with `ramp=` moves the
target linearly from its current value. `set_controls` is raw (no clamp, no warning). Unnamed
joints and actuators are named `joint<k>` / `actuator<k>`. `gravity_compensation=True` uses
MuJoCo's body `gravcomp`, an ideal stand-in for an arm's own gravity compensation.

**D-033 — `scene.controller` arrives in M3b, without `ctx.draw`.** RB-07 needs per-tick control,
so the §8.3 controller API moves forward from M4/M5 (D-016). `fn(t, state, ctx)`: `state` is the
scene (entities by name), `ctx` has `dt` (the controller's period), `tick`, and `rng`. Due
controllers run at the start of a tick, before ODE entities and the world step. A returned dict
`{entity: u}` sets inputs; returning None is fine. The rate must divide 1/dt. `ctx.draw` comes with
the viewport in M4.

**D-034 — The robot library downloads on first use.** Menagerie robots are tens of MB each (Panda
34 MB, UR10e 33 MB), too big to bundle. `library.fetch` downloads only the files a robot's MJCF
references, plus its LICENSE and README, from `raw.githubusercontent.com` at commit `370c4396`,
with the standard library's `urllib` (no new dependency), into `$SIMVIEW_CACHE` (default
`~/.cache/simview`). An offline first use raises `FetchError` saying how to fix it. Licenses:
Panda Apache-2.0, UR10e BSD-3-Clause, Robotiq 2F-85 BSD-2-Clause. Tests that download are marked
`network` (skipped with `SIMVIEW_OFFLINE=1`); CI caches the folder.

**D-035 — The pick done-when uses the UR5 and a scripted gripper.** PRD §10 allows "a Panda (or a
scripted gripper)". The test and `examples/ur5_pick.py` use the bundled UR5 with a two-finger MJCF
gripper mounted on `tool0`, so they run offline: the cube lifts 9.9 cm (10 cm commanded; about
2 mm slip in the grip), with a quintic lift because a step target jerks the cube out. The Panda is
covered by network tests (loads, 8 actuators, reaches a pose within 5 mm under differential IK);
a Panda pick is not tested yet.

**D-036 — Controller gains and MuJoCo versions.** Fixed joint gains high enough for the UR5's
shoulder make its light wrist (about 1e-4 kg·m²) unstable under 1 ms torque control. The joint
controller tests scale gains by inertia (kp = ω²·M_ii, kd = 2ω·M_ii); `OperationalSpace` scales
by the mass matrix itself. `mujoco>=3.3` (for `MjSpec.attach`); `mj_fullM` changed signature in
MuJoCo 4 and both forms are handled. Development used MuJoCo 4.0.1; CI installs the latest release.

## PRD 1.2

**D-037 — "Alloy robotics" is Alloy Robotics (usealloy.ai), not Argon's Alloy engine.** D-025 took
"all the necessary functionality of Alloy robotics" to mean the Alloy physics engine from Argon
Robotics, the first match a web search returned, and PRD 1.1 framed §5.10 and M3b around it. The
owner meant Alloy Robotics (usealloy.ai), an AI platform for investigating robot data: it ingests
logs (MCAP, ROS, Parquet, CSV, ArduPilot), answers questions about missions, scans every run for
a pattern defined once ("Scenarios"), writes mission reports with plots, links each finding to its
signals and time window, and offers an MCP server. It has no simulation. The owner's decisions
(2026-11-18):
- M3b stays, as plain "Robotics depth". Its code and requirements (RB-01..RB-12) are sound and
  unchanged; only the Alloy framing is removed from the PRD and PROGRESS. 1.1's physics-engine
  `[Future]` list (RB-20..RB-28) is removed.
- usealloy.ai's functionality becomes PRD §5.11 Run investigation (RI-01..RI-06 MVP, RI-20..RI-24
  later), applied to SimView's own runs and to imported robot logs, as milestone M5b after M5 (it
  needs the timeline and plots). Natural-language Q&A and an MCP server are `[Future]` for now.
- Lesson recorded: confirm a product's identity from its own site before building on it.

## M4

**D-038 — The sim process.** `ipc/client.py` starts the sim in a `spawn`ed process (the same on
every OS, and no forked Qt state). State goes through one shared-memory float64 buffer guarded by a
sequence counter (a seqlock: the reader retries instead of seeing a half-written frame). Commands,
events, debug draws, and tracebacks go through a ZeroMQ `PAIR` socket on 127.0.0.1 as pickled
dicts (both ends are SimView on one machine). The sim publishes state at most every 1/120 s.
Stop resets by loading the scene file again. A user-code exception (scene file or controller)
arrives as a traceback in the console and pauses the run, with the process still up; `print`
output is forwarded line by line. A killed or crashed sim is reported once with its exit code, and
Run starts a new one (NF-10).

**D-039 — Pacing and its numbers (SE-10, NF-04).** Speeds 0.1×, 0.25×, 0.5×, 1×, 2×, 5×, 10×, and
Max (no pacing). The reported RTF averages over 0.5 s of wall time. Measured on the development
machine: 2.000 s of sim time per 2.001 s of wall time at 1×; about 10× at Max for the UR5 pick
scene; state latency median 4.8 ms, p99 about 10 ms (NF-04: 20 ms). The test checks the median.

**D-040 — VP-05 is split between M4 and M5.** VP-05 is in both milestones' lists. M4 builds play,
pause, step forward, and the speeds; step back and the scrub slider need recorded history, which
is M5's timeline. Step back (`,`) is not bound yet.

**D-041 — The HUD and heads-up toolbar are drawn inside VTK.** Qt widgets laid over the native
OpenGL surface don't composite reliably across platforms, so the toolbar is VTK textured buttons
(Lucide icons rendered by Qt) on a translucent `bg.elevated` backdrop, and the HUD is a VTK text
actor in JetBrains Mono. This keeps §7.5's look. VTK buttons have no tooltips. The "view presets"
button cycles iso, front, right, top (the ViewCube and keys 1/3/7/0 pick one directly). The
"sensor visuals" toggle waits for sensors (M8). The HUD text refreshes at 10 Hz: VTK's corner
annotation re-fitted its font on every change and cost about 25 ms a frame.

**D-042 — Navigation.** SimView's style (§7.5) is the only preset for now: right- or middle-drag
orbits around the point under the cursor, Ctrl+right or Shift+middle pans, the wheel zooms toward
the cursor (keeping that point under it, in perspective and orthographic), left-click selects.
The other presets (SolidWorks, Onshape, Blender, MATLAB) need the Settings dialog and come with it.
Fly mode is a toolbar toggle: W/S, A/D, Q/E move the camera; in fly mode A strafes instead of
framing all. 2D mode (Tab) is top-down orthographic; right-drag pans there and the ViewCube is off.
The world coordinates under the cursor show as a HUD line rather than a tooltip. VTK's own key
handling never sees keys (its defaults close the window on q/e).

**D-043 — Selection and gizmos (VP-06, VP-10, DS-06).** Clicking a robot's link selects the robot.
Selection and hover are one state shared by the viewport, scene tree, and inspector; plots join in
M5. Outlines are silhouettes in a second renderer layer, so they show through other geometry. Drag
targets (`scene.add_target`) always show the translate/rotate gizmo; a selected free body gets one
too, and is placed (at rest) where it is released. Robots get no gizmo: their bases are fixed and
their joints follow IK targets. PyVista's gizmo switches the interactor to its trackball style on
release; SimView puts its own style back.

**D-044 — Testing the OpenGL viewport.** Tests that need a GL context are marked `gl` and run only
with `SIMVIEW_GL=1`. CI runs them on Linux (Mesa under `xvfb`) and macOS. GitHub's Windows runners
only offer OpenGL 1.1, below VTK's 3.2, so Windows GL runs on the development machine (GTX 1050 Ti,
all `gl` tests pass). Without GL (headless runs, broken drivers) the main window uses a stand-in
view: the sim, panels, and console still work and nothing crashes. Everything else in the viewport
(geometry, matrices, trails, draws, grid, navigation math) is OpenGL-free and tested everywhere.

**D-045 — Scene API added for the viewport.** `ctx.draw.line/arrow/point/text/frame` with
`persist=` (VP-07; recorded headless too). `scene.add_target(name, pose)` (VP-10). `Entity.position()`
places markers and trails (VP-04): states named x/y/z by default, a free body's position, a robot's
default frame. `scene.trail(entity, seconds, color)` (VP-04). `scene.add_visual(name, path, pose)`
shows an STL, OBJ, PLY, or GLB/glTF mesh without physics (VP-01; MuJoCo can't load GLB); glTF is
+Y-up, so it is turned +90° about x. World axes sit at the origin and toggle with the grid. Mesh
geoms render with subtle feature edges (shaded+edges, §7.5).

**D-046 — Frame rate.** Measured on the development machine at 1000×700 with 4× MSAA: 62 fps for
both the pick scene and the IK-drag scene (whose debug draws change every tick). Debug draws are
coalesced to the newest set per UI frame and batched into a few actors. NF-01's target scene
(20 entities and a 50k-point cloud) is checked in M10.

**D-047 — Panels and launch.** The Console tab now shows sim output and tracebacks; the IPython
console replaces it in M6. The Inspector lists every state live, and a robot's joints as sliders
that follow the simulation (UC-3). `simview scene.py` opens a scene directly. New dependencies:
`pyvista`, `pyvistaqt`, `pyzmq` (all in PRD §8.1).

## M5

**D-048 — The timeline replays a recording; it doesn't rewind the sim (VP-05).** A run can't be
restarted from a past tick: its state includes MuJoCo's warm starts and whatever controllers keep
in closures (`DifferentialIK.q_cmd`). So the UI keeps a recording of every tick (D-049), and the
timeline shows either the live sim or a recorded row. Scrubbing or stepping back (`,`) pauses the
sim and parks on a row. Play from a parked row replays the recording at the playback speed (Max
replays at 10×) and, when it runs out, the live sim carries on from where it stopped. Step forward
(`.`) moves through the recording, and at its end steps the sim one tick. Hovering a time plot
previews that moment in the viewport without moving the cursor (DA-02); clicking one seeks. Start
and live-end buttons sit beside the transport (palette: "Go to Start / Live"). The speed menu
stays in the toolbar; the timeline shows `live` or `replay` beside the time.

**D-049 — Recording.** After every tick the sim process records one float64 row: the tick, every
logged signal (the Parquet log's columns, SE-06), each entity's marker position, and every MuJoCo
body pose (`ipc/record.py`). Rows go to the UI with each state publish (at most 120 Hz) as one
array. A re-recorded tick (a body dropped by the gizmo while paused) or a reset replaces the rows
from that tick on. The UI's `History` keeps them in one growable array; past 512 MB it drops its
oldest quarter. Debug draws are recorded as the sim sends them (when they change, at most once per
publish), so a scrubbed frame shows the newest draw set sent at or before it; per-tick draws
would cost too much for controllers that draw every tick. Recording costs the UR5 drag scene a
`mj_kinematics` per tick (a few µs).

**D-050 — Plot speed (DA-01).** pyqtgraph's own downsampling still drew 10 × 9k-point antialiased
paths (about 500 ms a frame), and 1.5 px antialiased polylines are slow in Qt's raster engine.
Time plots now thin every trace to a min and a max per bin before drawing (`ui/plots/decimate.py`;
spikes survive), at most 0.75 bins per pixel, and draw segmented lines. While rows stream in, the
bins are a power of two of samples and are cached, so a redraw only reduces new rows. Zooming
or panning by hand re-thins just the visible span. Measured on the development machine for 10
signals × 100k samples at 1000×300: median 25 ms per update (about 40 FPS). The test asserts
33 ms locally; CI runners render in software and only get a regression bound (150 ms).

**D-051 — Plot kinds and behavior (DA-02..DA-04, DS-06).** Kinds: time, XY (the first signal
dropped is X; each later one is a Y series against it; same units lock the aspect ratio, so a
top view isn't skewed), scatter (XY with points), and histogram (all recorded samples; the cursor
marks the current value). Drop signals from the tree onto a plot, onto the empty panel (makes a
time plot), or double-click them. Clicking a trace selects its entity, and the selected entity's
traces are drawn bold; plots don't report hover (pyqtgraph curves have no hover signal), but the
signal tree does. A one-trace plot has no legend (its axis label names it); more get a legend in
the top right, hidden while the hover readout shows. Vector components (x/y/z, vx…, wx…) use the
X/Y/Z axis colors, others Okabe–Ito in order. Plots scroll in their panel instead of growing the
dock. Axis values are shown as logged (no SI rescaling).

**D-052 — Units for plot labels (DS-09).** `Entity.state_units` (optional class attribute, e.g.
`{"h": "m"}`) and `scene.log(name, fn, unit="")` are new optional arguments; nothing existing
changes. Free bodies and robots fill them in (m, m/s, rad, rad/s; quaternions unitless).

**D-053 — Exports (DA-07, DS-09).** Export Data writes the whole recording (every signal, `t`,
`tick`) to CSV, Parquet, or `.mat` by extension. In `.mat`, names become valid MATLAB variables
(`ur5.shoulder.q` → `ur5_shoulder_q`) and `signal_names` lists the originals. Each plot exports
itself to PNG (2× its size) or SVG, in the light theme. pyqtgraph's SVG exporter fails on Qt 6
paths, so SVG uses Qt's `QSvgGenerator`. New dependency: `pyqtgraph` (PRD §8.1).

**D-054 — Fixes to M4 found while checking M5 on screen.** (1) Opening a scene replaced the main
window's central widget, which left it zero-wide: the 3D view vanished and the side docks took
the width. The central widget is now one `QStackedWidget` (empty state, then the view), and the
layout version is bumped so layouts saved with the bug are dropped. (2) The light theme showed
black panels (Inspector, Console) when Windows is in dark mode: the Qt palette now comes from the
tokens too, and Qt no longer makes the docks native windows next to VTK's. (3) Sliders and tree
selection used the OS accent color: both are styled from the tokens now. (4) pyqtgraph creates
parentless menus per plot; plots adopt them so they are deleted with the plot (no leak), and the
test teardown deletes plain stray widgets last. (5) The shared-memory reader gave up after 100
quick retries, so a writer descheduled mid-frame (a busy 2-core CI machine) made `frame()` return
None; it now yields and waits out a write for up to 20 ms. The GL scrub test checks timing only
off CI: CI renders OpenGL in software (0.3–1.3 s a frame).

## M5b

**D-055 — Scenario expressions (RI-02).** A scenario is `condition for <n> s|ms` (no `for`: any
single sample). The condition is parsed with Python's `ast` and only a whitelist is evaluated:
numbers, signal names (`entity.state` or a channel; backticks quote any other name; `t` is
time), comparisons (chains too), arithmetic, `and`/`or`/`not`, and `abs sqrt hypot min max deg
rad`. Anything else (calls, attributes of non-signals, strings, subscripts) is refused when the
scenario is defined. A Python predicate (`Scenario(name, predicate=fn, signals=[...])`) is the
escape hatch. "Holds for d" counts each sample as one sample period long: k consecutive samples
last k·dt. A match is the window from its first to its last sample. A run that doesn't log a
needed signal is reported as "not checked: missing …", never as no match (RI-03).

**D-056 — The run catalog (RI-01).** A run is a Parquet log (SE-06) in a run folder: `runs/` next
to the scene file in the app (projects arrive in M6), `runs/` in the working directory headless,
or `SIMVIEW_RUNS`. The log's metadata gains `source` (sim, app, import), `units`, and `params`
(empty until `sim.params`, M6). The date and the scene file go in a sidecar `<run>.run.json`,
because the log itself must stay byte-identical for the same seed (NF-06, and SC-04 compares a
scene file's log with the same scene built in code). The catalog reads only Parquet footers and
sidecars; there is no separate index to go stale. The app saves the live run when it is stopped
(or the scene closed), if it has more than one sample.

**D-057 — Scanning (RI-02).** Results of expression scenarios are cached per run in
`<folder>/.scan-cache.json`, keyed by the run file's size and modification time and by the
scenario's name and text, so a scan reads only new or changed runs ("new runs are scanned when
they finish": the app scans right after saving a run; headless, `simview runs scan` or
`investigate.scan`). Predicates aren't cached. Expression scenarios are saved in
`<folder>/scenarios.json`.

**D-058 — Opening a run replays it through its scene (RI-01, RI-06).** The sim process loads the
run's scene, then for each logged row sets the entities' states (states the log lacks keep their
start values), recomputes markers and body poses, and sends the rows as history; channels come
from the log. The timeline then shows the run in "recorded" mode: Play replays it and stops at
its end, step forward stops there too, and Stop goes back to the live scene. Debug draws aren't
in logs, so a replayed run shows none. An imported log's unmapped columns aren't scene signals:
they are scanned and reported, but not in the Signals panel.

**D-059 — Findings, comparisons (RI-03, RI-05).** Findings are grouped by run in the Runs
panel. Clicking one opens its run if another is shown, moves the timeline to the window's start,
zooms every time plot to the window with context either side, and adds a time plot of its
signals if none shows them. Comparison aligns two runs on shared ticks when their sample periods
match, otherwise interpolates the baseline onto the run's times, over the time both cover. A
signal diverges where |Δ| > atol + rtol·|baseline| (the app uses 1e-6 and 1e-6; the API and CLI
default to 1e-9 and 0). Each first divergence and each scenario match found in only one run
becomes a finding; `simview runs compare` exits 1 when anything diverged.

**D-060 — Reports (RI-04).** One self-contained HTML file: inline CSS from the light-theme
tokens, plots as inline SVG drawn with matplotlib (text as outlines, so no fonts are needed),
no scripts or links. Per run: metadata, every match (scenario, window, signals), the scenarios
it couldn't check, plots of the matched scenarios' signals with the windows shaded (or the
run's channels when nothing matched), and min/max/mean/final of every signal with units. A set
of runs adds a scenario × run table; a comparison adds its table and a plot. The app writes
reports to `<run folder>/reports/` and opens them. New dependency: `matplotlib` (PRD §8.1 lists
it for exports).

**D-061 — Importing logs (RI-06).** CSV or Parquet; `mapping` renames log columns to scene
signals (`ur5.shoulder_pan_joint.q=j1`). Time comes from one column (scaled, e.g. ms → s),
shifted to start at 0; rows are sorted by time and repeated times dropped; the sample period is
the median spacing and ticks are time / period. Other numeric columns are kept under their own
names. The app's Import asks for the file, then shows a `signal = column` mapping prefilled with
columns that already match the scene's signals.

**D-062 — Faster scrubbing.** Scrubbing a run rendered the 3D view three to four times per move:
pyvista re-renders whenever an actor is added or removed (the debug draws are rebuilt), and the
UI rendered on every timer tick even when nothing had changed. Draw actors are now added and
removed without rendering, the UI renders only when the shown moment, the history, or the draws
changed, and an empty draw set is one shared object. Measured: a finding click on an open run
takes 49–62 ms with the OpenGL viewport (it was 67–124 ms).

## M6

**D-063 — M6 dependencies.** `qtconsole`, `ipykernel`, and `pygments`, all named in PRD §8.1
(console: qtconsole + ipykernel in-process; editor: QPlainTextEdit + Pygments). QScintilla is
not used, so nothing needed asking.

**D-064 — Declaring parameters (SC-05).** A scene file declares them: `scene.params.kp = 2000.0`
(numbers or arrays of numbers). Controllers read `ctx.params.kp` (or `scene.params`, the same
object as `sim.params`). The set of names is fixed when a run starts (`Sim` freezes it), so
`sim.params.kpp = 3` is an error instead of a silent no-op, and a value keeps its kind (a
number stays a float, an array keeps its shape). Scalar parameters are logged every tick as
`params.<name>` channels, so a live change shows in plots, reports, comparisons, and scenarios;
arrays are not logged. The run's metadata `params` holds the values at the start. Stop / Reset
reloads the scene file, so parameters go back to the file's values.

**D-065 — "Takes effect on the next tick."** The UI sends `{"cmd": "param"}`; the sim process
applies it between ticks (its command poll runs every loop iteration, at most one publish
period, about 8 ms, apart while running flat out), so the next tick computed uses it. The sim
answers with its current values (`"params"` event), also after rejecting a value, whose reason
goes to the console as stderr.

**D-066 — `sim` in the console (SC-01).** The sim runs in its own process (SE-02), so `sim` in
the console is a handle: `sim.t`, `sim.tick`, `sim.dt`, `sim.running`, `sim.entities`,
`sim.state(name)` (a dict by state name), `sim.signals` and `sim.data(signal=None)` (the recorded
history, what the timeline and plots show), `sim.params`, and `sim.play() / pause() / step(n)
/ reset()`. `sim.scene` builds a copy of the scene from its file inside the console, for
kinematics and inspection (UC-3: `sim.scene["ur5"].fk(q)`); it doesn't move with the sim. The
namespace also has `sv` (simview) and `np`.

**D-067 — One kernel per UI process.** IPython's shell is a process singleton, so every window
shares one in-process kernel and namespace; the newest window's `sim` is the one in it. Output
and tracebacks from the sim process (NF-10) are written above the prompt on a line of their own.
IPython also installs its namespace as `__main__`, and `%run` leaves `__file__` there, which
`multiprocessing`'s spawn would run again in a new sim process; `SimClient.start` hides
`__main__.__file__` while spawning (the sim process only needs `simview.ipc.server.serve`).

**D-068 — Editor (SC-02).** One script at a time with New / Open / Save. Run File (F5) saves the
file and runs it with `%run -i`, so it sees `sim` and its variables land in the workspace (an
untitled script runs its text as typed). Run Selection (F9) runs the selected whole lines, or
the current line when nothing is selected, dedented. Tab inserts 4 spaces. Ctrl/Cmd+S is the
window's Save: it saves the project, or with no project open, the editor's script. The editor
has no Save shortcut of its own, since two Ctrl+S shortcuts would cancel each other.

**D-069 — Workspace browser (SC-03).** It lists the console's user variables, refreshed after
every cell (typed, Run File, imports): not `_private` names, modules, functions, classes, or the
names SimView puts there (`sim`, `sv`, `np`, unless reassigned). Columns are Name, Value, Shape,
Type, with Value second because the side panel is narrow (full preview in its tooltip).
Double-clicking a NumPy array opens a table: 0-D and 1-D as one column, 2-D as is, higher
dimensions as (first axis, the rest), record arrays with one column per field, up to 1M cells.

**D-070 — The console dock has no empty state.** §7.8 asks every empty panel for a hint and an
action. The console is a live prompt with a banner, so it is never empty; the editor's hint is
its placeholder text, next to its Open button. The Workspace panel keeps an empty state (with
Import Data…) until a variable exists.

**D-071 — Importing data (IO-02).** File > Import Data reads a CSV file into one record array
named after the file (`flight_log["alt"]`; numeric columns as float64 with empty cells as NaN,
other columns as text) or a `.mat` file's variables by their own names (`scipy.io.loadmat`,
`squeeze_me=True`; MATLAB v7.3 files are HDF5 and need re-saving with `-v7`). The same functions
are `sv.io.data.load_csv`, `load_mat`, and `load_data` in scripts.

**D-072 — Projects (IO-04).** A `<name>.svproj` folder with `project.json` (format 1, name, the
open scene and script as relative paths) and `scenes/`, `diagrams/` (for M7), `scripts/`, and
`runs/`. Save Project copies the open scene and script into the folder if they came from
elsewhere (never overwriting: `name-1.py`), saves the script, and writes `project.json`; runs
are written to `runs/` when they stop (RI-01), and the Runs panel shows that folder. Files the
scene loads by relative path aren't copied. Workspace variables aren't saved (re-run the script).
Unknown `project.json` keys are kept on save; a newer format is refused. Opening a project loads
its scene and opens its script; the window layout is kept per project (DS-03, keyed by path).
New Project, Open Project, Save Project (Ctrl/Cmd+S), and Import Data are in the File menu,
the Project button, and the command palette.

**D-073 — Code colors.** New `SYNTAX` tokens per theme (keyword, string, number, comment,
function, class, builtin, decorator), each ≥ 4.5:1 on `bg.panel` and `bg.elevated` (tested).
One Pygments style built from them colors the editor and the console; the console's prompts
and errors use the existing accent, success, and error tokens. Code text uses JetBrains Mono
through a `role="code"` stylesheet rule (the app-wide `*` rule otherwise forces Inter).

**D-074 — PySide6 below 6.12 on Python 3.11.** After M6, the Ubuntu / Python 3.11 CI job passed
every test and then crashed at exit (`Fatal Python error: bool_dealloc`). Measured on CI:
PySide6 6.12.0 over-releases `True` when a signal is emitted (a five-line `Signal(object)`
script crashes Python 3.11 within 1000 emits), while 6.10.2 and 6.11.1 don't. qtconsole sends
every kernel message through such signals, so each console cell and each new window drained
`True`'s reference count until it was freed. Python 3.12 made `True` and `False` immortal, so
there the bug is harmless. `pyproject.toml` keeps `PySide6<6.12` on Python < 3.12 only; lift it
once a fixed PySide6 release is out.

## M7

**D-075 — How a diagram runs.** A diagram is a sampled system run as one of the scene's
controllers, every tick or at `rate` Hz (`scene.add_diagram("x.svd", rate=100)`). At each sample
it computes every block's outputs in topological order, writes Entity Input blocks (before the
entities move that tick), updates discrete blocks, then integrates its continuous states over
the sample period with the chosen integrator (`rk4` by default), holding discrete outputs and
entity readings (the same input hold as D-013). So a diagram and a script controller with the
same math give the same numbers: the M7 check passes with an exact match, not just within 1e-9.

**D-076 — Block semantics.** PID is discrete at the diagram's sample period Ts:
`I += e·Ts` (skipped while saturated and pushing further into the limit: anti-windup),
`D = (e - e_prev)/Ts` (0 at the first sample), `u = kp·e + ki·I + kd·D`, clipped to optional
limits. Derivative is the backward difference at samples. Sine follows Simulink (amplitude,
bias, frequency in rad/s, phase). Integrator's shape is its initial value's (a vector integrator
needs a vector initial value). Gain with a matrix multiplies; otherwise it scales elementwise.
Mux concatenates; Demux splits evenly. Entity State has one output per chosen state (all by
default, named after them); Entity Input sets the entity's whole `u` (a number or a vector).

**D-077 — Shapes and errors.** Signals are scalars, vectors, or matrices (no bus block is in the
MVP list, so no bus type). Shapes are found by evaluating the diagram once at t = 0 (a probe):
a mismatch is reported on the block where it happens. Every problem comes back at once as
`Issue(block path, message)` (unconnected input, bad parameter, missing entity, algebraic
loop, shape mismatch), so the editor can outline each offending block. An algebraic loop is a
cycle through direct-feedthrough blocks only (Tarjan SCCs); every block in it is reported.

**D-078 — Logging block signals (SE-06).** Every block output is logged as
`<diagram>.<block path>.<port>` (`[k]` per element of a vector or matrix), e.g.
`altitude.pid.y`, `altitude.ctrl/gain1.y` inside a subsystem. Outputs hold between samples.
The logger and the controller share one evaluation per sample, so the row for tick k shows the
outputs the controller used at tick k. To Workspace blocks are recorded in the run metadata;
`run.workspace()` returns each as a record array (`t`, `value`).

**D-079 — `.svd` files (BD-06).** JSON with sorted keys and 2-space indent, `format: 1`, a
`blocks` list (id, type, params, pos, and a nested `diagram` for subsystems) and a `wires`
list of `{"from": "block:port", "to": "block:port"}` with ports numbered from 0. One edited
parameter changes one line. A Python Function block saves its function as `"file.py:name"`
(relative to the diagram file) or `"module:name"`; a callable passed from a script works but
can't be saved.

**D-080 — Subsystems (BD-07).** `diagram.group(ids)` moves blocks into a Subsystem; each
distinct outside source becomes an Inport and each distinct inside source an Outport.
`ungroup` reverses it. The compiler flattens subsystems before running (inner blocks keep
their path), so grouping doesn't change results (tested bit for bit).

**D-081 — The M7 check uses vertical drone dynamics.** The PRD's check names a quadrotor, but
the 6-DOF quadrotor is part of the Aerospace toolbox (M8). `examples/drone_altitude/` uses the
quadrotor's vertical axis (m·z'' = thrust − m·g) with the same PID as a script (`script.py`) and
as a diagram (`blocks.py` + `altitude.svd`). Rerun the check with the full quadrotor in M8.

**D-082 — Where the editor lives (BD-01).** The central area holds two pages, the 3D view and
the diagram, switched by "3D View" / "Diagram" buttons in the main toolbar (Ctrl+1 / Ctrl+2,
also in the View menu and the command palette). A tab bar above the central area would cost
about 28 px of height and drop the §7.2.1 content share below its 68% floor (measured: 66%).
The editor is one diagram at a time with New / Open / Save (File menu, Project button, and its
own toolbar); a new window starts with an untitled, empty diagram whose canvas says
"Double-click to add a block." (§7.8's empty state). The parameter panel sits to the right of
the canvas, 180 to 240 px wide.

**D-083 — Editing and undo.** Every edit (add, connect, delete, move, rename, parameter,
group, ungroup) is one undo step; undo restores a JSON snapshot of the whole diagram (an
`.svd` file is a few kB). Connecting to an input that already has a wire replaces it (an input
takes one wire, BD-05). A block's `pos` is its top-left corner; positions snap to 8 px and grid
dots are drawn every 16 px. Parameters are typed as JSON or Python literals (`2.5`, `[1, 0]`);
anything else is taken as text, so `+-` and `drone` need no quotes. Ctrl+S on the Diagram page
saves the diagram (with a project open, it saves the project, which saves the diagram).

**D-084 — Checking in the editor (BD-05).** The editor re-runs `blocks.check` after every
edit, with a stand-in scene built from the sim process's description (entity names and state
names), so Entity State shows one port per state of its entity and a wrong entity name is
reported on the block. Without a scene, entity blocks report "no entity ... (entities: none)".
Problems on blocks inside a subsystem are also shown on the subsystem block. The compiler no
longer reports "input ... is not connected" on a block fed by a block that failed (the failing
block has its own message), so one bad block is outlined once, not along the whole chain.

**D-085 — When edits run, and projects.** A running scene compiled its diagram when it loaded
(SE-02: the sim is a separate process), so edits run after a reload. Saving a diagram that the
open scene runs reloads the scene right away if time isn't moving; while it runs, the status
bar says to stop it first. When a scene loads, the editor opens the scene's (first) diagram
unless it has unsaved edits to another one. A project records the open diagram as `diagram`
in `project.json` when it is inside the project; Save Project saves an untitled diagram to
`diagrams/diagram.svd`. A diagram outside the project stays where it is (the scene refers to it
by a relative path, D-072) and opens with its scene.

**D-086 — Live values and port colors (§7.7).** Hovering a wire shows its source's value at
the timeline's current row (live or scrubbed), `pid.y = 0.2101`, or `[a, b]` for a vector; a
diagram that the loaded scene doesn't run says "run the sim to see its value". Ports are
colored by the probed shape of their signal: scalar, vector, matrix (D-077: no bus). Input
ports and ports whose shape isn't known (the diagram doesn't compile) are drawn hollow; wires
take their source port's color. The category and port colors are tokens, ≥ 3:1 on the panel
surfaces in both themes (tested).

**D-087 — Canvas interaction and Scope plots (BD-01, BD-07, BD-08).** Left-drag on the canvas
selects with a rubber band; middle-drag or Alt + drag pans; the wheel zooms around the mouse
(25% to 400%); Ctrl+0 fits the diagram. Drag from any port to a port of the other direction to
connect. Delete / Backspace removes the selection, Ctrl+G groups the selected blocks into a
subsystem, Ctrl+Shift+G ungroups one, Ctrl+A selects all. Double-click a subsystem to open it;
breadcrumbs ("altitude › ctrl") and the Up button go back. Each Scope block gets a time plot in
the plot panel when its scene loads, titled `<diagram>.<scope>` with all its inputs; reloading
the scene replaces those plots (plots the user added are kept).

## Process

**D-088 — CI runs by hand or on PRs to main.** Every push ran 9 jobs, about 99 billed minutes
(GitHub bills macOS at 10× and Windows at 2× on private repos), and November's 43 runs used up
the account's Actions minutes. CI now triggers on `workflow_dispatch` and on pull requests to
`main` (docs-only changes skipped). Branch work is verified locally; the 3-OS run happens once
per milestone, before the owner merges.

## M8: Vehicles toolbox

**D-091 — Paths and roads (TB-VEH).** A path is a 2-D polyline (`sv.vehicles.Path`) with arc
length, `point_at` / `heading_at` (clamped to the ends) and `nearest`, whose `cross_track` is
positive left of the path. Road and lane primitives are data, not MuJoCo geometry: a `Road` is
a centerline with N lanes of equal width, lane 0 the rightmost (drive on the right); lanes and
edges are mitred offsets of the centerline. `road.draw(ctx.draw)` draws edges and dashed
dividers as persistent debug lines (call it once, at t = 0). Lidar doesn't see the road
surface; NPCs get solids with `scene.attach_shape` (D-090) when sensors should see them.

**D-092 — Kinematic bicycle.** Reference point is the rear axle; states x, y, yaw, v; input
`u = [accel, steer]`, clipped to `max_accel` / `max_steer` (35° default), speed held within
[`min_speed`, `max_speed`] (0 to 40 m/s, so no reversing by default). Wheelbase 2.7 m default.

**D-093 — Path trackers.** Pure pursuit uses lookahead `gain * v + min_lookahead` (0.5 s,
3 m) with the goal searched forward from the nearest point; Stanley uses the front-axle
cross-track error with a softening speed (1 m/s). Both are plain callables
`ctrl(x, y, yaw, v) -> steer`, so they work in script controllers and are easy to wrap as
blocks later; `speed_control` is a clipped P-controller on speed.

**D-094 — Scripted NPCs.** `ScriptedNPC` follows a path at a speed given as a constant, a
(t, v) schedule (linear between points) or a function of t; it has no dynamics and doesn't
react to other agents (the PRD's "scripted"). Arc length advances by the trapezoid rule, exact
for piecewise-linear schedules. At the path's end it stops, or starts over with `loop=True`.
