from __future__ import annotations

from hf_agent_ui.daemon.hub_client import _auth_headers, _daemon_ws_url, _is_hf_space_url, _websocket_status_code


def test_daemon_ws_url_uses_ws_for_http() -> None:
    assert _daemon_ws_url("http://localhost:9341") == "ws://localhost:9341/daemon/ws"


def test_daemon_ws_url_uses_wss_for_https() -> None:
    assert _daemon_ws_url("https://hf-agent-ui-space.hf.space") == "wss://hf-agent-ui-space.hf.space/daemon/ws"


def test_daemon_ws_url_preserves_base_path() -> None:
    assert _daemon_ws_url("https://example.test/hf-agent-ui") == "wss://example.test/hf-agent-ui/daemon/ws"


def test_daemon_ws_url_can_carry_host_token_query() -> None:
    assert _daemon_ws_url("https://example.test", query_token="secret") == "wss://example.test/daemon/ws?token=secret"


def test_auth_headers_use_hf_token() -> None:
    assert _auth_headers("hf-token") == {"Authorization": "Bearer hf-token"}


def test_auth_headers_use_host_token_header() -> None:
    assert _auth_headers(None, host_token="host-secret") == {
        "X-HF-Agent-UI-Host-Token": "host-secret",
    }


def test_auth_headers_include_both_hf_and_host_tokens() -> None:
    assert _auth_headers("hf-token", host_token="host-secret") == {
        "Authorization": "Bearer hf-token",
        "X-HF-Agent-UI-Host-Token": "host-secret",
    }


def test_auth_headers_are_none_without_tokens() -> None:
    assert _auth_headers(None) is None


def test_is_hf_space_url() -> None:
    assert _is_hf_space_url("https://edbeeching-hf-agent-ui.hf.space")
    assert not _is_hf_space_url("https://huggingface.co/spaces/edbeeching/hf-agent-ui")


def test_websocket_status_code_parses_invalid_status_message() -> None:
    assert _websocket_status_code(RuntimeError("server rejected WebSocket connection: HTTP 404")) == 404
