from __future__ import annotations

import logging
from dataclasses import asdict

from .adapters import get_adapter
from .session import Session, SessionInfo, SessionOptions

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create(self, opts: SessionOptions) -> Session:
        adapter = get_adapter(opts.tool)
        session = Session(opts, adapter)
        self._sessions[session.id] = session
        await session.start()
        logger.info("Created session %s in %s", session.id, opts.work_dir)
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict]:
        return [asdict(s.to_info()) for s in self._sessions.values()]

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
