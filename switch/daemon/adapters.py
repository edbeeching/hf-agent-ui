from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from .session import SessionOptions


class ToolAdapter(ABC):
    """Protocol for wrapping different AI coding CLI tools."""

    name: str

    @abstractmethod
    def build_start_args(self, opts: SessionOptions, initial_prompt: str | None = None) -> list[str]:
        """Return the full command + args to spawn the process."""

    @abstractmethod
    def format_user_message(self, message: str) -> str | None:
        """Format a user message for stdin. Return None if stdin messaging not supported."""

    @abstractmethod
    def format_control_response(self, response: dict[str, Any]) -> str | None:
        """Format a tool approval response for stdin. Return None if not supported."""

    @abstractmethod
    def parse_output_line(self, line: str) -> dict[str, Any] | None:
        """Parse an NDJSON line into an event dict. Return None to skip the line."""

    @abstractmethod
    def supports_stdin_messages(self) -> bool:
        """Whether the tool supports ongoing messages via stdin."""

    @abstractmethod
    def build_resume_args(self, codex_session_id: str, message: str, opts: SessionOptions) -> list[str]:
        """For tools that don't support stdin messages, build args to resume with a new message."""


class ClaudeAdapter(ToolAdapter):
    name = "claude"

    def build_start_args(self, opts: SessionOptions, initial_prompt: str | None = None) -> list[str]:
        args = [
            "claude",
            "--print",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
        ]
        if opts.model:
            args.extend(["--model", opts.model])
        if opts.permission_mode:
            args.extend(["--permission-mode", opts.permission_mode])
        if opts.allowed_tools:
            args.extend(["--allowedTools", *opts.allowed_tools])
        if opts.system_prompt:
            args.extend(["--system-prompt", opts.system_prompt])
        return args

    def format_user_message(self, message: str) -> str | None:
        return json.dumps({"type": "user_message", "content": message})

    def format_control_response(self, response: dict[str, Any]) -> str | None:
        return json.dumps(response)

    def parse_output_line(self, line: str) -> dict[str, Any] | None:
        if not line.strip():
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"type": "raw", "text": line}

    def supports_stdin_messages(self) -> bool:
        return True

    def build_resume_args(self, codex_session_id: str, message: str, opts: SessionOptions) -> list[str]:
        # Claude doesn't need this — it supports stdin messages
        raise NotImplementedError("Claude supports stdin messages; resume not needed")


class CodexAdapter(ToolAdapter):
    name = "codex"

    def build_start_args(self, opts: SessionOptions, initial_prompt: str | None = None) -> list[str]:
        args = [
            "codex", "exec",
            "--json",
        ]
        if opts.model:
            args.extend(["--model", opts.model])
        if opts.permission_mode:
            # Map generic permission modes to Codex's --ask-for-approval
            mode_map = {
                "auto": "never",
                "bypassPermissions": "never",
                "acceptEdits": "on-request",
                "default": "untrusted",
            }
            codex_mode = mode_map.get(opts.permission_mode, opts.permission_mode)
            args.extend(["--ask-for-approval", codex_mode])
        if opts.work_dir:
            args.extend(["--cd", opts.work_dir])
        # The prompt must be the last argument
        if initial_prompt:
            args.append(initial_prompt)
        return args

    def format_user_message(self, message: str) -> str | None:
        # Codex exec doesn't support ongoing stdin messages
        return None

    def format_control_response(self, response: dict[str, Any]) -> str | None:
        # Codex exec doesn't support control responses via stdin
        return None

    def parse_output_line(self, line: str) -> dict[str, Any] | None:
        if not line.strip():
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"type": "raw", "text": line}

    def supports_stdin_messages(self) -> bool:
        return False

    def build_resume_args(self, codex_session_id: str, message: str, opts: SessionOptions) -> list[str]:
        args = [
            "codex", "exec",
            "--json",
        ]
        if opts.model:
            args.extend(["--model", opts.model])
        if opts.permission_mode:
            mode_map = {
                "auto": "never",
                "bypassPermissions": "never",
                "acceptEdits": "on-request",
                "default": "untrusted",
            }
            codex_mode = mode_map.get(opts.permission_mode, opts.permission_mode)
            args.extend(["--ask-for-approval", codex_mode])
        if opts.work_dir:
            args.extend(["--cd", opts.work_dir])
        args.extend(["resume", codex_session_id])
        # Append the follow-up message
        args.append(message)
        return args


ADAPTERS: dict[str, type[ToolAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
}


def get_adapter(tool: str) -> ToolAdapter:
    cls = ADAPTERS.get(tool)
    if not cls:
        raise ValueError(f"Unknown tool: {tool}. Available: {list(ADAPTERS.keys())}")
    return cls()
