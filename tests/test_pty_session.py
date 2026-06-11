from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import sys
from pathlib import Path

import pytest

from hf_agent_ui.daemon.pty_session import (
    TOOL_COMMANDS,
    PtySession,
    _codex_hook_config_args,
    _detect_action_required,
    _detect_claude_input_hook,
    _detect_claude_notification,
    _detect_codex_permission_request,
)


MOCK_CLI = str(Path(__file__).parent / "mock_cli.py")


def test_default_tool_is_codex(tmp_path: Path) -> None:
    session = PtySession(work_dir=str(tmp_path))

    assert session.tool == "codex"


def test_pause_exits_tui_cleanly_and_keeps_session_paused(tmp_path: Path) -> None:
    async def run() -> None:
        session = PtySession(work_dir=str(tmp_path), tool="mock")
        await session.start()

        session.pause()

        assert session._read_task is not None
        await asyncio.wait_for(session._read_task, timeout=2)
        assert session.status == "paused"
        assert session._proc is not None
        assert session._proc.returncode == 0
        assert session._master_fd is None

    TOOL_COMMANDS["mock"] = [sys.executable, MOCK_CLI]
    try:
        asyncio.run(run())
    finally:
        del TOOL_COMMANDS["mock"]


def test_custom_launch_command_renders_quoted_placeholders(tmp_path: Path) -> None:
    work_dir = tmp_path / "project with spaces"
    work_dir.mkdir()
    tool_args = ["/bin/mock tool", "arg value"]
    session = PtySession(
        work_dir=str(work_dir),
        tool="mock",
        launch_mode="custom",
        launch_command="launcher --cwd {workDir} -- {command}",
        launch_label="gpu",
    )

    args = session._build_args(tool_args, resume=False)

    assert args[:2] == ["/bin/sh", "-lc"]
    assert args[2] == (
        f"launcher --cwd {shlex.quote(str(work_dir.resolve()))} -- "
        f"{shlex.join(tool_args)}"
    )
    assert session.to_info().launch_mode == "custom"
    assert session.to_info().launch_label == "gpu"


def test_custom_launch_command_requires_command_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\{command\}"):
        PtySession(
            work_dir=str(tmp_path),
            tool="mock",
            launch_mode="custom",
            launch_command="launcher --cwd {workDir}",
        )


def test_custom_launch_resume_uses_same_template(tmp_path: Path) -> None:
    session = PtySession(
        work_dir=str(tmp_path),
        tool="claude",
        launch_mode="custom",
        launch_command="launcher {command}",
        resume_token="claude-session",
    )

    args = session._build_args(["claude"], resume=True)

    assert args[2] == "launcher claude --resume claude-session"


def test_bash_tool_builds_plain_shell_command(tmp_path: Path) -> None:
    session = PtySession(work_dir=str(tmp_path), tool="bash")

    assert TOOL_COMMANDS["bash"] == ["bash"]
    assert session._build_tool_args(["bash"], resume=False) == ["bash"]
    assert session._build_tool_args(["bash"], resume=True) == ["bash"]
    assert session._pause_exit_command() == "exit\r"


def test_bash_ignores_yolo_mode(tmp_path: Path) -> None:
    session = PtySession(work_dir=str(tmp_path), tool="bash", yolo_mode=True)

    assert session.yolo_mode is False
    assert session.to_info().yolo_mode is False
    assert session._build_tool_args(["bash"], resume=False) == ["bash"]


def test_codex_hook_config_is_added_when_hook_enabled(tmp_path: Path) -> None:
    session = PtySession(work_dir=str(tmp_path), tool="codex")
    session._codex_hook_enabled = True

    args = session._build_tool_args(["codex"], resume=False)

    assert args[0] == "codex"
    assert "-c" in args
    assert "features.hooks=true" in args
    assert any("hooks.PermissionRequest" in arg for arg in args)
    assert args[-2:] == ["--cd", str(tmp_path.resolve())]


def test_codex_yolo_initial_launch_adds_bypass_flag(tmp_path: Path) -> None:
    session = PtySession(work_dir=str(tmp_path), tool="codex", yolo_mode=True)

    args = session._build_tool_args(["codex"], resume=False)

    assert args == [
        "codex",
        "--dangerously-bypass-approvals-and-sandbox",
        "--cd",
        str(tmp_path.resolve()),
    ]


def test_codex_yolo_resume_adds_bypass_before_resume(tmp_path: Path) -> None:
    session = PtySession(
        work_dir=str(tmp_path),
        tool="codex",
        resume_token="codex-session",
        yolo_mode=True,
    )

    args = session._build_tool_args(["codex"], resume=True)

    assert args == [
        "codex",
        "--dangerously-bypass-approvals-and-sandbox",
        "--cd",
        str(tmp_path.resolve()),
        "resume",
        "codex-session",
    ]


def test_claude_yolo_launch_adds_skip_permissions_flag(tmp_path: Path) -> None:
    session = PtySession(
        work_dir=str(tmp_path),
        tool="claude",
        resume_token="claude-session",
        yolo_mode=True,
    )

    args = session._build_tool_args(["claude"], resume=False)

    assert args == [
        "claude",
        "--dangerously-skip-permissions",
        "--session-id",
        "claude-session",
    ]


def test_claude_yolo_resume_adds_skip_permissions_flag(tmp_path: Path) -> None:
    session = PtySession(
        work_dir=str(tmp_path),
        tool="claude",
        resume_token="claude-session",
        yolo_mode=True,
    )

    args = session._build_tool_args(["claude"], resume=True)

    assert args == [
        "claude",
        "--dangerously-skip-permissions",
        "--resume",
        "claude-session",
    ]


def test_codex_initial_launch_can_attach_image_and_prompt(tmp_path: Path) -> None:
    image_path = tmp_path / "screenshot.png"
    session = PtySession(work_dir=str(tmp_path), tool="codex")

    args = session._build_tool_args(
        ["codex"],
        resume=False,
        image_paths=[image_path],
        prompt="Use this screenshot",
    )

    assert args == [
        "codex",
        "--cd",
        str(tmp_path.resolve()),
        "--image",
        str(image_path),
        "Use this screenshot",
    ]


def test_codex_resume_launch_can_attach_image_and_prompt(tmp_path: Path) -> None:
    image_path = tmp_path / "screenshot.png"
    session = PtySession(
        work_dir=str(tmp_path),
        tool="codex",
        resume_token="codex-session",
    )

    args = session._build_tool_args(
        ["codex"],
        resume=True,
        image_paths=[image_path],
        prompt="Use this screenshot",
    )

    assert args == [
        "codex",
        "--cd",
        str(tmp_path.resolve()),
        "resume",
        "--image",
        str(image_path),
        "codex-session",
        "Use this screenshot",
    ]


def test_non_codex_session_rejects_image_attach(tmp_path: Path) -> None:
    async def run() -> None:
        session = PtySession(work_dir=str(tmp_path), tool="bash")

        with pytest.raises(ValueError, match="Codex"):
            await session.send_image_to_codex(
                image_path=tmp_path / "screenshot.png",
                prompt="Use this screenshot",
            )

    asyncio.run(run())


def test_codex_hook_config_runs_hf_agent_ui_hook() -> None:
    config_args = _codex_hook_config_args()

    assert "features.hooks=true" in config_args
    assert any("hf_agent_ui.daemon.codex_hook" in arg for arg in config_args)


def test_claude_input_hook_install_replaces_notification_hook(tmp_path: Path) -> None:
    command = f"{shlex.quote(sys.executable)} -m hf_agent_ui.daemon.claude_hook"
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    settings_file = settings_dir / "settings.local.json"
    settings_file.write_text(json.dumps({
        "hooks": {
            "Notification": [
                {
                    "hooks": [
                        {"type": "command", "command": command},
                        {"type": "command", "command": "echo keep"},
                    ],
                },
                {
                    "matcher": "idle_prompt",
                    "hooks": [{"type": "command", "command": command}],
                },
            ],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo policy"}]},
            ],
        },
    }))
    session = PtySession(work_dir=str(tmp_path), tool="claude")

    session._install_claude_input_hooks()

    hooks = json.loads(settings_file.read_text())["hooks"]
    assert "Notification" in hooks
    assert hooks["Notification"] == [{"hooks": [{"type": "command", "command": "echo keep"}]}]
    assert hooks["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo policy"}]},
    ]
    for event_name in ("PermissionRequest", "Elicitation"):
        assert any(
            hook.get("command") == command
            for group in hooks[event_name]
            for hook in group["hooks"]
        )


def test_claude_permission_request_maps_to_input_signal() -> None:
    signal = _detect_claude_input_hook({
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {
            "description": "Run tests outside the sandbox",
            "command": "pytest",
        },
    })

    assert signal is not None
    assert signal.kind == "permission"
    assert signal.title == "Claude approval required"
    assert signal.reason == "Run tests outside the sandbox"
    assert signal.tool_name == "Bash"


def test_claude_elicitation_maps_to_prompt_signal() -> None:
    signal = _detect_claude_input_hook({
        "hook_event_name": "Elicitation",
        "server_name": "docs",
        "request": {
            "title": "Choose source",
            "question": "Which documentation source should Claude use?",
        },
    })

    assert signal is not None
    assert signal.kind == "prompt"
    assert signal.title == "Choose source"
    assert signal.reason == "Which documentation source should Claude use?"
    assert signal.tool_name == "docs"


def test_claude_idle_notification_is_ignored() -> None:
    event = {
        "hook_event_name": "Notification",
        "notification_type": "idle_prompt",
        "message": "Claude is waiting for your input",
    }

    assert _detect_claude_notification(event) is None
    assert _detect_claude_input_hook(event) is None


def test_codex_permission_request_maps_to_input_signal() -> None:
    signal = _detect_codex_permission_request({
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {
            "description": "Run tests outside the sandbox",
            "command": "pytest",
        },
    })

    assert signal.kind == "permission"
    assert signal.title == "Codex approval required"
    assert signal.reason == "Run tests outside the sandbox"
    assert signal.tool_name == "Bash"


def test_pty_action_required_ignores_hooked_tools() -> None:
    output = "Claude needs your permission to use Bash\n"

    assert _detect_action_required(output, "claude") is None
    assert _detect_action_required(output, "codex") is None


def test_pty_action_required_keeps_non_hook_fallback() -> None:
    signal = _detect_action_required("Claude needs your permission to use Bash\n", "mock")

    assert signal is not None
    assert signal.kind == "permission"
    assert signal.title == "Permission required"


def test_pty_action_required_ignores_broad_non_prompt_text() -> None:
    output = "This README explains approve flows, login setup, and y/n examples for users.\n"

    assert _detect_action_required(output, "mock") is None


def test_terminate_process_targets_process_group(monkeypatch, tmp_path: Path) -> None:
    class FakeProc:
        pid = 123

        def poll(self):
            return None

    calls = []
    session = PtySession(work_dir=str(tmp_path), tool="mock")
    session._proc = FakeProc()

    monkeypatch.setattr(os, "getpgid", lambda pid: 456)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))

    session._terminate_process()

    assert calls == [(456, signal.SIGTERM)]
