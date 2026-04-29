from __future__ import annotations

import argparse
import asyncio
import subprocess
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


def test_local_hub_url_uses_browser_reachable_host() -> None:
    assert cli._local_hub_url("0.0.0.0", 9341) == "http://localhost:9341"
    assert cli._local_hub_url("10.0.0.8", 9341) == "http://10.0.0.8:9341"


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

    cli._run_hub(argparse.Namespace(
        port=9341,
        host="0.0.0.0",
        verbose=False,
        dev=False,
        local_daemon=False,
        daemon_port=9340,
        daemon_name="local",
    ))

    assert calls


def test_run_hub_can_launch_local_daemon(monkeypatch) -> None:
    class FakeTimer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

    class FakeThread:
        def __init__(self, target, daemon: bool) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            self.target()

    class FakeProc:
        pid = 12345

        def __init__(self, cmd, **kwargs) -> None:
            popen_calls.append((cmd, kwargs))
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    popen_calls = []
    killpg_calls = []

    import httpx
    import os
    import uvicorn

    monkeypatch.setattr(threading, "Timer", FakeTimer)
    monkeypatch.setattr(threading, "Thread", FakeThread)
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: object())
    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    cli._run_hub(argparse.Namespace(
        port=9341,
        host="0.0.0.0",
        verbose=True,
        dev=False,
        local_daemon=True,
        daemon_port=9440,
        daemon_name="dev-local",
    ))

    assert popen_calls
    cmd, kwargs = popen_calls[0]
    assert cmd[:3] == [cli.sys.executable, "-m", "switch.daemon"]
    assert "--port" in cmd
    assert "9440" in cmd
    assert "--hub" in cmd
    assert "http://localhost:9341" in cmd
    assert "--name" in cmd
    assert "dev-local" in cmd
    assert "--verbose" in cmd
    assert kwargs["start_new_session"] is True
    assert killpg_calls == [(12345, 15)]


def test_run_daemon_does_not_kill_port_by_default(monkeypatch) -> None:
    killed_ports = []

    monkeypatch.setattr(cli, "_kill_port", lambda port: killed_ports.append(port))
    monkeypatch.setattr(asyncio, "run", lambda coro: coro.close())

    cli._run_daemon(argparse.Namespace(port=9340, hub="http://localhost:9341", name=None, verbose=False))

    assert killed_ports == []
