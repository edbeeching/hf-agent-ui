from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Union

from .adapters import get_adapter
from .pty_session import PtySession
from .session import Session, SessionInfo, SessionOptions

logger = logging.getLogger(__name__)

AnySession = Union[Session, PtySession]


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, AnySession] = {}

    def create(self, opts: SessionOptions) -> Session:
        """Create a JSON-mode session. Call session.start() after subscribing."""
        adapter = get_adapter(opts.tool)
        session = Session(opts, adapter)
        self._sessions[session.id] = session
        logger.info("Created session %s in %s", session.id, opts.work_dir)
        return session

    def create_pty(self, work_dir: str, tool: str = "claude", cols: int = 120, rows: int = 40) -> PtySession:
        """Create a PTY-mode session. Call session.start() after subscribing."""
        session = PtySession(work_dir=work_dir, tool=tool, cols=cols, rows=rows)
        self._sessions[session.id] = session
        logger.info("Created PTY session %s (%s) in %s", session.id, tool, work_dir)
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
        return True

    def remove(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        session.stop()
        return True

    def stop_all(self) -> None:
        for session in self._sessions.values():
            session.stop()
