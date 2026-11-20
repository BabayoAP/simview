"""DS-08: start screen with recent projects and template cards."""

from simview.ui.app import Controller
from simview.ui.start_screen import StartScreen, add_recent_project, recent_projects


def test_four_template_cards(qapp, settings):
    s = StartScreen(settings)
    assert [c.template_id for c in s.cards] == [
        "av_scenario",
        "drone_delivery",
        "ur5_ik",
        "drone_landing",
    ]


def test_new_and_open_buttons(qapp, settings):
    s = StartScreen(settings)
    assert s.new_button.text() == "New Empty Scene"
    assert s.open_button.text() == "Open…"


def test_recent_empty_state_then_list(qapp, settings):
    s = StartScreen(settings)
    assert s.recent_stack.currentWidget() is s.recent_empty
    add_recent_project(settings, "/tmp/a.svproj")
    add_recent_project(settings, "/tmp/b.svproj")
    add_recent_project(settings, "/tmp/a.svproj")
    assert recent_projects(settings) == ["/tmp/a.svproj", "/tmp/b.svproj"]
    s.refresh_recent()
    assert s.recent_stack.currentWidget() is s.recent_list
    assert s.recent_list.item(0).text() == "a.svproj"


def test_card_click_opens_main_window(qapp, settings):
    """A card without a template scene yet (UR5) opens an empty window titled after it."""
    c = Controller(settings)
    c.start.show()
    c.start.cards[2].clicked.emit("ur5_ik")
    assert c.window is not None and c.window.isVisible()
    assert "Robotic Arm (UR5)" in c.window.windowTitle()
    assert not c.start.isVisible()
    c.window.show_start_screen.emit()
    assert c.start.isVisible()
    c.window.close()


def test_new_scene_opens_untitled(qapp, settings):
    c = Controller(settings)
    c.start.new_scene.emit()
    assert c.window is not None and "Untitled" in c.window.windowTitle()
    c.window.close()
