from __future__ import annotations

import asyncio
import logging
import platform

import httpx

logger = logging.getLogger(__name__)


class HubRegistration:
    """Registers with the hub and sends periodic heartbeats."""

    def __init__(
        self,
        hub_url: str,
        daemon_name: str,
        daemon_port: int,
        daemon_host: str = "0.0.0.0",
    ) -> None:
        self.hub_url = hub_url.rstrip("/")
        self.daemon_name = daemon_name
        self.daemon_port = daemon_port
        self.daemon_host = daemon_host
        self.daemon_id: str | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._client = httpx.AsyncClient(timeout=10)

    async def register(self) -> str | None:
        try:
            resp = await self._client.post(
                f"{self.hub_url}/api/daemons/register",
                json={
                    "name": self.daemon_name,
                    "host": self.daemon_host,
                    "port": self.daemon_port,
                    "hostname": platform.node(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self.daemon_id = data["id"]
            logger.info("Registered with hub as %s (id=%s)", self.daemon_name, self.daemon_id)
            return self.daemon_id
        except Exception:
            logger.exception("Failed to register with hub at %s", self.hub_url)
            return None

    async def start_heartbeat(self, interval: float = 30.0) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval))

    async def _heartbeat_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            if not self.daemon_id:
                # Try to re-register
                await self.register()
                continue
            try:
                resp = await self._client.post(
                    f"{self.hub_url}/api/daemons/{self.daemon_id}/heartbeat",
                )
                if resp.status_code == 404:
                    # Hub doesn't know us anymore, re-register
                    logger.warning("Hub lost our registration, re-registering...")
                    await self.register()
                else:
                    resp.raise_for_status()
            except Exception:
                logger.warning("Heartbeat failed, will retry")

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await self._client.aclose()
