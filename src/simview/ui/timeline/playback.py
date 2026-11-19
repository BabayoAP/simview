"""Which moment the UI shows, and replay of recorded history (VP-05, DA-02; D-048).

The view is either *live* (following the sim process) or parked on a recorded row. Scrubbing or
stepping back pauses the sim and parks the view. Play from a parked row replays the recording at
the playback speed and, at its end, hands over to the live sim, which carries on from where it
is. Hovering a plot previews a row without moving the cursor. Qt-free.
"""

from __future__ import annotations

from typing import Protocol

from simview.ui.timeline.history import History

REPLAY_MAX_SPEED = 10.0  # replay speed when the playback speed is "Max" (as fast as possible)


class SimControls(Protocol):
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def step(self, n: int = 1) -> None: ...


class Playback:
    def __init__(self, sim: SimControls) -> None:
        self.sim = sim
        self.history: History | None = None
        self.cursor: int | None = None  # parked row; None follows the live sim
        self.preview: int | None = None  # row under a hovering plot cursor (DA-02)
        self.sim_running = False
        self.replaying = False
        self._replay_t = 0.0

    def reset(self, history: History | None) -> None:
        """A (re)loaded scene: back to live, nothing replaying."""
        self.history = history
        self.cursor = self.preview = None
        self.replaying = False

    # -- what to show -----------------------------------------------------------------------
    @property
    def live(self) -> bool:
        return self.cursor is None

    @property
    def running(self) -> bool:
        """True while time moves, live or replayed (the Play/Pause state)."""
        return self.sim_running or self.replaying

    @property
    def last(self) -> int:
        return self.history.n - 1 if self.history is not None else -1

    @property
    def index(self) -> int:
        """The row the cursor is on (the newest row when live)."""
        return self.last if self.cursor is None else min(self.cursor, self.last)

    @property
    def shown(self) -> int | None:
        """The row to draw, or None to draw the live state."""
        return self.preview if self.preview is not None else self.cursor

    # -- transport -----------------------------------------------------------------------------
    def play(self) -> None:
        if self.cursor is None:
            self.sim_running = True
            self.sim.play()
        elif not self.replaying:
            assert self.history is not None
            self.replaying = True
            self._replay_t = self.history.time_of(self.index)

    def pause(self) -> None:
        self.replaying = False
        if self.sim_running:
            self.sim_running = False
            self.sim.pause()

    def toggle(self) -> None:
        if self.running:
            self.pause()
        else:
            self.play()

    def seek(self, i: int) -> None:
        """Park on row `i` (the newest row means live, paused)."""
        self.pause()
        if self.history is None or self.history.n == 0:
            return
        i = min(max(int(i), 0), self.last)
        self.cursor = None if i == self.last else i

    def step_back(self) -> None:
        self.seek(self.index - 1)

    def step_forward(self) -> None:
        if self.cursor is None:
            self.pause()
            self.sim.step()
        else:
            self.seek(self.cursor + 1)

    def to_start(self) -> None:
        self.seek(0)

    def to_live(self) -> None:
        self.seek(self.last)

    def sim_stopped(self) -> None:
        """The sim paused itself (an error) or died."""
        self.sim_running = False

    def advance(self, wall_dt: float, speed: float) -> None:
        """Move a replay on by `wall_dt` seconds of wall time at `speed` (0 = max)."""
        if not self.replaying or self.history is None:
            return
        self._replay_t += wall_dt * (speed if speed > 0 else REPLAY_MAX_SPEED)
        i = self.history.index_at(self._replay_t)
        if self.history.time_of(i) > self._replay_t and i > 0:
            i -= 1  # never show a row from the future
        if i >= self.last:
            self.replaying = False
            self.cursor = None
            self.sim_running = True
            self.sim.play()  # the recording ran out: carry on live
        else:
            self.cursor = i
