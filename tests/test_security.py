from __future__ import annotations

import base64
import json

from hf_agent_ui.hub import security
from hf_agent_ui.hub.security import (
    USER_HOST_TOKEN_TTL_SECONDS,
    UserIdentity,
    auth_mode,
    user_from_host_token,
    user_host_token,
)


def test_user_host_token_round_trips_identity(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    monkeypatch.setattr(security.time, "time", lambda: 1_700_000_000)
    user = UserIdentity(sub="hf-user-123", username="edward", display_name="Edward")

    token = user_host_token(user)
    parsed = user_from_host_token(token)

    assert parsed == UserIdentity(sub="hf-user-123", username="edward", display_name="edward")
    payload = _token_payload(token)
    assert payload["iat"] == 1_700_000_000
    assert payload["exp"] == 1_700_000_000 + USER_HOST_TOKEN_TTL_SECONDS


def test_user_host_token_rejects_tampering(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    token = user_host_token(UserIdentity(sub="hf-user-123", username="edward", display_name="Edward"))
    prefix, payload, signature = token.split(".")

    assert user_from_host_token(f"{prefix}.{payload[:-1]}x.{signature}") is None


def test_user_host_token_rejects_expired_token(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    issued_at = 1_700_000_000
    monkeypatch.setattr(security.time, "time", lambda: issued_at)
    token = user_host_token(UserIdentity(sub="hf-user-123", username="edward", display_name="Edward"))

    monkeypatch.setattr(security.time, "time", lambda: issued_at + USER_HOST_TOKEN_TTL_SECONDS + 1)

    assert user_from_host_token(token) is None


def test_user_host_token_rejects_legacy_token_without_expiry(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    payload = {
        "kind": "host",
        "sub": "hf-user-123",
        "username": "edward",
        "version": 1,
    }
    payload_b64 = security._b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = security._sign_payload(payload_b64, "signing-secret")
    token = f"{security.SIGNED_HOST_TOKEN_PREFIX}.{payload_b64}.{signature}"

    assert user_from_host_token(token) is None


def test_auth_mode_uses_oauth_env_when_not_explicit(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_AUTH_MODE", raising=False)
    monkeypatch.setenv("OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OPENID_PROVIDER_URL", "https://huggingface.co")

    assert auth_mode() == "hf-oauth"


def _token_payload(token: str) -> dict:
    _, payload_b64, _ = token.split(".")
    padding = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode())
