from __future__ import annotations

import json

import pytest

from hf_agent_ui.hub.ws_relay import WsRelay


class FakePool:
    def __init__(self, owned: set[tuple[str, str]], send_error: str | None = None) -> None:
        self.owned = owned
        self.send_error = send_error
        self.sent: list[tuple[str, dict]] = []

    def owns(self, daemon_id: str, owner_sub: str) -> bool:
        return (daemon_id, owner_sub) in self.owned

    async def send(self, daemon_id: str, data: dict) -> None:
        if self.send_error:
            raise RuntimeError(self.send_error)
        self.sent.append((daemon_id, data))


class FakeBrowser:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def test_session_list_response_targets_requesting_browser_only() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    relay._clients.update({browser_a, browser_b})  # type: ignore[arg-type]

    relay._track_browser_request(browser_a, "daemon-1", {"type": "session.list"})  # type: ignore[arg-type]

    targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "session.list",
        "sessions": [],
    })

    assert targets == {browser_a}
    assert relay._targets_for_daemon_message("daemon-1", {"type": "session.list"}) == set()


def test_worktrees_list_response_targets_requesting_browser_only() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    relay._clients.update({browser_a, browser_b})  # type: ignore[arg-type]

    relay._track_browser_request(browser_a, "daemon-1", {"type": "worktrees.list"})  # type: ignore[arg-type]

    targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "worktrees.list",
        "sourceDir": "/repo",
        "worktrees": [],
    })

    assert targets == {browser_a}
    assert relay._targets_for_daemon_message("daemon-1", {"type": "worktrees.list"}) == set()


def test_worktrees_list_response_targets_matching_request_id() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    relay._clients.update({browser_a, browser_b})  # type: ignore[arg-type]

    relay._track_browser_request(browser_a, "daemon-1", {  # type: ignore[arg-type]
        "type": "worktrees.list",
        "sourceDir": "/repo-a",
        "requestId": "req-a",
    })
    relay._track_browser_request(browser_b, "daemon-1", {  # type: ignore[arg-type]
        "type": "worktrees.list",
        "sourceDir": "/repo-b",
        "requestId": "req-b",
    })
    relay._clients.discard(browser_a)  # type: ignore[arg-type]

    stale_targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "worktrees.list",
        "sourceDir": "/repo-a",
        "requestId": "req-a",
        "worktrees": [],
    })
    current_targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "worktrees.list",
        "sourceDir": "/repo-b",
        "requestId": "req-b",
        "worktrees": [],
    })

    assert stale_targets == set()
    assert current_targets == {browser_b}


def test_stale_worktrees_list_request_id_does_not_drain_fifo_request() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    relay._clients.update({browser_a, browser_b})  # type: ignore[arg-type]

    relay._track_browser_request(browser_a, "daemon-1", {  # type: ignore[arg-type]
        "type": "worktrees.list",
        "sourceDir": "/repo-a",
        "requestId": "req-a",
    })
    relay._track_browser_request(browser_b, "daemon-1", {  # type: ignore[arg-type]
        "type": "worktrees.list",
        "sourceDir": "/repo-b",
    })
    relay._clients.discard(browser_a)  # type: ignore[arg-type]

    stale_targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "worktrees.list",
        "sourceDir": "/repo-a",
        "requestId": "req-a",
        "worktrees": [],
    })
    fifo_targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "worktrees.list",
        "sourceDir": "/repo-b",
        "worktrees": [],
    })

    assert stale_targets == set()
    assert fifo_targets == {browser_b}


def test_pty_events_target_subscribed_browser_only() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    relay._clients.update({browser_a, browser_b})  # type: ignore[arg-type]

    relay._track_browser_request(browser_a, "daemon-1", {"type": "pty.create"})  # type: ignore[arg-type]

    started_targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "pty.started",
        "sessionId": "session-1",
    })
    output_targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "pty.output",
        "sessionId": "session-1",
        "data": "secret output",
    })

    assert started_targets == {browser_a}
    assert output_targets == {browser_a}
    assert browser_b not in output_targets


def test_session_image_sent_targets_requesting_browser_and_subscribers() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    browser_c = object()
    relay._clients.update({browser_a, browser_b, browser_c})  # type: ignore[arg-type]

    relay._track_browser_request(browser_a, "daemon-1", {  # type: ignore[arg-type]
        "type": "session.image.send",
        "sessionId": "session-1",
    })
    relay._track_browser_request(browser_b, "daemon-1", {  # type: ignore[arg-type]
        "type": "pty.input",
        "sessionId": "session-1",
    })

    targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "session.image.sent",
        "sessionId": "session-1",
    })

    assert targets == {browser_a, browser_b}
    assert browser_c not in targets


def test_pty_input_ack_targets_requesting_browser_only() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    relay._clients.update({browser_a, browser_b})  # type: ignore[arg-type]

    relay._track_browser_request(browser_b, "daemon-1", {  # type: ignore[arg-type]
        "type": "session.subscribe",
        "sessionId": "session-1",
    })
    relay._track_browser_request(browser_a, "daemon-1", {  # type: ignore[arg-type]
        "type": "pty.input",
        "sessionId": "session-1",
        "requestId": "input-1",
    })

    targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "pty.input_ack",
        "sessionId": "session-1",
        "requestId": "input-1",
    })

    assert targets == {browser_a}
    assert relay._targets_for_daemon_message("daemon-1", {
        "type": "pty.input_ack",
        "sessionId": "session-1",
        "requestId": "input-1",
    }) == set()


def test_pty_input_error_targets_matching_request_id() -> None:
    relay = WsRelay(pool=None)  # type: ignore[arg-type]
    browser_a = object()
    browser_b = object()
    relay._clients.update({browser_a, browser_b})  # type: ignore[arg-type]

    relay._track_browser_request(browser_a, "daemon-1", {  # type: ignore[arg-type]
        "type": "pty.input",
        "sessionId": "session-1",
        "requestId": "input-1",
    })
    relay._track_browser_request(browser_b, "daemon-1", {  # type: ignore[arg-type]
        "type": "pty.input",
        "sessionId": "session-1",
        "requestId": "input-2",
    })

    targets = relay._targets_for_daemon_message("daemon-1", {
        "type": "error",
        "message": "write failed",
        "requestType": "pty.input",
        "sessionId": "session-1",
        "requestId": "input-1",
    })

    assert targets == {browser_a}
    assert relay._targets_for_daemon_message("daemon-1", {
        "type": "error",
        "message": "write failed",
        "requestType": "pty.input",
        "sessionId": "session-1",
        "requestId": "input-2",
    }) == {browser_b}


@pytest.mark.asyncio
async def test_browser_message_cannot_target_another_users_daemon() -> None:
    pool = FakePool(owned={("daemon-1", "alice")})
    relay = WsRelay(pool=pool)  # type: ignore[arg-type]
    browser = FakeBrowser()
    relay._clients.add(browser)  # type: ignore[arg-type]
    relay._client_owners[browser] = "alice"  # type: ignore[index]

    await relay._handle_browser_message(browser, {"type": "session.list", "daemonId": "daemon-2"})  # type: ignore[arg-type]

    assert pool.sent == []
    assert browser.sent == [{
        "type": "error",
        "message": "No connection to agent host daemon-2",
        "requestType": "session.list",
        "daemonId": "daemon-2",
    }]


@pytest.mark.asyncio
async def test_worktrees_list_send_error_preserves_request_context() -> None:
    pool = FakePool(owned={("daemon-1", "alice")}, send_error="daemon offline")
    relay = WsRelay(pool=pool)  # type: ignore[arg-type]
    browser = FakeBrowser()
    relay._clients.add(browser)  # type: ignore[arg-type]
    relay._client_owners[browser] = "alice"  # type: ignore[index]

    await relay._handle_browser_message(browser, {
        "type": "worktrees.list",
        "daemonId": "daemon-1",
        "sourceDir": "/repo",
        "requestId": "req-1",
    })  # type: ignore[arg-type]

    assert browser.sent == [{
        "type": "error",
        "message": "daemon offline",
        "requestType": "worktrees.list",
        "daemonId": "daemon-1",
        "requestId": "req-1",
        "sourceDir": "/repo",
    }]
    assert relay._targets_for_daemon_message("daemon-1", {
        "type": "worktrees.list",
        "sourceDir": "/repo",
        "requestId": "req-1",
        "worktrees": [],
    }) == set()
