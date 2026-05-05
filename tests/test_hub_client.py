from __future__ import annotations

from switch.daemon.hub_client import _auth_headers, _daemon_ws_url, _is_hf_space_url


def test_daemon_ws_url_uses_ws_for_http() -> None:
    assert _daemon_ws_url("http://localhost:9341") == "ws://localhost:9341/daemon/ws"


def test_daemon_ws_url_uses_wss_for_https() -> None:
    assert _daemon_ws_url("https://agentic-ui-space.hf.space") == "wss://agentic-ui-space.hf.space/daemon/ws"


def test_daemon_ws_url_preserves_base_path() -> None:
    assert _daemon_ws_url("https://example.test/switch") == "wss://example.test/switch/daemon/ws"


def test_daemon_ws_url_can_carry_switch_token_query() -> None:
    assert _daemon_ws_url("https://example.test", query_token="secret") == "wss://example.test/daemon/ws?token=secret"


def test_auth_headers_use_hf_token() -> None:
    assert _auth_headers("hf-token") == {"Authorization": "Bearer hf-token"}


def test_auth_headers_do_not_use_switch_token() -> None:
    assert _auth_headers(None) is None


def test_is_hf_space_url() -> None:
    assert _is_hf_space_url("https://edbeeching-agentic-ui.hf.space")
    assert not _is_hf_space_url("https://huggingface.co/spaces/edbeeching/agentic-ui")
