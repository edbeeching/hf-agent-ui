from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from .pty_session import PtySession

logger = logging.getLogger(__name__)

AnySession = PtySession


class SessionManager:
    def __init__(self, state_path: Path | None = None) -> None:
        self._sessions: dict[str, AnySession] = {}
        self.state_path = state_path or Path.home() / ".switch" / "sessions.json"
        self._load()

    def create_pty(self, work_dir: str, tool: str = "claude", cols: int = 120, rows: int = 40) -> PtySession:
        """Create a PTY session. Call session.start() after subscribing."""
        session = PtySession(work_dir=work_dir, tool=tool, cols=cols, rows=rows)
        session.on_event(self._persist_on_event)
        self._sessions[session.id] = session
        logger.info("Created PTY session %s (%s) in %s", session.id, tool, work_dir)
        self._save()
        return session

    def get(self, session_id: str) -> AnySession | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict]:
        results = []
        for s in self._sessions.values():
            info = s.to_info()
            results.append(asdict(info))
        return results

    def stop(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.stop()
        self._save()
        return True

    def pause(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.pause()
        self._save()
        return True

    async def resume(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        await session.resume()
        self._save()
        return True

    def remove(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        session.stop()
        self._save()
        return True

    def stop_all(self) -> None:
        for session in self._sessions.values():
            session.stop()
        self._save()

    def pause_all(self) -> None:
        for session in self._sessions.values():
            session.pause()
        self._save()

    async def resume_all(self) -> None:
        for session in self._sessions.values():
            if session.status == "paused":
                await session.resume()
        self._save()

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "sessions": [session.to_record() for session in self._sessions.values()],
            }
            tmp_path = self.state_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self.state_path)
        except OSError:
            logger.exception("Failed to save session state to %s", self.state_path)

    def _load(self) -> None:
        try:
            if not self.state_path.exists():
                return
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load session state from %s", self.state_path)
            return

        for record in payload.get("sessions", []):
            try:
                if record.get("kind") != "pty":
                    continue
                session = PtySession(
                    work_dir=record.get("work_dir", "."),
                    tool=record.get("tool", "claude"),
                    cols=record.get("cols", 120),
                    rows=record.get("rows", 40),
                    session_id=record.get("id"),
                    created_at=record.get("created_at"),
                    status=self._restore_status(record.get("status")),
                    resume_token=record.get("resume_token"),
                )
                session.on_event(self._persist_on_event)
                self._sessions[session.id] = session
            except Exception:
                logger.exception("Failed to restore session record: %s", record)

    async def _persist_on_event(self, _event: dict) -> None:
        self._save()

    @staticmethod
    def _restore_status(status: object) -> str:
        if status == "stopped":
            return "stopped"
        if status == "error":
            return "error"
        return "paused"
