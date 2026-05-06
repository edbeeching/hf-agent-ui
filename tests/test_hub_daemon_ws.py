from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hf_agent_ui.hub.app import app


def test_daemon_ws_requires_configured_token(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "secret")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/daemon/ws"):
                pass


def test_daemon_ws_registers_and_relays_browser_messages(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "secret")

    with TestClient(app) as client:
        with client.websocket_connect("/daemon/ws", headers={"Authorization": "Bearer secret"}) as daemon_ws:
            daemon_ws.send_json({
                "type": "daemon.register",
                "name": "remote",
                "hostname": "devbox",
            })
            registered = daemon_ws.receive_json()
            daemon_id = registered["daemonId"]

            daemons = client.get("/api/daemons").json()
            assert daemons == [{
                "id": daemon_id,
                "name": "remote",
                "host": "outbound",
                "port": 0,
                "hostname": "devbox",
                "registeredAt": daemons[0]["registeredAt"],
                "lastSeen": daemons[0]["lastSeen"],
                "connected": True,
            }]

            with client.websocket_connect("/ws") as browser_ws:
                browser_ws.send_json({"type": "session.list", "daemonId": daemon_id})
                assert daemon_ws.receive_json() == {"type": "session.list"}

                daemon_ws.send_json({"type": "session.list", "sessions": []})
                assert browser_ws.receive_json() == {
                    "type": "session.list",
                    "sessions": [],
                    "daemonId": daemon_id,
                }


def test_daemon_ws_allows_query_token(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "secret")

    with TestClient(app) as client:
        with client.websocket_connect("/daemon/ws?token=secret") as daemon_ws:
            daemon_ws.send_json({
                "type": "daemon.register",
                "name": "remote",
                "hostname": "devbox",
            })
            assert daemon_ws.receive_json()["type"] == "daemon.registered"


def test_daemon_ws_allows_host_token_header(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "secret")

    with TestClient(app) as client:
        with client.websocket_connect("/daemon/ws", headers={"X-HF-Agent-UI-Host-Token": "secret"}) as daemon_ws:
            daemon_ws.send_json({
                "type": "daemon.register",
                "name": "remote",
                "hostname": "devbox",
            })
            assert daemon_ws.receive_json()["type"] == "daemon.registered"


def test_browser_ws_requires_ui_token_for_remote_browser(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_BROWSER_TOKEN", "ui-secret")
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass


def test_browser_ws_allows_ui_token_query_for_remote_browser(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_BROWSER_TOKEN", "ui-secret")
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(app, base_url="http://hub.example.test:9341") as client:
        with client.websocket_connect("/ws?uiToken=ui-secret"):
            pass


def test_browser_ws_allows_ui_token_cookie_for_remote_browser(monkeypatch) -> None:
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
        assert response.status_code == 200

        with client.websocket_connect("/ws", headers={"Cookie": "hf_agent_ui_token=ui-secret"}):
            pass


def test_browser_ws_rejects_spoofed_local_host_from_remote_client(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_BROWSER_TOKEN", raising=False)
    monkeypatch.delenv("HF_AGENT_UI_TRUST_PROXY_AUTH", raising=False)

    with TestClient(
        app,
        base_url="http://hub.example.test:9341",
        client=("203.0.113.10", 50000),
    ) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"Host": "localhost:9341"}):
                pass


def test_daemon_ws_rejects_duplicate_active_name(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_HOST_TOKEN", "secret")

    with TestClient(app) as client:
        with client.websocket_connect("/daemon/ws?token=secret") as first_ws:
            first_ws.send_json({
                "type": "daemon.register",
                "name": "remote",
                "hostname": "devbox-1",
            })
            first = first_ws.receive_json()
            assert first["type"] == "daemon.registered"

            with client.websocket_connect("/daemon/ws?token=secret") as second_ws:
                second_ws.send_json({
                    "type": "daemon.register",
                    "name": "remote",
                    "hostname": "devbox-2",
                })
                rejected = second_ws.receive_json()
                assert rejected == {
                    "type": "error",
                    "message": "Agent host name already connected: remote",
                }

            daemons = client.get("/api/daemons").json()
            assert len(daemons) == 1
            assert daemons[0]["id"] == first["daemonId"]
            assert daemons[0]["hostname"] == "devbox-1"
            assert daemons[0]["connected"] is True
