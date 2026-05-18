from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class WorktreeError(ValueError):
    """Raised when a requested Git worktree cannot be prepared."""


@dataclass(frozen=True)
class WorktreeMetadata:
    source_dir: str
    repo_root: str
    worktree_root: str
    branch: str
    start_point: str


@dataclass(frozen=True)
class PreparedWorktree:
    work_dir: str
    metadata: WorktreeMetadata


def prepare_worktree(request: Mapping[str, Any], fallback_source_dir: str) -> PreparedWorktree:
    source_dir = _string_field(request.get("sourceDir")) or fallback_source_dir
    branch = _string_field(request.get("branch"))
    start_point = _string_field(request.get("startPoint")) or "HEAD"
    if not branch:
        raise WorktreeError("Worktree branch is required")

    source_path = Path(os.path.expanduser(source_dir)).resolve()
    if not source_path.is_dir():
        raise WorktreeError(f"Worktree source directory does not exist: {source_dir}")

    repo_root = Path(_git_output(["rev-parse", "--show-toplevel"], cwd=source_path)).resolve()
    try:
        relative_source = source_path.relative_to(repo_root)
    except ValueError as exc:
        raise WorktreeError(f"Worktree source is not inside Git repository: {source_dir}") from exc

    _validate_branch(repo_root, branch)
    _ensure_branch_does_not_exist(repo_root, branch)

    worktrees_dir = repo_root / ".worktrees"
    worktree_root = worktrees_dir / _sanitize_branch_path(branch)
    if worktree_root.exists():
        raise WorktreeError(f"Worktree path already exists: {worktree_root}")

    worktrees_dir.mkdir(exist_ok=True)
    try:
        _git_output(
            ["worktree", "add", "-b", branch, str(worktree_root), start_point],
            cwd=repo_root,
        )
    except WorktreeError:
        _cleanup_worktree_path_and_branch(repo_root, worktree_root, branch)
        raise

    work_dir = worktree_root / relative_source
    return PreparedWorktree(
        work_dir=str(work_dir),
        metadata=WorktreeMetadata(
            source_dir=str(source_path),
            repo_root=str(repo_root),
            worktree_root=str(worktree_root),
            branch=branch,
            start_point=start_point,
        ),
    )


def cleanup_prepared_worktree(metadata: WorktreeMetadata) -> None:
    repo_root = Path(metadata.repo_root).resolve()
    worktree_root = Path(metadata.worktree_root).resolve()
    _cleanup_worktree_path_and_branch(repo_root, worktree_root, metadata.branch)


def worktree_metadata_from_record(value: object) -> WorktreeMetadata | None:
    if not isinstance(value, dict):
        return None
    source_dir = _string_field(value.get("source_dir"))
    repo_root = _string_field(value.get("repo_root"))
    worktree_root = _string_field(value.get("worktree_root"))
    branch = _string_field(value.get("branch"))
    start_point = _string_field(value.get("start_point")) or "HEAD"
    if not source_dir or not repo_root or not worktree_root or not branch:
        return None
    return WorktreeMetadata(
        source_dir=source_dir,
        repo_root=repo_root,
        worktree_root=worktree_root,
        branch=branch,
        start_point=start_point,
    )


def _validate_branch(repo_root: Path, branch: str) -> None:
    try:
        _git_output(["check-ref-format", "--branch", branch], cwd=repo_root)
    except WorktreeError as exc:
        raise WorktreeError(f"Invalid worktree branch: {branch}") from exc


def _ensure_branch_does_not_exist(repo_root: Path, branch: str) -> None:
    result = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_root)
    if result.returncode == 0:
        raise WorktreeError(f"Git branch already exists: {branch}")
    if result.returncode != 1:
        raise WorktreeError(_git_error_message(result) or f"Could not check Git branch: {branch}")


def _cleanup_worktree_path_and_branch(repo_root: Path, worktree_root: Path, branch: str) -> None:
    _ensure_safe_worktree_path(repo_root, worktree_root)
    remove_result = _git(["worktree", "remove", "--force", str(worktree_root)], cwd=repo_root)
    if remove_result.returncode != 0 and worktree_root.exists():
        raise WorktreeError(_git_error_message(remove_result) or f"Could not remove worktree: {worktree_root}")

    branch_result = _git(["branch", "-D", branch], cwd=repo_root)
    if branch_result.returncode != 0 and _branch_exists(repo_root, branch):
        raise WorktreeError(_git_error_message(branch_result) or f"Could not delete Git branch: {branch}")


def _ensure_safe_worktree_path(repo_root: Path, worktree_root: Path) -> None:
    worktrees_dir = (repo_root / ".worktrees").resolve()
    try:
        worktree_root.relative_to(worktrees_dir)
    except ValueError as exc:
        raise WorktreeError(f"Refusing to clean up worktree outside {worktrees_dir}: {worktree_root}") from exc


def _branch_exists(repo_root: Path, branch: str) -> bool:
    result = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_root)
    return result.returncode == 0


def _sanitize_branch_path(branch: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", branch.replace("/", "-")).strip(".-")
    return sanitized or "worktree"


def _string_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _git_output(args: list[str], *, cwd: Path) -> str:
    result = _git(args, cwd=cwd)
    if result.returncode != 0:
        raise WorktreeError(_git_error_message(result) or f"Git command failed: {' '.join(args)}")
    return result.stdout.strip()


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise WorktreeError("Git is not installed on the agent host") from exc


def _git_error_message(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip()
