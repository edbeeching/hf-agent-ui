from __future__ import annotations

from hf_agent_ui.hub.security import UserIdentity, auth_mode, user_from_host_token, user_host_token


def test_user_host_token_round_trips_identity(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    user = UserIdentity(sub="hf-user-123", username="edward", display_name="Edward")

    token = user_host_token(user)
    parsed = user_from_host_token(token)

    assert parsed == UserIdentity(sub="hf-user-123", username="edward", display_name="edward")


def test_user_host_token_rejects_tampering(monkeypatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "hf-oauth")
    monkeypatch.setenv("HF_AGENT_UI_USER_TOKEN_SECRET", "signing-secret")
    token = user_host_token(UserIdentity(sub="hf-user-123", username="edward", display_name="Edward"))
    prefix, payload, signature = token.split(".")

    assert user_from_host_token(f"{prefix}.{payload[:-1]}x.{signature}") is None


def test_auth_mode_uses_oauth_env_when_not_explicit(monkeypatch) -> None:
    monkeypatch.delenv("HF_AGENT_UI_AUTH_MODE", raising=False)
    monkeypatch.setenv("OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OPENID_PROVIDER_URL", "https://huggingface.co")

    assert auth_mode() == "hf-oauth"
