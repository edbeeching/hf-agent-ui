from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .security import SINGLE_USER_NAME, SINGLE_USER_SUB, UserIdentity

logger = logging.getLogger(__name__)

PRUNE_TIMEOUT_SECONDS = 45


@dataclass
class DaemonInfo:
    id: str
    name: str
    host: str
    port: int
    hostname: str
    registered_at: str
    last_seen: str
    owner_sub: str = SINGLE_USER_SUB
    owner_username: str = SINGLE_USER_NAME

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "hostname": self.hostname,
            "registeredAt": self.registered_at,
            "lastSeen": self.last_seen,
        }


class DaemonRegistry:
    def __init__(self) -> None:
        self._daemons: dict[str, DaemonInfo] = {}
        self._prune_task: asyncio.Task | None = None

    def register(
        self,
        name: str,
        host: str,
        port: int,
        hostname: str,
        owner: UserIdentity | None = None,
    ) -> DaemonInfo:
        owner = owner or UserIdentity(
            sub=SINGLE_USER_SUB,
            username=SINGLE_USER_NAME,
            display_name=SINGLE_USER_NAME,
        )
        # Check if a daemon with the same name already exists — update it
        for d in self._daemons.values():
            if d.name == name and d.owner_sub == owner.sub:
                now = datetime.now(timezone.utc).isoformat()
                d.host = host
                d.port = port
                d.hostname = hostname
                d.last_seen = now
                logger.info("Re-registered daemon %s (id=%s)", name, d.id)
                return d

        daemon_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        info = DaemonInfo(
            id=daemon_id,
            name=name,
            host=host,
            port=port,
            hostname=hostname,
            registered_at=now,
            last_seen=now,
            owner_sub=owner.sub,
            owner_username=owner.username,
        )
        self._daemons[daemon_id] = info
        logger.info("Registered new daemon %s (id=%s) at %s:%d", name, daemon_id, host, port)
        return info

    def heartbeat(self, daemon_id: str) -> bool:
        daemon = self._daemons.get(daemon_id)
        if not daemon:
            return False
        daemon.last_seen = datetime.now(timezone.utc).isoformat()
        return True

    def get(self, daemon_id: str) -> DaemonInfo | None:
        return self._daemons.get(daemon_id)

    def list(self, owner_sub: str | None = None) -> list[dict[str, Any]]:
        return [
            d.to_dict()
            for d in self._daemons.values()
            if owner_sub is None or d.owner_sub == owner_sub
        ]

    def owns(self, daemon_id: str, owner_sub: str) -> bool:
        daemon = self._daemons.get(daemon_id)
        return daemon is not None and daemon.owner_sub == owner_sub

    def remove(self, daemon_id: str) -> bool:
        return self._daemons.pop(daemon_id, None) is not None

    def prune(self) -> list[str]:
        now = datetime.now(timezone.utc)
        to_remove = []
        for daemon_id, info in self._daemons.items():
            last_seen = datetime.fromisoformat(info.last_seen)
            if (now - last_seen).total_seconds() > PRUNE_TIMEOUT_SECONDS:
                to_remove.append(daemon_id)

        for daemon_id in to_remove:
            name = self._daemons[daemon_id].name
            del self._daemons[daemon_id]
            logger.info("Pruned stale daemon %s (id=%s)", name, daemon_id)

        return to_remove

    async def start_prune_loop(self, interval: float = 30.0) -> None:
        self._prune_task = asyncio.create_task(self._prune_loop(interval))

    async def _prune_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            self.prune()

    def stop(self) -> None:
        if self._prune_task:
            self._prune_task.cancel()
