"""The dashboard runs without errors on a simulated database (Streamlit AppTest, no browser)."""
import os

import pytest

from conftest import ROOT

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


@pytest.fixture
def simulated_db(tmp_path, monkeypatch):
    from data_sentinel import scenarios
    from data_sentinel.db import Database
    from data_sentinel.engine import Engine
    path = str(tmp_path / "dash.db")
    db = Database(url="", sqlite_path=path)
    db.init_schema()
    scenarios.run(Engine(db), verbose=False)
    db.close()
    monkeypatch.setattr("data_sentinel.config.SQLITE_PATH", path)
    monkeypatch.setattr("data_sentinel.config.DATABASE_URL", None)
    return path


def test_dashboard_renders_simulated_events(simulated_db):
    at = AppTest.from_file(os.path.join(ROOT, "dashboard", "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Events"] == "21" and metrics["Blocked"] == "15" and metrics["Warnings"] == "4"
    assert metrics["Audit chain"] == "✅ Intact"
    text = " ".join(m.value for m in at.markdown)
    assert "BLOCK" in text and "weekly_report.txt" in text


def test_resolve_all_alerts(simulated_db):
    at = AppTest.from_file(os.path.join(ROOT, "dashboard", "app.py"), default_timeout=60)
    at.run()
    next(b for b in at.button if b.label == "Resolve all").click().run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Open alerts"] == "0"


def test_hosted_demo_seeds_itself(tmp_path, monkeypatch):
    """With SENTINEL_DEMO_SEED=1 an empty database is filled with the simulated scenarios."""
    monkeypatch.setattr("data_sentinel.config.SQLITE_PATH", str(tmp_path / "hosted.db"))
    monkeypatch.setattr("data_sentinel.config.DATABASE_URL", None)
    monkeypatch.setenv("SENTINEL_DEMO_SEED", "1")
    at = AppTest.from_file(os.path.join(ROOT, "dashboard", "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Events"] == "21" and metrics["Blocked"] == "15"
