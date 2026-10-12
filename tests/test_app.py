"""Headless smoke test of the Streamlit app (streamlit.testing AppTest)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


@pytest.fixture(scope="module")
def at():
    app = AppTest.from_file(APP, default_timeout=120)
    app.run()
    return app


def _goto(at, page):
    at.sidebar.radio(key="page").set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]


def test_overview_renders_headline(at):
    assert not at.exception
    assert any("Headline" in i.value for i in at.info)
    assert len(at.metric) >= 4


def test_drilldown(at):
    _goto(at, "Material drill-down")
    assert at.title[0].value == "Material drill-down"


def test_replay_controls(at):
    _goto(at, "Step-by-step replay")
    labels = [b.label for b in at.button]
    for expected in ["▶ Play", "⏸ Pause", "⏭ Next day", "⏮ Reset"]:
        assert expected in labels
    assert at.select_slider(key="speed").value == "1 day/s (slow)"
    next_btn = next(b for b in at.button if b.label == "⏭ Next day")
    next_btn.click().run()
    assert not at.exception
    assert at.session_state["replay_day"] == 1


def test_export_page(at):
    _goto(at, "SAP export")
    labels = [m.label for m in at.metric]
    assert {"Auto-update", "Needs planner approval", "No change (dead band)"} <= set(labels)


def test_about_page(at):
    _goto(at, "About & SAP fields")


def test_parameter_change_reruns(at):
    _goto(at, "Overview")
    at.sidebar.radio[1].set_value("Backorder").run()
    assert not at.exception
