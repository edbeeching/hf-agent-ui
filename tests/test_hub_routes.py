from __future__ import annotations

from fastapi.testclient import TestClient

from switch.hub.app import app


def test_hub_info_uses_configured_daemon_url(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_HUB_DAEMON_URL", "http://192.168.1.50:9341")
    monkeypatch.delenv("SWITCH_DAEMON_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_EXPOSE_DAEMON_TOKEN", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "http://192.168.1.50:9341",
        "daemonTokenRequired": False,
    }


def test_hub_info_falls_back_to_request_base_url(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_HUB_DAEMON_URL", raising=False)
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "secret")
    monkeypatch.delenv("SWITCH_EXPOSE_DAEMON_TOKEN", raising=False)

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "http://hub.example.test:9341",
        "daemonTokenRequired": True,
    }


def test_hub_info_prefers_forwarded_public_url(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_HUB_DAEMON_URL", raising=False)
    monkeypatch.delenv("SWITCH_DAEMON_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_EXPOSE_DAEMON_TOKEN", raising=False)

    with TestClient(app, base_url="http://internal:7860") as client:
        response = client.get("/api/hub", headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "switch-space.hf.space",
        })

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "https://switch-space.hf.space",
        "daemonTokenRequired": False,
    }


def test_hub_info_forces_https_for_hf_space_host(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_HUB_DAEMON_URL", raising=False)
    monkeypatch.delenv("SWITCH_DAEMON_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_EXPOSE_DAEMON_TOKEN", raising=False)

    with TestClient(app, base_url="http://edbeeching-switch.hf.space") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "https://edbeeching-switch.hf.space",
        "daemonTokenRequired": False,
    }


def test_hub_info_can_expose_daemon_token_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_HUB_DAEMON_URL", raising=False)
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "secret")
    monkeypatch.setenv("SWITCH_EXPOSE_DAEMON_TOKEN", "1")

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "http://hub.example.test:9341",
        "daemonTokenRequired": True,
        "daemonToken": "secret",
    }
