from __future__ import annotations

import json
from pathlib import Path

from switch.daemon.session_manager import SessionManager


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
