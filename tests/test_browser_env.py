import os

from nonebot_plugin_checkin import envbridge


def test_bridge_sets_when_config_has_value(monkeypatch) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    applied = envbridge.bridge_playwright_path("/opt/ms-playwright")
    assert applied is True
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/ms-playwright"


def test_bridge_does_not_override_real_env(monkeypatch) -> None:
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/already/set")
    applied = envbridge.bridge_playwright_path("/opt/ms-playwright")
    assert applied is False
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/already/set"


def test_bridge_noop_when_config_empty(monkeypatch) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert envbridge.bridge_playwright_path(None) is False
    assert envbridge.bridge_playwright_path("") is False
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_bridge_tolerant_of_whitespace(monkeypatch) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert envbridge.bridge_playwright_path("  /opt/ms-playwright  ") is True
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/ms-playwright"
