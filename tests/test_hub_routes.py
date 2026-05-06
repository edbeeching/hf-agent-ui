from __future__ import annotations

from fastapi.testclient import TestClient

from hf_agent_ui.hub.app import app
from hf_agent_ui.hub.security import UserIdentity, require_browser_http, require_browser_user, user_from_host_token

DEFAULT_INSTALL_COMMAND = "uv -vv tool install --force --reinstall git+https://github.com/edbeeching/hf-agent-ui.git"
DEV_INSTALL_COMMAND = f"{DEFAULT_INSTALL_COMMAND}@main"
PROD_INSTALL_COMMAND = f"{DEFAULT_INSTALL_COMMAND}@prod"


def clear_install_env(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_INSTALL_REF", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_INSTALL_REPO_URL", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_SPACE_REPO_ID", raising=False)


def test_hub_info_uses_configured_daemon_url(monkeypatch) -> None:
    clear_install_env(monkeypatch)
    monkeypatch.setenv("HF_AGENT_UI_HUB_URL", "http://192.168.1.50:9341")
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "hostHubUrl": "http://192.168.1.50:9341",
        "hostTokenRequired": False,
        "installCommand": DEFAULT_INSTALL_COMMAND,
    }


def test_hub_info_falls_back_to_request_base_url(monkeypatch) -> None:
    clear_install_env(monkeypatch)
    monkeypatch.delenv("HF_AGENT_UI_HUB_URL", raising=False)
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "secret")
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "hostHubUrl": "http://hub.example.test:9341",
        "hostTokenRequired": True,
        "installCommand": DEFAULT_INSTALL_COMMAND,
    }


def test_hub_info_prefers_forwarded_public_url(monkeypatch) -> None:
    clear_install_env(monkeypatch)
    monkeypatch.delenv("HF_AGENT_UI_HUB_URL", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://internal:7860") as client:
        response = client.get("/api/hub", headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "hf-agent-ui-space.hf.space",
        })

    assert response.status_code == 200
    assert response.json() == {
        "hostHubUrl": "https://hf-agent-ui-space.hf.space",
        "hostTokenRequired": False,
        "installCommand": PROD_INSTALL_COMMAND,
    }


def test_hub_info_forces_https_for_hf_space_host(monkeypatch) -> None:
    clear_install_env(monkeypatch)
    monkeypatch.delenv("HF_AGENT_UI_HUB_URL", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://edbeeching-hf-agent-ui.hf.space") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "hostHubUrl": "https://edbeeching-hf-agent-ui.hf.space",
        "hostTokenRequired": False,
        "installCommand": PROD_INSTALL_COMMAND,
    }


def test_hub_info_uses_main_install_ref_for_dev_space(monkeypatch) -> None:
    clear_install_env(monkeypatch)
    monkeypatch.delenv("HF_AGENT_UI_HUB_URL", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_HOST_TOKEN", raising=False)
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://internal:7860") as client:
        response = client.get("/api/hub", headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "edbeeching-hf-agent-ui-dev.hf.space",
        })

    assert response.status_code == 200
    assert response.json() == {
        "hostHubUrl": "https://edbeeching-hf-agent-ui-dev.hf.space",
        "hostTokenRequired": False,
        "installCommand": DEV_INSTALL_COMMAND,
    }


def test_hub_info_can_expose_daemon_token_when_enabled(monkeypatch) -> None:
    clear_install_env(monkeypatch)
    monkeypatch.delenv("HF_AGENT_UI_HUB_URL", raising=False)
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "secret")
    monkeypatch.setenv("HF_AGENT_UI_UNSAFE_EXPOSE_HOST_TOKEN", "1")
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.json() == {
        "hostHubUrl": "http://hub.example.test:9341",
        "hostTokenRequired": True,
        "hostToken": "secret",
        "installCommand": DEFAULT_INSTALL_COMMAND,
    }


def test_hub_info_returns_per_user_host_token_in_oauth_mode(monkeypatch) -> None:
    clear_install_env(monkeypatch)
    user = UserIdentity(sub="hf-user-123", username="edward", display_name="Edward")
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    monkeypatch.delenv("HF_AGENT_UI_HUB_URL", raising=False)
    app.dependency_overrides[require_browser_http] = lambda: None
    app.dependency_overrides[require_browser_user] = lambda: user

    try:
        with TestClient(app, base_url="https://edbeeching-hf-agent-ui.hf.space") as client:
            response = client.get("/api/hub")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["hostHubUrl"] == "https://edbeeching-hf-agent-ui.hf.space"
    assert payload["hostTokenRequired"] is True
    assert payload["installCommand"] == PROD_INSTALL_COMMAND
    assert user_from_host_token(payload["hostToken"]) == UserIdentity(
        sub="hf-user-123",
        username="edward",
        display_name="edward",
    )


def test_api_requires_ui_token_for_remote_browser(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_BROWSER_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/daemons")

    assert response.status_code == 401


def test_api_rejects_spoofed_local_host_from_remote_client(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_BROWSER_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="http://hub.example.test:9341",
        client=("203.0.113.10", 50000),
    ) as client:
        response = client.get("/api/daemons", headers={"Host": "localhost:9341"})

    assert response.status_code == 401


def test_api_rejects_proxy_public_host_without_browser_auth(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_BROWSER_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="http://hub.example.test:9341",
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.get("/api/daemons")

    assert response.status_code == 401


def test_api_allows_local_browser_without_ui_token(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_BROWSER_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="http://localhost:9341",
        client=("127.0.0.1", 50000),
    ) as client:
        response = client.get("/api/daemons")

    assert response.status_code == 200


def test_api_allows_ui_token_header_for_remote_browser(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_BROWSER_TOKEN", "ui-secret")
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        response = client.get("/api/daemons", headers={"X-HF-Agent-UI-Token": "ui-secret"})

    assert response.status_code == 200


def test_auth_cookie_endpoint_sets_httponly_cookie(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_BROWSER_TOKEN", "ui-secret")
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="https://hub.example.test:9341",
        client=("203.0.113.10", 50000),
    ) as client:
        response = client.post(
            "/api/auth/browser-cookie",
            headers={"X-HF-Agent-UI-Token": "ui-secret"},
        )
        cookie = response.headers["set-cookie"]

        assert response.status_code == 200
        assert response.json() == {"cookie": True}
        assert "hf_agent_ui_token=ui-secret" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie

        cookie_response = client.get("/api/daemons")

    assert cookie_response.status_code == 200


def test_http_responses_include_security_headers(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_BROWSER_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"


def test_hf_space_responses_allow_huggingface_embed(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_TRUST_PROXY_AUTH", "1")

    with TestClient(app, base_url="https://edbeeching-hf-agent-ui.hf.space") as client:
        response = client.get("/api/hub")

    assert response.status_code == 200
    assert "x-frame-options" not in response.headers
    assert "frame-ancestors https://huggingface.co" in response.headers["content-security-policy"]
