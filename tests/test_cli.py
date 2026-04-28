from __future__ import annotations

import argparse
import asyncio
import threading

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


def test_run_hub_does_not_kill_port(monkeypatch) -> None:
    class FakeTimer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

    def fail_kill_port(port: int) -> None:
        raise AssertionError(f"_kill_port should not be called for switch hub: {port}")

    monkeypatch.setattr(cli, "_kill_port", fail_kill_port)
    monkeypatch.setattr(threading, "Timer", FakeTimer)

    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    cli._run_hub(argparse.Namespace(port=9341, host="0.0.0.0", verbose=False, dev=False))

    assert calls


def test_run_daemon_does_not_kill_port_by_default(monkeypatch) -> None:
    killed_ports = []

    monkeypatch.setattr(cli, "_kill_port", lambda port: killed_ports.append(port))
    monkeypatch.setattr(asyncio, "run", lambda coro: coro.close())

    cli._run_daemon(argparse.Namespace(port=9340, hub="http://localhost:9341", name=None, verbose=False))

    assert killed_ports == []
