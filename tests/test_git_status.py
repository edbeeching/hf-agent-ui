from __future__ import annotations

import subprocess
from pathlib import Path

from hf_agent_ui.daemon.git_status import git_status_for_path


def test_git_status_for_path_reports_branch_and_dirty_state(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")

    clean = git_status_for_path(str(repo))
    assert clean is not None
    assert clean.branch
    assert clean.dirty is False
    assert clean.ahead is None
    assert clean.behind is None
    assert clean.is_worktree is False

    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    dirty = git_status_for_path(str(repo))
    assert dirty is not None
    assert dirty.dirty is True


def test_git_status_for_path_returns_none_for_non_git_dir(tmp_path: Path) -> None:
    assert git_status_for_path(str(tmp_path)) is None


def test_git_status_for_path_detects_worktree(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    worktree = repo / ".worktrees" / "agent-test"
    _git(repo, "worktree", "add", "-b", "agent/test", str(worktree), "HEAD", check=True)

    status = git_status_for_path(str(worktree))

    assert status is not None
    assert status.branch == "agent/test"
    assert status.is_worktree is True


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
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
