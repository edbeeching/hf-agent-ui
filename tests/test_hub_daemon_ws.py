from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from switch.hub.app import app


def test_daemon_ws_requires_configured_token(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "secret")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/daemon/ws"):
                pass


def test_daemon_ws_registers_and_relays_browser_messages(monkeypatch) -> None:
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "secret")

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
    monkeypatch.setenv("SWITCH_DAEMON_TOKEN", "secret")

    with TestClient(app) as client:
        with client.websocket_connect("/daemon/ws?token=secret") as daemon_ws:
            daemon_ws.send_json({
                "type": "daemon.register",
                "name": "remote",
                "hostname": "devbox",
            })
            assert daemon_ws.receive_json()["type"] == "daemon.registered"
