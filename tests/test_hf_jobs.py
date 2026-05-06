from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hf_agent_ui.hub import hf_jobs
from hf_agent_ui.hub.app import app
from hf_agent_ui.hub.security import UserIdentity


@dataclass
class FakeStatus:
    stage: str
    message: str | None = None


@dataclass
class FakeJob:
    id: str
    status: FakeStatus
    labels: dict[str, str]
    url: str = "https://huggingface.co/jobs/edbeeching/job-1"
    created_at: datetime = datetime(2026, 5, 6, tzinfo=timezone.utc)
    docker_image: str = "python:3.12"
    flavor: str = "cpu-basic"


@dataclass
class FakeAccelerator:
    type: str = "gpu"
    model: str = "T4"
    quantity: str = "1"
    vram: str = "16 GB"
    manufacturer: str = "Nvidia"


@dataclass
class FakeHardware:
    name: str = "t4-small"
    pretty_name: str = "Nvidia T4 - small"
    cpu: str = "4 vCPU"
    ram: str = "15 GB"
    accelerator: FakeAccelerator | None = None
    unit_cost_usd: float = 0.006667
    unit_label: str = "minute"


def test_hf_jobs_config_reports_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)

    payload = hf_jobs.config_payload()

    assert payload["enabled"] is False
    assert payload["missingConfig"] == ["HF_TOKEN", "HF_AGENT_UI_HOST_TOKEN"]
    assert payload["defaults"]["image"] == "python:3.12"
    assert payload["defaults"]["flavor"] == "cpu-basic"
    assert payload["defaults"]["spaceRepoId"] == "edbeeching/hf-agent-ui"


def test_hf_jobs_config_oauth_does_not_require_shared_host_token(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)

    payload = hf_jobs.config_payload()

    assert payload["enabled"] is True
    assert payload["missingConfig"] == []


def test_hf_jobs_config_oauth_requires_user_token_secret(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_USER_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("OAUTH_CLIENT_SECRET", raising=False)

    payload = hf_jobs.config_payload()

    assert payload["enabled"] is False
    assert payload["missingConfig"] == ["HF_AGENT_UI_USER_TOKEN_SECRET"]


def test_hf_jobs_start_injects_secrets_and_bootstrap_command(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "daemon-secret")
    monkeypatch.setenv("HF_AGENT_UI_SPACE_REPO_ID", "edbeeching/hf-agent-ui")
    calls: list[dict[str, Any]] = []

    def fake_run_job(**kwargs):
        calls.append(kwargs)
        return FakeJob(
            id="job-12345678",
            status=FakeStatus("RUNNING"),
            labels=kwargs["labels"],
        )

    monkeypatch.setattr(hf_jobs, "run_job", fake_run_job)

    payload = hf_jobs.start_agent_host_job(
        hub_url="https://edbeeching-hf-agent-ui.hf.space",
        image="python:3.12",
        flavor="t4-small",
        timeout="30m",
        name="gpu-box",
    )

    assert payload["id"] == "job-12345678"
    assert payload["stage"] == "RUNNING"
    assert payload["daemonName"] == "gpu-box"
    assert len(calls) == 1

    call = calls[0]
    assert call["image"] == "python:3.12"
    assert call["flavor"] == "t4-small"
    assert call["timeout"] == "30m"
    assert call["env"] == {
        "HF_AGENT_UI_HUB_URL": "https://edbeeching-hf-agent-ui.hf.space",
        "HF_AGENT_UI_SPACE_REPO_ID": "edbeeching/hf-agent-ui",
        "HF_AGENT_UI_HOST_NAME": "gpu-box",
    }
    assert call["secrets"] == {
        "HF_TOKEN": "hf-secret",
        "HF_AGENT_UI_HOST_TOKEN": "daemon-secret",
    }
    assert call["labels"]["app"] == "hf-agent-ui"
    assert call["labels"]["purpose"] == "agent-host"
    assert call["labels"]["owner_sub_hash"] == hf_jobs._owner_label(UserIdentity(
        sub="single-user",
        username="single-user",
        display_name="Single user",
    ))
    assert "'hf-agent-ui', 'host'" in call["command"][2]
    assert "daemon-secret" not in str(payload)
    assert "hf-secret" not in str(payload)


def test_hf_jobs_start_generates_name_when_omitted(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "daemon-secret")
    monkeypatch.setattr(hf_jobs, "_generated_name", lambda: "hf-container-1234abcd")
    calls: list[dict[str, Any]] = []

    def fake_run_job(**kwargs):
        calls.append(kwargs)
        return FakeJob(
            id="job-12345678",
            status=FakeStatus("RUNNING"),
            labels=kwargs["labels"],
        )

    monkeypatch.setattr(hf_jobs, "run_job", fake_run_job)

    payload = hf_jobs.start_agent_host_job(hub_url="https://edbeeching-hf-agent-ui.hf.space")

    assert payload["daemonName"] == "hf-container-1234abcd"
    assert calls[0]["env"]["HF_AGENT_UI_HOST_NAME"] == "hf-container-1234abcd"
    assert calls[0]["labels"]["daemon_name"] == "hf-container-1234abcd"


def test_hf_jobs_start_oauth_labels_owner_and_uses_user_token(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    user = UserIdentity(sub="alice-sub", username="alice", display_name="Alice")
    calls: list[dict[str, Any]] = []

    def fake_run_job(**kwargs):
        calls.append(kwargs)
        return FakeJob(
            id="job-12345678",
            status=FakeStatus("RUNNING"),
            labels=kwargs["labels"],
        )

    monkeypatch.setattr(hf_jobs, "run_job", fake_run_job)

    payload = hf_jobs.start_agent_host_job(
        hub_url="https://edbeeching-hf-agent-ui.hf.space",
        owner=user,
        host_token="alice-host-token",
        name="alice-host",
    )

    assert payload["daemonName"] == "alice-host"
    assert calls[0]["secrets"]["HF_AGENT_UI_HOST_TOKEN"] == "alice-host-token"
    assert calls[0]["labels"]["owner_sub_hash"] == hf_jobs._owner_label(user)
    assert calls[0]["labels"]["owner_username"] == "alice"


def test_hf_jobs_list_filters_hf_agent_ui_jobs(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")

    monkeypatch.setattr(hf_jobs, "list_jobs", lambda **kwargs: [
        FakeJob("agent-job", FakeStatus("RUNNING"), {**hf_jobs.JOB_LABELS, "daemon_name": "agent"}),
        FakeJob("other-job", FakeStatus("RUNNING"), {"app": "other"}),
    ])

    payload = hf_jobs.list_agent_host_jobs()

    assert [job["id"] for job in payload] == ["agent-job"]


def test_hf_jobs_auto_daemon_name_matches_bootstrap_name() -> None:
    payload = hf_jobs.job_to_dict(
        FakeJob("job-abcdef123456", FakeStatus("RUNNING"), {**hf_jobs.JOB_LABELS, "daemon_name": "auto"})
    )

    assert payload["daemonName"] == "hf-container-job-abcd"


def test_hf_jobs_hardware_normalizes_accelerators(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setattr(hf_jobs, "list_jobs_hardware", lambda **kwargs: [FakeHardware(accelerator=FakeAccelerator())])

    payload = hf_jobs.list_hardware()

    assert payload == [{
        "name": "t4-small",
        "prettyName": "Nvidia T4 - small",
        "cpu": "4 vCPU",
        "ram": "15 GB",
        "unitCostUsd": 0.006667,
        "unitLabel": "minute",
        "accelerator": {
            "type": "gpu",
            "model": "T4",
            "quantity": "1",
            "vram": "16 GB",
            "manufacturer": "Nvidia",
        },
    }]


def test_hf_jobs_cancel_calls_client(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    calls = []
    monkeypatch.setattr(
        hf_jobs,
        "inspect_job",
        lambda **kwargs: FakeJob("job-123", FakeStatus("RUNNING"), {**hf_jobs.JOB_LABELS, "daemon_name": "agent"}),
    )
    monkeypatch.setattr(hf_jobs, "cancel_job", lambda **kwargs: calls.append(kwargs))

    payload = hf_jobs.cancel_agent_host_job("job-123")

    assert payload == {"status": "cancelling", "jobId": "job-123"}
    assert calls == [{"job_id": "job-123", "namespace": None, "token": "hf-secret"}]


def test_hf_jobs_cancel_rejects_non_agent_job(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    calls = []
    monkeypatch.setattr(
        hf_jobs,
        "inspect_job",
        lambda **kwargs: FakeJob("job-123", FakeStatus("RUNNING"), {}),
    )
    monkeypatch.setattr(hf_jobs, "cancel_job", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(hf_jobs.HfJobsPermissionError):
        hf_jobs.cancel_agent_host_job("job-123")

    assert calls == []


def test_hf_jobs_list_filters_by_owner(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    alice = UserIdentity(sub="alice-sub", username="alice", display_name="Alice")
    bob = UserIdentity(sub="bob-sub", username="bob", display_name="Bob")

    monkeypatch.setattr(hf_jobs, "list_jobs", lambda **kwargs: [
        FakeJob("alice-job", FakeStatus("RUNNING"), {
            **hf_jobs.JOB_LABELS,
            "daemon_name": "alice-host",
            hf_jobs.OWNER_LABEL: hf_jobs._owner_label(alice),
        }),
        FakeJob("bob-job", FakeStatus("RUNNING"), {
            **hf_jobs.JOB_LABELS,
            "daemon_name": "bob-host",
            hf_jobs.OWNER_LABEL: hf_jobs._owner_label(bob),
        }),
    ])

    payload = hf_jobs.list_agent_host_jobs(owner=alice)

    assert [job["id"] for job in payload] == ["alice-job"]


def test_hf_jobs_routes_do_not_expose_secrets(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "daemon-secret")
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")
    monkeypatch.setattr(hf_jobs, "_generated_name", lambda: "hf-container-1234abcd")

    def fake_run_job(**kwargs):
        return FakeJob(
            id="job-12345678",
            status=FakeStatus("SCHEDULING"),
            labels=kwargs["labels"],
        )

    monkeypatch.setattr(hf_jobs, "run_job", fake_run_job)

    with TestClient(app, base_url="https://edbeeching-hf-agent-ui.hf.space") as client:
        response = client.post("/api/cloud/hf/jobs", json={})

    assert response.status_code == 200
    body = response.text
    assert "job-12345678" in body
    assert "hf-container-1234abcd" in body
    assert "hf-secret" not in body
    assert "daemon-secret" not in body


def test_hf_jobs_config_route_works_without_config(monkeypatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")

    with TestClient(app) as client:
        response = client.get("/api/cloud/hf/config")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
