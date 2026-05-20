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
    managed: bool = True


@dataclass(frozen=True)
class PreparedWorktree:
    work_dir: str
    metadata: WorktreeMetadata


@dataclass(frozen=True)
class WorktreeListItem:
    source_dir: str
    repo_root: str
    worktree_root: str
    work_dir: str
    branch: str
    start_point: str
    available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class WorktreeSource:
    source_path: Path
    repo_root: Path
    relative_source: Path


def prepare_worktree(request: Mapping[str, Any], fallback_source_dir: str) -> PreparedWorktree:
    mode = _string_field(request.get("mode")) or "create"
    if mode == "existing":
        return attach_existing_worktree(request, fallback_source_dir=fallback_source_dir)
    if mode != "create":
        raise WorktreeError(f"Unknown worktree mode: {mode}")

    source_dir = _string_field(request.get("sourceDir")) or fallback_source_dir
    branch = _string_field(request.get("branch"))
    start_point = _string_field(request.get("startPoint")) or "HEAD"
    if not branch:
        raise WorktreeError("Worktree branch is required")

    source = _worktree_source(source_dir)

    _validate_branch(source.repo_root, branch)
    _ensure_branch_does_not_exist(source.repo_root, branch)

    worktrees_dir = source.repo_root / ".worktrees"
    worktree_root = worktrees_dir / _sanitize_branch_path(branch)
    if worktree_root.exists():
        raise WorktreeError(f"Worktree path already exists: {worktree_root}")

    worktrees_dir.mkdir(exist_ok=True)
    try:
        _git_output(
            ["worktree", "add", "-b", branch, str(worktree_root), start_point],
            cwd=source.repo_root,
        )
    except WorktreeError:
        _cleanup_worktree_path_and_branch(source.repo_root, worktree_root, branch)
        raise

    work_dir = worktree_root / source.relative_source
    return PreparedWorktree(
        work_dir=str(work_dir),
        metadata=WorktreeMetadata(
            source_dir=str(source.source_path),
            repo_root=str(source.repo_root),
            worktree_root=str(worktree_root),
            branch=branch,
            start_point=start_point,
            managed=True,
        ),
    )


def list_existing_worktrees(source_dir: str) -> list[WorktreeListItem]:
    source = _worktree_source(source_dir)
    output = _git_output(["worktree", "list", "--porcelain"], cwd=source.repo_root)
    items: list[WorktreeListItem] = []
    for record in _parse_worktree_list(output):
        worktree_root_value = record.get("worktree")
        if not worktree_root_value:
            continue
        worktree_root = Path(worktree_root_value).resolve()
        if worktree_root == source.repo_root:
            continue

        work_dir = (worktree_root / source.relative_source).resolve()
        branch = _worktree_branch_label(record)
        available = work_dir.is_dir()
        items.append(WorktreeListItem(
            source_dir=str(source.source_path),
            repo_root=str(source.repo_root),
            worktree_root=str(worktree_root),
            work_dir=str(work_dir),
            branch=branch,
            start_point=record.get("HEAD") or branch,
            available=available,
            unavailable_reason=None if available else f"Missing directory: {work_dir}",
        ))
    return items


def attach_existing_worktree(request: Mapping[str, Any], fallback_source_dir: str) -> PreparedWorktree:
    source_dir = _string_field(request.get("sourceDir")) or fallback_source_dir
    requested_root = _string_field(request.get("worktreeRoot"))
    if not requested_root:
        raise WorktreeError("Existing worktree path is required")

    requested_path = Path(os.path.expanduser(requested_root)).resolve()
    for item in list_existing_worktrees(source_dir):
        if Path(item.worktree_root).resolve() != requested_path:
            continue
        if not item.available:
            raise WorktreeError(item.unavailable_reason or f"Worktree directory is not available: {item.work_dir}")
        return PreparedWorktree(
            work_dir=item.work_dir,
            metadata=WorktreeMetadata(
                source_dir=item.source_dir,
                repo_root=item.repo_root,
                worktree_root=item.worktree_root,
                branch=item.branch,
                start_point=item.start_point,
                managed=False,
            ),
        )
    raise WorktreeError(f"Existing worktree is not linked to repository: {requested_root}")


def cleanup_prepared_worktree(metadata: WorktreeMetadata) -> None:
    if not metadata.managed:
        return
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
    managed = value.get("managed")
    if not source_dir or not repo_root or not worktree_root or not branch:
        return None
    return WorktreeMetadata(
        source_dir=source_dir,
        repo_root=repo_root,
        worktree_root=worktree_root,
        branch=branch,
        start_point=start_point,
        managed=managed if isinstance(managed, bool) else True,
    )


def _worktree_source(source_dir: str) -> WorktreeSource:
    source_path = Path(os.path.expanduser(source_dir)).resolve()
    if not source_path.is_dir():
        raise WorktreeError(f"Worktree source directory does not exist: {source_dir}")

    repo_root = Path(_git_output(["rev-parse", "--show-toplevel"], cwd=source_path)).resolve()
    try:
        relative_source = source_path.relative_to(repo_root)
    except ValueError as exc:
        raise WorktreeError(f"Worktree source is not inside Git repository: {source_dir}") from exc
    return WorktreeSource(source_path=source_path, repo_root=repo_root, relative_source=relative_source)


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


def _parse_worktree_list(output: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, separator, value = line.partition(" ")
        current[key] = value if separator else ""
    if current:
        records.append(current)
    return records


def _worktree_branch_label(record: Mapping[str, str]) -> str:
    branch = record.get("branch")
    if branch:
        prefix = "refs/heads/"
        return branch[len(prefix):] if branch.startswith(prefix) else branch
    head = record.get("HEAD", "")
    if "detached" in record and head:
        return f"detached:{head[:7]}"
    return head[:7] if head else "unknown"


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
