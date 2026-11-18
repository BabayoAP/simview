"""DS-07: command palette listing every registered action, with fuzzy search."""

from qtpy.QtGui import QKeySequence

from simview.ui.actions import fuzzy_filter, fuzzy_score
from simview.ui.main_window import MainWindow


def test_fuzzy_score_subsequence():
    assert fuzzy_score("tgl thm", "Toggle Light/Dark Theme") is not None
    assert fuzzy_score("xyz", "Run") is None
    assert fuzzy_score("", "anything") == 0


def test_fuzzy_ranks_word_starts_and_runs_first():
    ranked = fuzzy_filter("run", ["Reset Layout", "Simulation: Run", "Show Console"])
    assert ranked[0] == "Simulation: Run"
    assert "Show Console" not in ranked


def test_palette_lists_every_registered_action(qapp, settings):
    w = MainWindow(settings)
    w.palette_.open()
    ids = set(w.palette_.visible_action_ids())
    assert ids == {a.objectName() for a in w.actions_.all()}
    w.palette_.hide()


def test_palette_filters_and_runs(qapp, settings):
    w = MainWindow(settings)
    hits = []
    w.actions_.get("view.reset_layout").triggered.connect(lambda *_: hits.append(1))
    w.palette_.open()
    w.palette_.search.setText("reset lay")
    assert w.palette_.visible_action_ids()[0] == "view.reset_layout"
    w.palette_.run_current()
    assert hits == [1]
    assert not w.palette_.isVisible()


def test_palette_shortcut_is_ctrl_k(qapp, settings):
    w = MainWindow(settings)
    # Qt maps Ctrl to Cmd on macOS.
    assert w.actions_.get("palette.open").shortcut() == QKeySequence("Ctrl+K")


def test_duplicate_action_ids_rejected(qapp, settings):
    import pytest

    w = MainWindow(settings)
    with pytest.raises(ValueError):
        w.actions_.register("palette.open", "x", lambda: None)
