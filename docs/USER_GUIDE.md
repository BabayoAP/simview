# SimView User Guide

How to get from opening SimView to a run you can inspect, plot, and share. In the app,
**Help > SimView User Guide** (F1) opens this page and **Help > Keyboard Shortcuts** (Ctrl+/)
lists every key. On macOS read Cmd wherever this guide says Ctrl.

Hover over any button to see what it does and its shortcut. If you're not sure where a command
lives, press **Ctrl+K** and type part of its name: every command is in the command palette.

## 1. Install and start

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/simview                 # or: simview --theme light
```

On Windows the program is `.venv\Scripts\simview`. Library robots (Panda, UR10e, Robotiq) are
downloaded the first time a scene uses them.

## 2. The start screen

The start screen opens with:

- **Templates**: ready-made scenes. Click a card to open it.
  - *Autonomous Vehicle*: a bicycle-model car with lidar and a camera.
  - *Drone Delivery*: a quadrotor fleet in wind, each with a GPS + IMU EKF.
  - *Robotic Arm (UR5)*: drag the end effector and watch IK solve.
  - *Drone Landing (RL)*: a Gymnasium environment for PPO training.
  - *Vision Drive*: a camera-only car with 8 cameras and an occupancy grid.
- **New Empty Scene** and **Open…** (a project folder).
- **Recent**: projects you opened before.

You can come back to it at any time with **File > Show Start Screen**.

## 3. The main window

| Area | What it's for |
|---|---|
| Toolbar (top) | Project menu, Run / Pause / Step / Stop, playback speed, 3D View / Diagram, dt and real-time factor, search |
| 3D view (centre) | The scene. The heads-up toolbar at its top frames the view, changes presets and display, and toggles grid, frames, trails, ortho, 2D and fly mode |
| Scene Tree, Signals (left) | Everything in the scene; every logged signal |
| Inspector, Workspace (right) | The selected object's pose and states (robots get a slider per joint); console variables |
| Timeline, Plots, Console / Editor, Runs, Training, Cameras, BEV Map (bottom) | Scrub the recording, plot signals, run Python, investigate saved runs, follow RL training, see camera streams and the bird's-eye map |

Every panel can be dragged, docked, floated, or tabbed. The layout is saved per project;
**View > Reset Layout** brings back the default. An empty panel tells you what goes there and
offers a button to fill it.

## 4. Run a simulation

1. Open a template (or `simview path/to/scene.py`).
2. Press **Space** to run and again to pause. **.** and **,** step one tick forward or back.
3. Pick a speed in the toolbar's speed box: 0.1× to 10× real time, or Max.
4. **Stop and Reset** saves the run to the project's runs folder and goes back to t = 0.

The simulation runs in its own process. If your scene code raises an error, the traceback
shows in the console and the window stays open: fix the file and press Run again.

## 5. Move around the 3D view

| Do this | To |
|---|---|
| Right-drag | Orbit around the point under the cursor |
| Ctrl + right-drag | Pan |
| Wheel | Zoom toward the cursor |
| Click | Select (the scene tree, inspector, and plots follow) |
| F / A | Frame the selection / frame everything |
| 1 / 3 / 7 / 0 | Front / right / top / iso view, or click the ViewCube |
| Tab | 2D mode (top-down, orthographic) |
| W A S D Q E | Fly, with fly mode on in the heads-up toolbar |

Robots with drag targets show a gizmo: drag it to move the target.

## 6. Scrub, plot, and export

- **Timeline**: every tick is recorded. Drag the slider to go back in time; Play from an
  earlier point replays the run, then carries on live. The buttons jump to the start and to live.
- **Plots**: drag signals from the Signals panel onto the Plots panel. Use the buttons at the
  top of the Plots panel to add a time, XY, scatter, or histogram plot. Hovering a time plot moves the 3D view to that moment.
- **Export Data** (download button on the Plots panel, or File > Export Data…) writes every
  signal to CSV, Parquet, or MATLAB `.mat`. Each plot exports to PNG or SVG.

## 7. Block diagrams

Click **Diagram** in the toolbar (Ctrl+2) to switch to the block editor.

- Double-click the canvas to add a block; type to search.
- Drag from an output port to an input port to connect.
- Select blocks and press Ctrl+G to group them into a subsystem; double-click a subsystem to
  open it, and use the "Up one level" button to come back.
- Ctrl+0 fits the diagram in view. Undo and redo cover every edit.
- Hover over a wire during a run to see its live value. Problems (for example an algebraic loop)
  show as a red outline with the message under the block.

## 8. Python: console and editor

The **Console / Editor** panel has an IPython console and a script editor. In the editor,
**F5** runs the file and **F9** runs the selection. Variables you create show in the
**Workspace** panel; double-click an array to open it in a table.

Headless runs, without the window:

```bash
simview run examples/bouncing_ball.py --headless --duration 5
```

## 9. Investigate runs

Every run is saved as a Parquet log in the runs folder. The **Runs** panel lists them. Add a
scenario such as `lifted: cube.z > 0.08 for 0.5 s` and press **Scan** to search every run; click
a match to jump the timeline to it. From the command line:

```bash
simview runs scan -s "lifted: cube.z > 0.08 for 0.5 s" --save
simview runs report <run> -o report.html
simview runs compare <run> <baseline>
simview reproduce <run>
```

## 10. Scenario tests

A suite (TOML or Python) runs scenes over parameter samples and checks pass/fail criteria:

```bash
simview test src/simview/templates/drone_delivery/checks.toml
simview test suite.toml --save-baseline base.json      # record
simview test suite.toml --baseline base.json           # flag new failures and drifts
```

It exits with code 1 on a failure and writes JUnit XML and an HTML report, so it fits in CI.

## 11. Monte Carlo sweeps and RL training

- **File > Open Sweep Results…** opens a sweep made with `sv.sweep`: pick a metric and a
  parameter to see how they relate.
- The **Training** panel follows a training folder (for example from the Drone Landing
  template); click a large (recorded) point on its plot to replay that episode in the 3D view.

## 12. Help and settings

- **Ctrl+K**: command palette, every command with fuzzy search.
- **Ctrl+/**: keyboard shortcuts, with a filter box.
- **View > Toggle Light/Dark Theme**.
- Problems or ideas: open an issue on [GitHub](https://github.com/BabayoAP/simview/issues).
