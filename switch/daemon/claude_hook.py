"""Claude Code hook entrypoint for Switch PTY sessions."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    session_id = os.environ.get("SWITCH_PTY_SESSION_ID")
    hook_dir = os.environ.get("SWITCH_CLAUDE_HOOK_DIR")
    if not session_id or not hook_dir:
        return 0

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    path = Path(hook_dir) / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
