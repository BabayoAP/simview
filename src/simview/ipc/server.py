"""The sim process (SE-02): loads a scene file, runs it paced or flat out, and publishes state.

Runs in a child process started by `SimClient`. A user-code exception (in the scene file or a
controller) is sent to the UI as a traceback and pauses the run; the process stays up (NF-10).
`print` output from scene code is forwarded to the UI console.
"""

from __future__ import annotations

import io
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import zmq

from simview.ipc import protocol as proto
from simview.ipc.record import RowLayout, record_row, replay_rows, row_layout
from simview.ipc.shm import Layout, StateBuffer

PUBLISH_PERIOD = 1 / 120  # s of wall time between state frames (twice the 60 Hz render rate)
MAX_BATCH = 2000  # ticks per loop iteration when running flat out, so commands stay responsive
IDLE_POLL_MS = 10
RTF_WINDOW = 0.5  # s of wall time the reported real-time factor averages over


class _Forward(io.TextIOBase):
    """stdout/stderr of scene code -> LOG events."""

    def __init__(self, sock: zmq.Socket, stream: str) -> None:
        self.sock, self.stream = sock, stream
        self._pending = ""

    def write(self, s: str) -> int:
        # Line-buffered: print("a", 1) writes "a", " ", "1", "\n" separately.
        self._pending += s
        if "\n" in self._pending:
            lines, self._pending = self._pending.rsplit("\n", 1)
            self.sock.send_pyobj({"event": proto.LOG, "stream": self.stream, "text": lines + "\n"})
        return len(s)

    def flush(self) -> None:
        if self._pending:
            text, self._pending = self._pending, ""
            self.sock.send_pyobj({"event": proto.LOG, "stream": self.stream, "text": text})


class Server:
    def __init__(self, scene_path: str, address: str) -> None:
        self.scene_path = scene_path
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.PAIR)
        self.sock.connect(address)
        self.buffer: StateBuffer | None = None
        self.sim: Any = None
        self.scene: Any = None
        self.running = False
        self.speed = 1.0  # x real time; 0 = as fast as possible (SE-10)
        self.rtf = 0.0
        self._published = 0.0
        self._pace_wall = 0.0
        self._pace_sim = 0.0
        self._last_draws: list[tuple] | None = None
        self.row_layout: RowLayout | None = None
        self._rows: list[np.ndarray] = []  # recorded since the last publish
        self._rtf_samples: list[tuple[float, float]] = []  # (wall, sim t) over RTF_WINDOW

    # -- loading --------------------------------------------------------------------------
    def load(self) -> bool:
        from simview.core.scheduler import Sim
        from simview.runner.headless import load_scene

        self.running = False
        try:
            scene = load_scene(Path(self.scene_path))
            sim = Sim(scene)
            desc = proto.describe(scene)
        except Exception:  # noqa: BLE001 - any user error must reach the console (NF-10)
            self.error()
            return False
        self.scene, self.sim = scene, sim
        markers = [e.name for e in desc.entities if e.has_marker]
        n_bodies = scene.world.model.nbody if scene.world is not None else 0
        layout = Layout.build(
            [e.name for e in desc.entities],
            [len(scene[e.name].x) for e in desc.entities],
            markers,
            n_bodies,
        )
        if self.buffer is not None:
            self.buffer.close(unlink=True)
        self.buffer = StateBuffer(layout, create=True)
        self.row_layout = row_layout(scene, layout)
        self._rows = []
        self.sock.send_pyobj(
            {
                "event": proto.READY,
                "layout": layout,
                "rows": self.row_layout,
                "shm": self.buffer.name,
                "description": desc,
            }
        )
        try:
            self.record()
        except Exception:  # noqa: BLE001 - a broken log channel must reach the console
            self.error()
        self.publish(force=True)
        return True

    def replay(self, path: str) -> None:
        """Reload the scene, then send a saved run's log as history rows (RI-01, RI-06)."""
        if not self.load():
            return
        assert self.row_layout is not None
        try:
            rows, dt = replay_rows(self.scene, self.sim, self.row_layout, path)
        except Exception:  # noqa: BLE001 - a bad log must reach the console, not kill the sim
            self.error()
            return
        finally:  # the live sim goes back to its start state
            for e in self.scene.entities.values():
                e.reset()
            if self.scene.world is not None:
                self.scene.world.reset()
            self.sim.tick = 0
        self.sock.send_pyobj({"event": proto.REPLAYED, "rows": rows, "dt": dt, "path": path})

    def error(self) -> None:
        self.running = False
        self.sock.send_pyobj({"event": proto.ERROR, "traceback": traceback.format_exc()})

    # -- state out ------------------------------------------------------------------------------
    def record(self) -> None:
        """Queue the history row for the current tick (sent with the next publish)."""
        assert self.row_layout is not None
        self._rows.append(record_row(self.scene, self.sim, self.row_layout))

    def publish(self, force: bool = False) -> None:
        now = time.monotonic()
        if self.buffer is None or (not force and now - self._published < PUBLISH_PERIOD):
            return
        self._published = now
        scene, sim = self.scene, self.sim
        bodies = None
        if scene.world is not None:
            import mujoco

            m, d = scene.world.model, scene.world.data
            mujoco.mj_kinematics(m, d)  # poses of the state just stepped to
            bodies = np.hstack([d.xpos, d.xquat])
        if self._rows:
            rows, self._rows = np.vstack(self._rows), []
            self.sock.send_pyobj({"event": proto.ROWS, "rows": rows})
        layout = self.buffer.layout
        self.buffer.write(
            tick=sim.tick,
            t=sim.t,
            rtf=self.rtf,
            running=self.running,
            wall=now,
            speed=self.speed,
            states={n: scene[n].x for n in layout.entity_names},
            markers={n: scene[n].position() for n in layout.marker_entities},
            bodies=bodies,
        )
        draws = proto.draws_payload(sim.draw.snapshot())
        if not proto.same_draws(self._last_draws, draws):
            self._last_draws = draws
            self.sock.send_pyobj({"event": proto.DRAWS, "draws": draws, "tick": sim.tick})

    # -- commands -------------------------------------------------------------------------------
    def handle(self, msg: dict[str, Any]) -> bool:
        """Apply one command; False means quit."""
        cmd = msg.get("cmd")
        if cmd == proto.QUIT:
            return False
        if cmd == proto.RESET:
            self.load()
            return True
        if cmd == proto.REPLAY:
            self.replay(str(msg["path"]))
            return True
        if self.sim is None:
            return True
        if cmd == proto.PLAY:
            self.running = True
            self._rtf_samples.clear()
            self._pace_wall, self._pace_sim = time.monotonic(), self.sim.t
        elif cmd == proto.PAUSE:
            self.running = False
            self.publish(force=True)
        elif cmd == proto.STEP:
            self.running = False
            self.advance(int(msg.get("n", 1)))
            self.publish(force=True)
        elif cmd == proto.SPEED:
            self.speed = float(msg["speed"])
            self._rtf_samples.clear()
            self._pace_wall, self._pace_sim = time.monotonic(), self.sim.t
        elif cmd == proto.TARGET:
            self.scene.targets[msg["name"]].pose = np.array(msg["pose"], dtype=np.float64)
            self.publish(force=True)
        elif cmd == proto.PARAM:
            try:
                self.sim.params.set(str(msg["name"]), msg["value"])
            except (AttributeError, TypeError) as exc:
                self.sock.send_pyobj({"event": proto.LOG, "stream": "stderr", "text": f"{exc}\n"})
            self.sock.send_pyobj({"event": proto.PARAMS, "values": self.sim.params.to_dict()})
        elif cmd == proto.BODY_POSE:
            body = self.scene[msg["name"]]
            body.x[:3] = msg["pos"]
            body.x[3:7] = msg["quat"]
            body.x[7:] = 0.0  # a dragged object starts at rest
            self.record()  # the current tick's row now shows the new pose
            self.publish(force=True)
        return True

    def _measure_rtf(self) -> None:
        now = time.monotonic()
        samples = self._rtf_samples
        samples.append((now, self.sim.t))
        while len(samples) > 2 and now - samples[1][0] >= RTF_WINDOW:
            samples.pop(0)
        (w0, t0), (w1, t1) = samples[0], samples[-1]
        if w1 > w0:
            self.rtf = (t1 - t0) / (w1 - w0)

    def advance(self, n: int) -> None:
        try:
            for _ in range(n):
                self.sim.step()
                self.record()
        except Exception:  # noqa: BLE001 - user controller errors pause the run (NF-10)
            self.error()
            self.publish(force=True)  # the UI must see the run as paused

    # -- loop -----------------------------------------------------------------------------------
    def run(self) -> None:
        sys.stdout = _Forward(self.sock, "stdout")  # type: ignore[assignment]
        sys.stderr = _Forward(self.sock, "stderr")  # type: ignore[assignment]
        self.load()
        poller = zmq.Poller()
        poller.register(self.sock, zmq.POLLIN)
        alive = True
        while alive:
            timeout = 0 if self.running else IDLE_POLL_MS
            while dict(poller.poll(timeout)).get(self.sock):
                if not self.handle(self.sock.recv_pyobj()):
                    alive = False
                    break
                timeout = 0
            if not alive or not self.running or self.sim is None:
                continue
            start_wall = time.monotonic()
            if self.speed > 0:
                # Paced (SE-10): step until sim time catches up with speed x wall time.
                due = self._pace_sim + (time.monotonic() - self._pace_wall) * self.speed
                n = min(MAX_BATCH, int((due - self.sim.t) / self.sim.dt))
                if n <= 0:
                    self.publish()
                    time.sleep(0.0005)
                    continue
            else:
                n = MAX_BATCH
                deadline = start_wall + PUBLISH_PERIOD
            done = 0
            while done < n and self.running:
                self.advance(1)
                done += 1
                if self.speed <= 0 and time.monotonic() >= deadline:
                    break
            self._measure_rtf()
            self.publish()
        if self.buffer is not None:
            self.buffer.close(unlink=True)
        self.sock.send_pyobj({"event": proto.STOPPED})
        self.sock.close(linger=500)
        self.ctx.term()


def serve(scene_path: str, address: str) -> None:
    """Entry point of the sim process."""
    Server(scene_path, address).run()
