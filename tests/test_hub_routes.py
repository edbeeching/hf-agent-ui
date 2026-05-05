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
    monkeypatch.setenv("SWITCH_TRUST_PROXY_AUTH", "1")

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
    monkeypatch.setenv("SWITCH_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://internal:7860") as client:
        response = client.get("/api/hub", headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "agentic-ui-space.hf.space",
        })

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "https://agentic-ui-space.hf.space",
        "daemonTokenRequired": False,
    }


def test_hub_info_forces_https_for_hf_space_host(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_HUB_DAEMON_URL", raising=False)
    monkeypatch.delenv("SWITCH_DAEMON_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_EXPOSE_DAEMON_TOKEN", raising=False)
    monkeypatch.setenv("SWITCH_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://edbeeching-agentic-ui.hf.space") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "https://edbeeching-agentic-ui.hf.space",
        "daemonTokenRequired": False,
    }


def test_hub_info_can_expose_daemon_token_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_HUB_DAEMON_URL", raising=False)
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "secret")
    monkeypatch.setenv("SWITCH_UNSAFE_EXPOSE_HOST_TOKEN", "1")
    monkeypatch.setenv("SWITCH_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "http://hub.example.test:9341",
        "daemonTokenRequired": True,
        "daemonToken": "secret",
    }


def test_hub_info_does_not_expose_daemon_token_with_legacy_env(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_HUB_DAEMON_URL", raising=False)
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "secret")
    monkeypatch.setenv("SWITCH_EXPOSE_DAEMON_TOKEN", "1")
    monkeypatch.setenv("SWITCH_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "daemonHubUrl": "http://hub.example.test:9341",
        "daemonTokenRequired": True,
    }


def test_api_requires_ui_token_for_remote_browser(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_UI_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/daemons")

    assert response.status_code == 401


def test_api_rejects_spoofed_local_host_from_remote_client(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_UI_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="http://hub.example.test:9341",
        client=("203.0.113.10", 50000),
    ) as client:
        response = client.get("/api/daemons", headers={"Host": "localhost:9341"})

    assert response.status_code == 401


def test_api_rejects_proxy_public_host_without_browser_auth(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_UI_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="http://hub.example.test:9341",
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.get("/api/daemons")

    assert response.status_code == 401


def test_api_allows_local_browser_without_ui_token(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_UI_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="http://localhost:9341",
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.get("/api/daemons")

    assert response.status_code == 200


def test_api_allows_ui_token_header_for_remote_browser(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_UI_TOKEN", "ui-secret")
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/daemons", headers={"X-Agentic-UI-Token": "ui-secret"})

    assert response.status_code == 200


def test_auth_cookie_endpoint_sets_httponly_cookie(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_UI_TOKEN", "ui-secret")
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="https://hub.example.test:9341",
        client=("203.0.113.10", 50000),
    ) as client:
        response = client.post(
            "/api/auth/browser-cookie",
            headers={"X-Agentic-UI-Token": "ui-secret"},
        )
        cookie = response.headers["set-cookie"]

        assert response.status_code == 200
        assert response.json() == {"cookie": True}
        assert "agentic_ui_token=ui-secret" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie

        cookie_response = client.get("/api/daemons")

    assert cookie_response.status_code == 200


def test_http_responses_include_security_headers(monkeypatch) -> None:
    monkeypatch.delenv("SWITCH_UI_TOKEN", raising=False)
    monkeypatch.delenv("SWITCH_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"


def test_hf_space_responses_allow_huggingface_embed(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="https://edbeeching-agentic-ui.hf.space") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert "x-frame-options" not in response.headers
    assert "frame-ancestors https://huggingface.co" in response.headers["content-security-policy"]
