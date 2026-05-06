from __future__ import annotations

from hf_agent_ui.hub.daemon_registry import DaemonRegistry
from hf_agent_ui.hub.security import UserIdentity


def test_registry_lists_only_requested_owner() -> None:
    registry = DaemonRegistry()
    alice = UserIdentity(sub="alice-sub", username="alice", display_name="Alice")
    bob = UserIdentity(sub="bob-sub", username="bob", display_name="Bob")

    alice_daemon = registry.register("login-node", "outbound", 0, "alice-box", owner=alice)
    registry.register("login-node", "outbound", 0, "bob-box", owner=bob)

    payload = registry.list(owner_sub=alice.sub)

    assert [daemon["id"] for daemon in payload] == [alice_daemon.id]
    assert registry.owns(alice_daemon.id, alice.sub) is True
    assert registry.owns(alice_daemon.id, bob.sub) is False
