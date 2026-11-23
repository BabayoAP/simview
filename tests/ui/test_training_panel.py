"""ML-03 / ML-04: the Training panel follows a training run and replays recorded episodes."""

import numpy as np
import pytest
from qtpy.QtCore import Qt

pytest.importorskip("gymnasium")

import simview as sv  # noqa: E402
from simview.rl.metrics import EPISODE_RETURN, TRAINING_ENV  # noqa: E402
from simview.ui.main_window import MainWindow  # noqa: E402
from simview.ui.theme import tokens  # noqa: E402
from simview.ui.training_panel import TrainingPanel  # noqa: E402


def train_some(folder, episodes=4):
    env = sv.make_env("drone_landing", record_every=2, record_dir=folder)
    for ep in range(episodes):
        env.reset(seed=ep)
        while True:
            *_, term, trunc, _ = env.step(np.zeros(3, np.float32))
            if term or trunc:
                break


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.delenv(TRAINING_ENV, raising=False)
    train_some(tmp_path / "train-20261121-120000")
    sv.log_metric("train/loss", 100, 0.5)
    return tmp_path


def test_panel_follows_the_newest_run_and_plots_checked_metrics(qapp, runs, monkeypatch):
    p = TrainingPanel()
    assert p.stack.currentIndex() == 0  # empty state until a run folder has training
    p.set_runs_folder(runs)
    assert p.stack.currentIndex() == 1
    names = [p.metrics.item(i).text() for i in range(p.metrics.count())]
    assert {"episode/return", "episode/length", "episode/success", "train/loss"} <= set(names)
    assert p.checked() == [EPISODE_RETURN]  # the default
    assert len(p.items[EPISODE_RETURN].getData()[0]) == 4
    assert len(p.recorded.data) == 2  # episodes 0 and 2 have logs
    assert "4 episodes" in p.summary.text() and "2 recorded" in p.summary.text()
    loss = p.metrics.findItems("train/loss", Qt.MatchFlag.MatchExactly)[0]
    loss.setCheckState(Qt.CheckState.Checked)
    assert "train/loss" in p.items
    # training goes on: more episodes appear on the next poll
    monkeypatch.setenv(TRAINING_ENV, str(p.run.folder))
    train_some(p.run.folder, episodes=2)
    p.poll()
    assert len(p.items[EPISODE_RETURN].getData()[0]) == 6
    # a newer training run takes over
    newer = runs / "train-20261121-130000"
    train_some(newer, episodes=1)
    import os
    import time

    os.utime(newer, (time.time() + 5, time.time() + 5))
    p.poll()
    assert p.run.folder == newer and len(p.run.episodes) == 1
    p.style("light")
    assert p.plot.backgroundBrush().color().name() == tokens.color("light", "bg.panel").lower()


def test_clicking_a_recorded_episode_replays_it(qapp, settings, runs):
    w = MainWindow(settings)
    try:
        assert "training" in w.docks
        opened = []
        w.open_run = opened.append
        w.training.set_runs_folder(runs)
        got = []
        w.training.replay_requested.connect(got.append)
        pts = w.training.recorded.points()
        w.training._point_clicked(w.training.recorded, [pts[0]])
        assert got and got[0].endswith(".parquet")
        assert opened and opened[0].scene.endswith("scene.py") and opened[0].rows > 10
        w.replay_episode(str(runs / "missing.parquet"))
        assert "Can't open" in w.statusBar().currentMessage()
    finally:
        w.close()
