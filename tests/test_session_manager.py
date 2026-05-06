from __future__ import annotations

import json
from pathlib import Path

from hf_agent_ui.daemon.session_manager import SessionManager


def test_session_manager_default_tool_is_codex(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "state.json")

    session = manager.create_pty(str(tmp_path))

    assert session.tool == "codex"
    assert manager.list()[0]["tool"] == "codex"


def test_session_manager_restores_dead_running_pty_as_paused(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "version": 1,
        "sessions": [{
            "kind": "pty",
            "id": "session-1",
            "status": "running",
            "created_at": "2026-04-28T00:00:00+00:00",
            "work_dir": str(tmp_path),
            "tool": "codex",
            "cols": 120,
            "rows": 40,
            "resume_token": "codex-session",
        }],
    }), encoding="utf-8")

    manager = SessionManager(state_path)

    assert manager.list()[0]["status"] == "paused"


def test_session_manager_preserves_stopped_pty_status(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "version": 1,
        "sessions": [{
            "kind": "pty",
            "id": "session-1",
            "status": "stopped",
            "created_at": "2026-04-28T00:00:00+00:00",
            "work_dir": str(tmp_path),
            "tool": "codex",
            "cols": 120,
            "rows": 40,
            "resume_token": "codex-session",
        }],
    }), encoding="utf-8")

    manager = SessionManager(state_path)

    assert manager.list()[0]["status"] == "stopped"


def test_session_manager_persists_custom_launch_metadata(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    session = manager.create_pty(
        str(tmp_path),
        tool="claude",
        launch_mode="custom",
        launch_command="srun --pty --chdir {workDir} {command}",
        launch_label="gpu",
    )

    info = session.to_info()
    assert info.launch_mode == "custom"
    assert info.launch_command == "srun --pty --chdir {workDir} {command}"
    assert info.launch_label == "gpu"

    restored = SessionManager(state_path)

    restored_info = restored.list()[0]
    assert restored_info["launch_mode"] == "custom"
    assert restored_info["launch_command"] == "srun --pty --chdir {workDir} {command}"
    assert restored_info["launch_label"] == "gpu"


def test_session_manager_save_uses_unique_temp_file(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "sessions.json"
    fixed_tmp_path = state_path.with_suffix(".tmp")
    original_replace = Path.replace

    def replace(path: Path, target: Path) -> Path:
        if path == fixed_tmp_path:
            raise AssertionError("session state save used shared fixed temp path")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)

    manager = SessionManager(state_path)
    manager.create_pty(str(tmp_path), tool="claude")

    assert state_path.exists()
    assert not fixed_tmp_path.exists()
    assert list(tmp_path.glob(".sessions.json.*.tmp")) == []
