"""The UI side of the sim process (SE-02): start it, send commands, read state and events.

Qt-free on purpose: the UI polls it from a timer, and tests drive it directly. If the sim
process dies (killed, segfault), `poll()` reports a STOPPED event with the exit code and the
UI keeps running (NF-10); `start()` can launch a new one.
"""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
from typing import Any

import zmq

from simview.ipc import protocol as proto
from simview.ipc.record import RowLayout
from simview.ipc.server import serve
from simview.ipc.shm import Frame, Layout, StateBuffer


class SimClient:
    def __init__(self) -> None:
        self.ctx = zmq.Context.instance()
        self.sock: zmq.Socket | None = None
        self.proc: mp.process.BaseProcess | None = None
        self.buffer: StateBuffer | None = None
        self.layout: Layout | None = None
        self.description: proto.Description | None = None
        self.row_layout: RowLayout | None = None  # history row columns (VP-05, DA-01)
        self.scene_path: Path | None = None
        self._dead_reported = False

    # -- lifecycle --------------------------------------------------------------------------
    def start(self, scene_path: str | Path) -> None:
        """Launch a sim process for `scene_path` (stopping any current one)."""
        self.stop()
        self.scene_path = Path(scene_path).resolve()
        self.sock = self.ctx.socket(zmq.PAIR)
        port = self.sock.bind_to_random_port("tcp://127.0.0.1")
        spawn = mp.get_context("spawn")  # same behavior on every OS; no forked Qt state
        self.proc = spawn.Process(
            target=serve, args=(str(self.scene_path), f"tcp://127.0.0.1:{port}"), daemon=True
        )
        self.proc.start()
        self._dead_reported = False

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.is_alive()

    def stop(self, timeout: float = 2.0) -> None:
        if self.proc is not None:
            if self.proc.is_alive():
                self.send(proto.QUIT)
                self.proc.join(timeout)
            if self.proc.is_alive():
                self.proc.kill()
                self.proc.join(timeout)
            self.proc = None
        self._release()
        if self.sock is not None:
            self.sock.close(linger=0)
            self.sock = None

    def _release(self) -> None:
        if self.buffer is not None:
            self.buffer.close()
            self.buffer = None

    # -- commands ---------------------------------------------------------------------------------
    def send(self, cmd: str, **kw: Any) -> None:
        if self.sock is not None and self.alive:
            self.sock.send_pyobj({"cmd": cmd, **kw})

    def play(self) -> None:
        self.send(proto.PLAY)

    def pause(self) -> None:
        self.send(proto.PAUSE)

    def step(self, n: int = 1) -> None:
        self.send(proto.STEP, n=n)

    def reset(self) -> None:
        self.send(proto.RESET)

    def set_speed(self, speed: float) -> None:
        """Playback speed as a multiple of real time (0.1-10); 0 runs as fast as possible."""
        self.send(proto.SPEED, speed=speed)

    def set_target(self, name: str, pose: Any) -> None:
        self.send(proto.TARGET, name=name, pose=pose)

    def set_body_pose(self, name: str, pos: Any, quat: Any) -> None:
        self.send(proto.BODY_POSE, name=name, pos=pos, quat=quat)

    # -- state and events in ---------------------------------------------------------------
    def poll(self) -> list[dict[str, Any]]:
        """All pending events. READY attaches the state buffer; a dead process is reported once."""
        events: list[dict[str, Any]] = []
        while self.sock is not None and self.sock.poll(0):
            ev = self.sock.recv_pyobj()
            if ev.get("event") == proto.READY:
                self._release()
                self.layout = ev["layout"]
                self.description = ev["description"]
                self.row_layout = ev["rows"]
                self.buffer = StateBuffer(ev["layout"], name=ev["shm"])
            events.append(ev)
        if self.proc is not None and not self.proc.is_alive() and not self._dead_reported:
            self._dead_reported = True
            events.append({"event": proto.STOPPED, "exitcode": self.proc.exitcode})
        return events

    def frame(self) -> Frame | None:
        return self.buffer.read() if self.buffer is not None else None
