from __future__ import annotations

import pytest

from app.config import Config
from app.state.app_state import AppState


def _fresh_state(tmp_path, monkeypatch, demo: bool = True) -> AppState:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    user_path = tmp_path / "config" / "financial-terminal" / "config.toml"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config.load(user_path=user_path)
    if demo:
        config.set("data.demo_mode", True)
    return AppState.create(config)


@pytest.fixture()
def demo_state(tmp_path, monkeypatch):
    state = _fresh_state(tmp_path, monkeypatch, demo=True)
    yield state
    state.close()


@pytest.fixture()
def live_state(tmp_path, monkeypatch):
    state = _fresh_state(tmp_path, monkeypatch, demo=False)
    yield state
    state.close()


@pytest.fixture()
def r_analytics(demo_state):
    if not demo_state.r_available:
        pytest.skip("R analytics unavailable")
    return demo_state.analytics
