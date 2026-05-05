from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .security import UI_TOKEN_COOKIE, UI_TOKEN_ENV, require_browser_http, should_expose_host_token

router = APIRouter(prefix="/api", dependencies=[Depends(require_browser_http)])


def _is_https_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return forwarded_proto == "https" or request.url.scheme == "https"


@router.post("/auth/browser-cookie")
async def set_browser_auth_cookie(request: Request, response: Response) -> dict[str, bool]:
    ui_token = os.environ.get(UI_TOKEN_ENV)
    if not ui_token:
        response.delete_cookie(UI_TOKEN_COOKIE, path="/")
        return {"cookie": False}

    response.set_cookie(
        UI_TOKEN_COOKIE,
        ui_token,
        httponly=True,
        secure=_is_https_request(request),
        samesite="lax",
        path="/",
    )
    return {"cookie": True}


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
    if daemon_token and should_expose_host_token():
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
        detail="HTTP agent host registration is no longer supported; use /daemon/ws",
    )


@router.post("/daemons/{daemon_id}/heartbeat")
async def heartbeat(daemon_id: str, request: Request) -> dict[str, str]:
    registry = request.app.state.registry
    if not registry.heartbeat(daemon_id):
        raise HTTPException(status_code=404, detail="Agent host not found")
    return {"status": "ok"}


@router.get("/daemons")
async def list_daemons(request: Request) -> list[dict[str, Any]]:
    registry = request.app.state.registry
    pool = request.app.state.pool
    daemons = registry.list()
    for d in daemons:
        d["connected"] = pool.is_connected(d["id"])
    return daemons
