from __future__ import annotations

from hf_agent_ui.hub.ws_relay import WsRelay


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
