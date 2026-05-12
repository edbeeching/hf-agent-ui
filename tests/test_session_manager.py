from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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


def test_session_manager_creates_worktree_session(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    session = manager.create_pty(
        str(source_dir),
        tool="bash",
        worktree={
            "enabled": True,
            "sourceDir": str(source_dir),
            "branch": "agent/test-session",
            "startPoint": "HEAD",
        },
    )

    assert session.work_dir == str(repo / ".worktrees" / "agent-test-session" / "app")
    assert Path(session.work_dir).is_dir()
    assert session.worktree is not None
    assert session.worktree.branch == "agent/test-session"
    assert _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/agent/test-session").returncode == 0


def test_session_manager_cleans_up_worktree_when_session_construction_fails(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    with pytest.raises(ValueError, match="Unknown launch mode"):
        manager.create_pty(
            str(source_dir),
            tool="bash",
            launch_mode="invalid",
            worktree={
                "enabled": True,
                "sourceDir": str(source_dir),
                "branch": "agent/fails-before-start",
                "startPoint": "HEAD",
            },
        )

    assert not (repo / ".worktrees" / "agent-fails-before-start").exists()
    assert _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/agent/fails-before-start").returncode == 1
    assert manager.list() == []


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


def _init_git_repo(path: Path) -> Path:
    source_dir = path / "app"
    source_dir.mkdir(parents=True)
    (source_dir / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "init", check=True)
    _git(path, "config", "user.email", "test@example.com", check=True)
    _git(path, "config", "user.name", "Test User", check=True)
    _git(path, "add", ".", check=True)
    _git(path, "commit", "-m", "initial", check=True)
    return path


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )
