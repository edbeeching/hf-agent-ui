from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from hf_agent_ui.daemon import worktrees as worktrees_module
from hf_agent_ui.daemon.session_manager import SessionManager
from hf_agent_ui.daemon.worktrees import WorktreeError, list_existing_worktrees


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


def test_session_manager_persists_yolo_mode_for_agent_tools(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    session = manager.create_pty(str(tmp_path), tool="codex", yolo_mode=True)

    assert session.to_info().yolo_mode is True

    restored = SessionManager(state_path)

    assert restored.list()[0]["yolo_mode"] is True


def test_session_manager_ignores_yolo_mode_for_bash(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    session = manager.create_pty(str(tmp_path), tool="bash", yolo_mode=True)

    assert session.to_info().yolo_mode is False
    assert manager.list()[0]["yolo_mode"] is False


def test_session_manager_persists_label_and_seen_metadata(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    session = manager.create_pty(str(tmp_path), tool="bash")
    assert manager.rename(session.id, "Review server logs")
    assert manager.mark_seen(session.id)

    restored = SessionManager(state_path)
    restored_info = restored.list()[0]
    assert restored_info["label"] == "Review server logs"
    assert restored_info["last_seen_at"] is not None
    assert restored_info["agent_state"] == "idle"


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
    assert session.worktree.managed is True
    assert _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/agent/test-session").returncode == 0


def test_list_existing_worktrees_excludes_source_and_computes_work_dir(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    existing_root = repo / ".worktrees" / "feature-existing"
    _git(repo, "worktree", "add", "-b", "feature/existing", str(existing_root), "HEAD", check=True)

    worktrees = list_existing_worktrees(str(source_dir))

    assert len(worktrees) == 1
    item = worktrees[0]
    assert item.source_dir == str(source_dir.resolve())
    assert item.repo_root == str(repo.resolve())
    assert item.worktree_root == str(existing_root.resolve())
    assert item.work_dir == str((existing_root / "app").resolve())
    assert item.branch == "feature/existing"
    assert item.available is True
    assert item.unavailable_reason is None


def test_list_existing_worktrees_marks_prunable_worktree_unavailable(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    existing_root = repo / ".worktrees" / "feature-prunable"
    _git(repo, "worktree", "add", "-b", "feature/prunable", str(existing_root), "HEAD", check=True)
    shutil.rmtree(existing_root)
    (existing_root / "app").mkdir(parents=True)

    worktrees = list_existing_worktrees(str(source_dir))

    item = next(worktree for worktree in worktrees if worktree.branch == "feature/prunable")
    assert item.available is False
    assert item.unavailable_reason is not None
    assert "prunable" in item.unavailable_reason.lower()


def test_session_manager_attaches_existing_worktree_without_managing_it(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    existing_root = repo / ".worktrees" / "feature-attach"
    _git(repo, "worktree", "add", "-b", "feature/attach", str(existing_root), "HEAD", check=True)
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    session = manager.create_pty(
        str(source_dir),
        tool="bash",
        worktree={
            "enabled": True,
            "mode": "existing",
            "sourceDir": str(source_dir),
            "worktreeRoot": str(existing_root),
        },
    )

    assert session.work_dir == str((existing_root / "app").resolve())
    assert session.worktree is not None
    assert session.worktree.branch == "feature/attach"
    assert session.worktree.managed is False
    assert Path(session.work_dir).is_dir()


def test_session_manager_rejects_prunable_existing_worktree(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    existing_root = repo / ".worktrees" / "feature-stale"
    _git(repo, "worktree", "add", "-b", "feature/stale", str(existing_root), "HEAD", check=True)
    shutil.rmtree(existing_root)
    (existing_root / "app").mkdir(parents=True)
    manager = SessionManager(tmp_path / "state.json")

    with pytest.raises(WorktreeError, match="Prunable worktree"):
        manager.create_pty(
            str(source_dir),
            tool="bash",
            worktree={
                "enabled": True,
                "mode": "existing",
                "sourceDir": str(source_dir),
                "worktreeRoot": str(existing_root),
            },
        )

    assert manager.list() == []


def test_session_manager_does_not_cleanup_attached_worktree_when_construction_fails(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    existing_root = repo / ".worktrees" / "feature-keep"
    _git(repo, "worktree", "add", "-b", "feature/keep", str(existing_root), "HEAD", check=True)
    state_path = tmp_path / "state.json"
    manager = SessionManager(state_path)

    with pytest.raises(ValueError, match="Unknown launch mode"):
        manager.create_pty(
            str(source_dir),
            tool="bash",
            launch_mode="invalid",
            worktree={
                "enabled": True,
                "mode": "existing",
                "sourceDir": str(source_dir),
                "worktreeRoot": str(existing_root),
            },
        )

    assert existing_root.is_dir()
    assert _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/feature/keep").returncode == 0
    assert manager.list() == []


def test_managed_worktree_create_is_serialized(monkeypatch, tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "app"
    original_git_output = worktrees_module._git_output
    active_adds = 0
    max_active_adds = 0
    active_lock = threading.Lock()

    def slow_git_output(args: list[str], *, cwd: Path) -> str:
        nonlocal active_adds, max_active_adds
        if args[:2] == ["worktree", "add"]:
            with active_lock:
                active_adds += 1
                max_active_adds = max(max_active_adds, active_adds)
            try:
                time.sleep(0.2)
                return original_git_output(args, cwd=cwd)
            finally:
                with active_lock:
                    active_adds -= 1
        return original_git_output(args, cwd=cwd)

    monkeypatch.setattr(worktrees_module, "_git_output", slow_git_output)

    def create(state_name: str) -> object:
        manager = SessionManager(tmp_path / state_name)
        return manager.create_pty(
            str(source_dir),
            tool="bash",
            worktree={
                "enabled": True,
                "sourceDir": str(source_dir),
                "branch": "agent/serialized",
                "startPoint": "HEAD",
            },
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(create, "state-a.json"),
            executor.submit(create, "state-b.json"),
        ]
        results: list[object] = []
        errors: list[BaseException] = []
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except BaseException as exc:
                errors.append(exc)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], WorktreeError)
    assert max_active_adds == 1
    assert (repo / ".worktrees" / "agent-serialized").is_dir()
    assert _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/agent/serialized").returncode == 0


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
