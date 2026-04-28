from __future__ import annotations

from switch import cli


def test_display_host_for_daemons_uses_detected_ip_for_wildcard(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_detect_reachable_ip", lambda: "192.168.1.50")

    assert cli._display_host_for_daemons("0.0.0.0") == "192.168.1.50"
    assert cli._display_host_for_daemons("::") == "192.168.1.50"


def test_display_host_for_daemons_keeps_explicit_bind_host(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_detect_reachable_ip", lambda: "192.168.1.50")

    assert cli._display_host_for_daemons("10.0.0.8") == "10.0.0.8"
    assert cli._display_host_for_daemons("localhost") == "localhost"


def test_display_host_for_browser_uses_localhost_for_wildcard() -> None:
    assert cli._display_host_for_browser("0.0.0.0") == "localhost"
    assert cli._display_host_for_browser("::") == "localhost"
    assert cli._display_host_for_browser("10.0.0.8") == "10.0.0.8"
