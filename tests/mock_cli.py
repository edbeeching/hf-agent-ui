"""Mock CLI that simulates Claude's stream-json protocol.

Reads NDJSON from stdin, writes NDJSON to stdout.
Used by tests instead of the real claude/codex binary.
"""
import json
import sys


def main() -> None:
    # Emit a system/init event on startup
    emit({"type": "system", "subtype": "init", "model": "mock-model", "session_id": "mock-session-123"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "user_message":
            content = msg.get("content", "")
            # Echo back as a stream_event with content_block_delta
            emit({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"text": f"echo: {content}"},
                },
            })
            # Then a result
            emit({"type": "result", "session_id": "mock-session-123", "text": f"echo: {content}"})


def emit(data: dict) -> None:
    sys.stdout.write(json.dumps(data) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
