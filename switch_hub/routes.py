from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class RegisterRequest(BaseModel):
    name: str
    host: str
    port: int
    hostname: str = ""


@router.post("/daemons/register")
async def register_daemon(req: RegisterRequest, request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    pool = request.app.state.pool
    info = registry.register(req.name, req.host, req.port, req.hostname)
    await pool.connect(info)
    return {"id": info.id, "name": info.name}


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
