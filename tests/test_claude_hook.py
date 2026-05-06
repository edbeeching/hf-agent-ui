from __future__ import annotations

import io
import json
import sys

from hf_agent_ui.daemon import claude_hook


def test_claude_hook_writes_session_notification(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_PTY_SESSION_ID", "session-123")
    monkeypatch.setenv("HF_AGENT_UI_CLAUDE_HOOK_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "hook_event_name": "Notification",
        "message": "Claude needs your permission to use Bash",
    })))

    assert claude_hook.main() == 0

    lines = (tmp_path / "session-123.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["hook_event_name"] == "Notification"
