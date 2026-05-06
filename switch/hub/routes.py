from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import hf_jobs
from .hf_jobs import HfJobsConfigError
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
    daemon_hub_url = daemon_hub_url_for_request(request)
    daemon_token = os.environ.get("SWITCH_DAEMON_TOKEN")
    payload: dict[str, Any] = {
        "daemonHubUrl": daemon_hub_url,
        "daemonTokenRequired": bool(daemon_token),
    }
    if daemon_token and should_expose_host_token():
        payload["daemonToken"] = daemon_token
    return payload


def daemon_hub_url_for_request(request: Request) -> str:
    daemon_hub_url = os.environ.get("SWITCH_HUB_DAEMON_URL")
    if daemon_hub_url:
        return daemon_hub_url

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        daemon_hub_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        daemon_hub_url = str(request.base_url).rstrip("/")
    if daemon_hub_url.startswith("http://") and request.headers.get("host", "").endswith(".hf.space"):
        daemon_hub_url = daemon_hub_url.replace("http://", "https://", 1)
    return daemon_hub_url


class HfCloudJobRequest(BaseModel):
    image: str | None = None
    flavor: str | None = None
    timeout: str | None = None
    name: str | None = None


@router.get("/cloud/hf/config")
async def hf_cloud_config() -> dict[str, Any]:
    return hf_jobs.config_payload()


@router.get("/cloud/hf/hardware")
async def hf_cloud_hardware() -> list[dict[str, Any]]:
    try:
        return hf_jobs.list_hardware()
    except HfJobsConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HF Jobs hardware lookup failed: {exc}") from exc


@router.post("/cloud/hf/jobs")
async def create_hf_cloud_job(req: HfCloudJobRequest, request: Request) -> dict[str, Any]:
    try:
        return hf_jobs.start_agent_host_job(
            hub_url=daemon_hub_url_for_request(request),
            image=req.image,
            flavor=req.flavor,
            timeout=req.timeout,
            name=req.name,
        )
    except HfJobsConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HF Jobs launch failed: {exc}") from exc


@router.get("/cloud/hf/jobs")
async def list_hf_cloud_jobs() -> list[dict[str, Any]]:
    try:
        return hf_jobs.list_agent_host_jobs()
    except HfJobsConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HF Jobs listing failed: {exc}") from exc


@router.post("/cloud/hf/jobs/{job_id}/cancel")
async def cancel_hf_cloud_job(job_id: str) -> dict[str, Any]:
    try:
        return hf_jobs.cancel_agent_host_job(job_id)
    except HfJobsConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"HF Jobs cancel failed: {exc}") from exc


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
