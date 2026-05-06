from __future__ import annotations

import json
import logging
import os
import tempfile
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

    def create_pty(
        self,
        work_dir: str,
        tool: str = "claude",
        cols: int = 120,
        rows: int = 40,
        launch_mode: str = "local",
        launch_command: str | None = None,
        launch_label: str | None = None,
    ) -> PtySession:
        """Create a PTY session. Call session.start() after subscribing."""
        session = PtySession(
            work_dir=work_dir,
            tool=tool,
            cols=cols,
            rows=rows,
            launch_mode=launch_mode,
            launch_command=launch_command,
            launch_label=launch_label,
        )
        session.on_event(self._persist_on_event)
        self._sessions[session.id] = session
        logger.info("Created PTY session %s (%s) in %s via %s", session.id, tool, work_dir, launch_mode)
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
        tmp_path: Path | None = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "sessions": [session.to_record() for session in self._sessions.values()],
            }
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.state_path.name}.",
                suffix=".tmp",
                dir=self.state_path.parent,
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
            tmp_path.replace(self.state_path)
        except OSError:
            logger.exception("Failed to save session state to %s", self.state_path)
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    logger.debug("Failed to remove temp session state file %s", tmp_path, exc_info=True)

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
                    launch_mode=record.get("launch_mode", "local"),
                    launch_command=record.get("launch_command"),
                    launch_label=record.get("launch_label"),
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
