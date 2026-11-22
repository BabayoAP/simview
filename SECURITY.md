# Security

SimView is a local desktop tool. It has no network service and no accounts; the only network
access is downloading MuJoCo Menagerie robots over HTTPS, at one pinned commit, on first use.

## Threat model

**Code you choose to run is trusted.** Like MATLAB or Jupyter, SimView runs Python with your
permissions. That includes:

- scene files (`.py`) and editor scripts, and everything typed into the console;
- installed toolboxes (pip packages found through the `simview.toolboxes` entry point);
- projects (`.svproj`): opening one loads its scene file;
- block diagrams (`.svd`) that contain **Python Function** blocks: the editor imports the
  module or runs the `.py` file a block names, to read its ports;
- scenario files are *not* code: conditions such as `ur5.elbow_joint.v > 2.0 for 0.05 s` are
  read by a restricted parser (signal names, numbers, arithmetic, comparisons, a few functions).

Only open scenes, projects, diagrams, and toolboxes from sources you trust.

**Data files are not executed.** Run logs (Parquet and their `.run.json` side files), sweep
results, recorded datasets (`cameras.json`, PNG, `.npy` read with `allow_pickle=False`),
perception snapshots, CSV and `.mat` imports, TensorBoard event files, and HTML reports are
parsed as data. Files a dataset or project names must stay inside its folder. Replaying a run
loads the scene file named in its metadata, so SimView asks first unless that scene is the open
one, part of the open project, or one of SimView's own templates.

**The UI and the sim process** talk over a ZeroMQ socket on `127.0.0.1` (a random port) and
shared memory. Every message is signed with a random per-session key and unsigned messages are
dropped before they are read, so another local process can't make SimView run code through
the socket (it could still disrupt a session). Shared-memory frames are size-checked before
they are read. SimView is not designed to isolate users who share one machine.

See `docs/DECISIONS.md` D-136 for the details.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: **Security → Report a vulnerability** on
this repository. For something minor and not sensitive, a normal issue is fine.
