from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import threading

from switch import cli


def test_host_command_dispatches_to_agent_host_runner(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(sys, "argv", ["switch", "host", "--hub", "http://hub.example.test", "--name", "devbox"])
    monkeypatch.setattr(cli, "_run_daemon", lambda args: calls.append(args))

    cli.main()

    assert len(calls) == 1
    assert calls[0].hub == "http://hub.example.test"
    assert calls[0].name == "devbox"


def test_daemon_command_remains_backward_compatible(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(sys, "argv", ["switch", "daemon", "--hub", "http://hub.example.test"])
    monkeypatch.setattr(cli, "_run_daemon", lambda args: calls.append(args))

    cli.main()

    assert len(calls) == 1
    assert calls[0].hub == "http://hub.example.test"


def test_hub_command_defaults_to_loopback(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(sys, "argv", ["switch", "hub"])
    monkeypatch.setattr(cli, "_run_hub", lambda args: calls.append(args))

    cli.main()

    assert len(calls) == 1
    assert calls[0].host == "127.0.0.1"
    assert calls[0].allow_insecure is False


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
        allow_insecure=True,
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
        allow_insecure=True,
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


def test_run_hub_ready_check_uses_ui_token(monkeypatch) -> None:
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

        def __init__(self, *args, **kwargs) -> None:
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    get_calls = []

    import httpx
    import os
    import uvicorn

    monkeypatch.setenv("SWITCH_UI_TOKEN", "ui-secret")
    monkeypatch.setattr(threading, "Timer", FakeTimer)
    monkeypatch.setattr(threading, "Thread", FakeThread)
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: get_calls.append((args, kwargs)) or object())
    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(os, "killpg", lambda *args, **kwargs: None)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    cli._run_hub(argparse.Namespace(
        port=9341,
        host="127.0.0.1",
        verbose=False,
        dev=False,
        local_daemon=True,
        daemon_port=9440,
        daemon_name="dev-local",
        allow_insecure=False,
    ))

    assert get_calls
    assert get_calls[0][1]["headers"] == {"X-Agentic-UI-Token": "ui-secret"}


def test_run_hub_refuses_public_bind_without_auth(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SWITCH_UI_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    try:
        cli._run_hub(argparse.Namespace(
            port=9341,
            host="0.0.0.0",
            verbose=False,
            dev=False,
            local_daemon=False,
            daemon_port=9340,
            daemon_name="local",
            allow_insecure=False,
        ))
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")

    assert "refusing to bind" in capsys.readouterr().err


def test_run_hub_allows_public_bind_with_ui_token(monkeypatch) -> None:
    class FakeTimer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

    import uvicorn

    calls = []
    monkeypatch.setenv("SWITCH_UI_TOKEN", "ui-secret")
    monkeypatch.setattr(threading, "Timer", FakeTimer)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    cli._run_hub(argparse.Namespace(
        port=9341,
        host="0.0.0.0",
        verbose=False,
        dev=False,
        local_daemon=False,
        daemon_port=9340,
        daemon_name="local",
        allow_insecure=False,
    ))

    assert calls


def test_run_daemon_does_not_kill_port_by_default(monkeypatch) -> None:
    killed_ports = []

    monkeypatch.setattr(cli, "_kill_port", lambda port: killed_ports.append(port))
    monkeypatch.setattr(asyncio, "run", lambda coro: coro.close())

    cli._run_daemon(argparse.Namespace(
        port=9340,
        hub="http://localhost:9341",
        token=None,
        hf_token=None,
        name=None,
        verbose=False,
    ))

    assert killed_ports == []


def test_daemon_token_defaults_to_env(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "from-env")

    assert cli._daemon_token(argparse.Namespace(token=None)) == "from-env"
    assert cli._daemon_token(argparse.Namespace()) == "from-env"


def test_daemon_token_uses_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "from-env")

    assert cli._daemon_token(argparse.Namespace(token="explicit")) == "explicit"


def test_hf_token_defaults_to_env(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-env")

    assert cli._hf_token(argparse.Namespace(hf_token=None)) == "hf-env"
    assert cli._hf_token(argparse.Namespace()) == "hf-env"


def test_hf_token_falls_back_to_hf_login_cache(monkeypatch) -> None:
    import huggingface_hub

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.setattr(huggingface_hub, "get_token", lambda: "cached-hf-token")

    assert cli._hf_token(argparse.Namespace(hf_token=None)) == "cached-hf-token"


def test_hf_token_uses_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-env")

    assert cli._hf_token(argparse.Namespace(hf_token="hf-explicit")) == "hf-explicit"


def test_missing_hf_token_message_explains_private_space_failure() -> None:
    message = cli._missing_hf_token_message("https://edbeeching-agentic-ui.hf.space", None)

    assert message is not None
    assert "--hf-token" in message
    assert "HF_TOKEN" in message
    assert "HTTP 404" in message


def test_missing_hf_token_message_is_skipped_for_non_hf_hub() -> None:
    assert cli._missing_hf_token_message("http://localhost:9341", None) is None


def test_missing_hf_token_message_is_skipped_when_token_present() -> None:
    assert cli._missing_hf_token_message("https://edbeeching-agentic-ui.hf.space", "hf-token") is None


def test_daemon_name_defaults_to_hostname(monkeypatch) -> None:
    monkeypatch.setattr("platform.node", lambda: "devbox")

    assert cli._daemon_name(argparse.Namespace(name=None, port=9340)) == "devbox"


def test_daemon_name_uses_explicit_value(monkeypatch) -> None:
    monkeypatch.setattr("platform.node", lambda: "devbox")

    assert cli._daemon_name(argparse.Namespace(name="custom", port=9340)) == "custom"
