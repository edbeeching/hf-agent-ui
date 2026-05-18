from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitStatusInfo:
    branch: str | None
    dirty: bool
    ahead: int | None
    behind: int | None
    is_worktree: bool
    repo_root: str


def git_status_for_path(work_dir: str) -> GitStatusInfo | None:
    path = Path(work_dir).expanduser()
    if not path.is_dir():
        return None

    repo_root = _git_output(["rev-parse", "--show-toplevel"], cwd=path)
    if not repo_root:
        return None

    branch = _git_output(["branch", "--show-current"], cwd=path)
    if not branch:
        short_head = _git_output(["rev-parse", "--short", "HEAD"], cwd=path)
        branch = f"detached:{short_head}" if short_head else None

    status = _git_output(["status", "--porcelain=v1", "--untracked-files=normal"], cwd=path)
    ahead, behind = _ahead_behind(path)
    return GitStatusInfo(
        branch=branch,
        dirty=bool(status),
        ahead=ahead,
        behind=behind,
        is_worktree=_is_worktree(path),
        repo_root=repo_root,
    )


def _ahead_behind(path: Path) -> tuple[int | None, int | None]:
    counts = _git_output(["rev-list", "--left-right", "--count", "@{upstream}...HEAD"], cwd=path)
    if not counts:
        return None, None
    parts = counts.split()
    if len(parts) != 2:
        return None, None
    try:
        behind = int(parts[0])
        ahead = int(parts[1])
    except ValueError:
        return None, None
    return ahead, behind


def _is_worktree(path: Path) -> bool:
    git_dir = _git_output(["rev-parse", "--path-format=absolute", "--git-dir"], cwd=path)
    common_dir = _git_output(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=path)
    return bool(git_dir and common_dir and Path(git_dir).resolve() != Path(common_dir).resolve())


def _git_output(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
