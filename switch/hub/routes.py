from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


@router.get("/hub")
async def hub_info(request: Request) -> dict[str, Any]:
    daemon_hub_url = os.environ.get("SWITCH_HUB_DAEMON_URL")
    daemon_token = os.environ.get("SWITCH_DAEMON_TOKEN")
    if not daemon_hub_url:
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_proto and forwarded_host:
            daemon_hub_url = f"{forwarded_proto}://{forwarded_host}"
        else:
            daemon_hub_url = str(request.base_url).rstrip("/")
        if daemon_hub_url.startswith("http://") and request.headers.get("host", "").endswith(".hf.space"):
            daemon_hub_url = daemon_hub_url.replace("http://", "https://", 1)
    payload: dict[str, Any] = {
        "daemonHubUrl": daemon_hub_url,
        "daemonTokenRequired": bool(daemon_token),
    }
    if daemon_token and os.environ.get("SWITCH_EXPOSE_DAEMON_TOKEN") == "1":
        payload["daemonToken"] = daemon_token
    return payload


class RegisterRequest(BaseModel):
    name: str
    host: str
    port: int
    hostname: str = ""


@router.post("/daemons/register")
async def register_daemon(req: RegisterRequest, request: Request) -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail="HTTP daemon registration is no longer supported; use /daemon/ws",
    )


@router.post("/daemons/{daemon_id}/heartbeat")
async def heartbeat(daemon_id: str, request: Request) -> dict[str, str]:
    registry = request.app.state.registry
    if not registry.heartbeat(daemon_id):
        raise HTTPException(status_code=404, detail="Daemon not found")
    return {"status": "ok"}


@router.get("/daemons")
async def list_daemons(request: Request) -> list[dict[str, Any]]:
    registry = request.app.state.registry
    pool = request.app.state.pool
    daemons = registry.list()
    for d in daemons:
        d["connected"] = pool.is_connected(d["id"])
    return daemons
