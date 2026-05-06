from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Any

from huggingface_hub import cancel_job, inspect_job, list_jobs, list_jobs_hardware, run_job

HF_TOKEN_ENV = "HF_TOKEN"
DAEMON_TOKEN_ENV = "SWITCH_DAEMON_TOKEN"
SPACE_REPO_ENV = "SWITCH_HF_SPACE_REPO_ID"
JOBS_NAMESPACE_ENV = "SWITCH_HF_JOBS_NAMESPACE"
DEFAULT_IMAGE_ENV = "SWITCH_HF_JOBS_DEFAULT_IMAGE"
DEFAULT_FLAVOR_ENV = "SWITCH_HF_JOBS_DEFAULT_FLAVOR"
DEFAULT_TIMEOUT_ENV = "SWITCH_HF_JOBS_DEFAULT_TIMEOUT"

DEFAULT_SPACE_REPO_ID = "edbeeching/agentic-ui"
DEFAULT_IMAGE = "python:3.12"
DEFAULT_FLAVOR = "cpu-basic"
DEFAULT_TIMEOUT = "2h"

JOB_LABELS = {
    "app": "agentic-ui",
    "purpose": "agent-host",
}


def config_payload() -> dict[str, Any]:
    missing = _missing_config()
    return {
        "enabled": not missing,
        "missingConfig": missing,
        "defaults": {
            "image": _default_image(),
            "flavor": _default_flavor(),
            "timeout": _default_timeout(),
            "spaceRepoId": _space_repo_id(),
            "namespace": _jobs_namespace(),
        },
    }


def list_hardware() -> list[dict[str, Any]]:
    _require_hf_token()
    return [_hardware_to_dict(item) for item in list_jobs_hardware(token=_hf_token())]


def start_agent_host_job(
    *,
    hub_url: str,
    image: str | None = None,
    flavor: str | None = None,
    timeout: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    _require_config()
    daemon_name = _normalize_name(name) or _generated_name()
    job = run_job(
        image=_value_or_default(image, _default_image()),
        command=["python", "-c", _bootstrap_script()],
        env=_job_env(hub_url=hub_url, daemon_name=daemon_name),
        secrets={
            HF_TOKEN_ENV: _hf_token(),
            DAEMON_TOKEN_ENV: _daemon_token(),
        },
        flavor=_value_or_default(flavor, _default_flavor()),
        timeout=_value_or_default(timeout, _default_timeout()),
        labels={
            **JOB_LABELS,
            "daemon_name": daemon_name,
        },
        namespace=_jobs_namespace(),
        token=_hf_token(),
    )
    return job_to_dict(job)


def list_agent_host_jobs() -> list[dict[str, Any]]:
    _require_hf_token()
    jobs = list_jobs(namespace=_jobs_namespace(), token=_hf_token())
    filtered = [
        job_to_dict(job)
        for job in jobs
        if _has_agentic_ui_labels(getattr(job, "labels", None) or {})
    ]
    return sorted(filtered, key=lambda item: item.get("createdAt") or "", reverse=True)


def get_job(job_id: str) -> dict[str, Any]:
    _require_hf_token()
    return job_to_dict(inspect_job(job_id=job_id, namespace=_jobs_namespace(), token=_hf_token()))


def cancel_agent_host_job(job_id: str) -> dict[str, Any]:
    _require_hf_token()
    cancel_job(job_id=job_id, namespace=_jobs_namespace(), token=_hf_token())
    return {"status": "cancelling", "jobId": job_id}


def job_to_dict(job: Any) -> dict[str, Any]:
    status = getattr(job, "status", None)
    labels = getattr(job, "labels", None) or {}
    job_id = getattr(job, "id", "")
    daemon_name = labels.get("daemon_name")
    if daemon_name == "auto" and job_id:
        daemon_name = f"hf-container-{job_id[:8]}"
    return {
        "id": job_id,
        "url": getattr(job, "url", None),
        "stage": str(getattr(status, "stage", "UNKNOWN")),
        "message": getattr(status, "message", None),
        "createdAt": _datetime_to_iso(getattr(job, "created_at", None)),
        "image": getattr(job, "docker_image", None),
        "flavor": _flavor_name(getattr(job, "flavor", None)),
        "daemonName": daemon_name,
        "labels": _safe_labels(labels),
    }


def _missing_config() -> list[str]:
    missing = []
    if not _hf_token():
        missing.append(HF_TOKEN_ENV)
    if not _daemon_token():
        missing.append(DAEMON_TOKEN_ENV)
    return missing


def _require_config() -> None:
    missing = _missing_config()
    if missing:
        raise HfJobsConfigError(f"Missing required HF Jobs config: {', '.join(missing)}")


def _require_hf_token() -> None:
    if not _hf_token():
        raise HfJobsConfigError(f"Missing required HF Jobs config: {HF_TOKEN_ENV}")


def _hf_token() -> str:
    return os.environ.get(HF_TOKEN_ENV, "").strip()


def _daemon_token() -> str:
    return os.environ.get(DAEMON_TOKEN_ENV, "").strip()


def _space_repo_id() -> str:
    return os.environ.get(SPACE_REPO_ENV, DEFAULT_SPACE_REPO_ID).strip() or DEFAULT_SPACE_REPO_ID


def _jobs_namespace() -> str | None:
    return os.environ.get(JOBS_NAMESPACE_ENV, "").strip() or None


def _default_image() -> str:
    return os.environ.get(DEFAULT_IMAGE_ENV, DEFAULT_IMAGE).strip() or DEFAULT_IMAGE


def _default_flavor() -> str:
    return os.environ.get(DEFAULT_FLAVOR_ENV, DEFAULT_FLAVOR).strip() or DEFAULT_FLAVOR


def _default_timeout() -> str:
    return os.environ.get(DEFAULT_TIMEOUT_ENV, DEFAULT_TIMEOUT).strip() or DEFAULT_TIMEOUT


def _normalize_name(name: str | None) -> str:
    value = (name or "").strip()
    return value


def _generated_name() -> str:
    return f"hf-container-{secrets.token_hex(4)}"


def _value_or_default(value: str | None, default: str) -> str:
    cleaned = (value or "").strip()
    return cleaned or default


def _job_env(*, hub_url: str, daemon_name: str) -> dict[str, str]:
    env = {
        "SWITCH_HUB_URL": hub_url,
        SPACE_REPO_ENV: _space_repo_id(),
    }
    if daemon_name:
        env["SWITCH_DAEMON_NAME"] = daemon_name
    return env


def _bootstrap_script() -> str:
    return (
        "import os, subprocess, sys; "
        "subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'huggingface_hub==1.8.0'], check=True); "
        "from huggingface_hub import snapshot_download; "
        "repo_id = os.environ['SWITCH_HF_SPACE_REPO_ID']; "
        "path = snapshot_download(repo_id=repo_id, repo_type='space', token=os.environ['HF_TOKEN']); "
        "subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', path], check=True); "
        "name = os.environ['SWITCH_DAEMON_NAME']; "
        "subprocess.run(['switch', 'host', '--hub', os.environ['SWITCH_HUB_URL'], '--name', name], check=True)"
    )


def _has_agentic_ui_labels(labels: dict[str, Any]) -> bool:
    return all(labels.get(key) == value for key, value in JOB_LABELS.items())


def _safe_labels(labels: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in labels.items()
        if key in {"app", "purpose", "daemon_name"}
    }


def _datetime_to_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _flavor_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def _hardware_to_dict(item: Any) -> dict[str, Any]:
    accelerator = getattr(item, "accelerator", None)
    return {
        "name": getattr(item, "name", ""),
        "prettyName": getattr(item, "pretty_name", None) or getattr(item, "name", ""),
        "cpu": getattr(item, "cpu", None),
        "ram": getattr(item, "ram", None),
        "unitCostUsd": getattr(item, "unit_cost_usd", None),
        "unitLabel": getattr(item, "unit_label", None),
        "accelerator": None if accelerator is None else {
            "type": getattr(accelerator, "type", None),
            "model": getattr(accelerator, "model", None),
            "quantity": getattr(accelerator, "quantity", None),
            "vram": getattr(accelerator, "vram", None),
            "manufacturer": getattr(accelerator, "manufacturer", None),
        },
    }


class HfJobsConfigError(RuntimeError):
    pass
