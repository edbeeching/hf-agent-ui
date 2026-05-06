from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from urllib.parse import unquote

from fastapi import HTTPException, Request, WebSocket, status

AUTH_MODE_ENV = "HF_AGENT_UI_AUTH_MODE"
UI_TOKEN_ENV = "HF_AGENT_UI_BROWSER_TOKEN"
TRUST_PROXY_AUTH_ENV = "HF_AGENT_UI_TRUST_PROXY_AUTH"
UNSAFE_EXPOSE_HOST_TOKEN_ENV = "HF_AGENT_UI_UNSAFE_EXPOSE_HOST_TOKEN"
USER_TOKEN_SECRET_ENV = "HF_AGENT_UI_USER_TOKEN_SECRET"

UI_TOKEN_HEADER = "x-hf-agent-ui-token"
UI_TOKEN_QUERY_PARAM = "uiToken"
UI_TOKEN_COOKIE = "hf_agent_ui_token"
HOST_TOKEN_HEADER = "x-hf-agent-ui-host-token"
SIGNED_HOST_TOKEN_PREFIX = "hfu"
SINGLE_USER_SUB = "single-user"
SINGLE_USER_NAME = "single-user"


@dataclass(frozen=True)
class UserIdentity:
    sub: str
    username: str
    display_name: str

    def to_dict(self) -> dict[str, str]:
        return {
            "sub": self.sub,
            "username": self.username,
            "displayName": self.display_name,
        }


SINGLE_USER = UserIdentity(
    sub=SINGLE_USER_SUB,
    username=SINGLE_USER_NAME,
    display_name="Single user",
)


def is_browser_http_authorized(request: Request) -> bool:
    return current_browser_http_user(request) is not None


def require_browser_http(request: Request) -> None:
    if current_browser_http_user(request) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="hf-agent-ui browser auth required",
        )


def require_browser_user(request: Request) -> UserIdentity:
    user = current_browser_http_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="hf-agent-ui browser auth required",
        )
    return user


def current_browser_http_user(request: Request) -> UserIdentity | None:
    if auth_mode() == "hf-oauth":
        return _oauth_user_from_session(_request_session(request))
    if _is_single_browser_authorized(
        host=request.headers.get("host", ""),
        client_host=request.client.host if request.client else "",
        token_candidates=(
            _bearer_token(request.headers.get("authorization", "")),
            request.headers.get(UI_TOKEN_HEADER, ""),
            request.query_params.get(UI_TOKEN_QUERY_PARAM, ""),
            request.cookies.get(UI_TOKEN_COOKIE, ""),
        ),
    ):
        return SINGLE_USER
    return None


def is_browser_ws_authorized(ws: WebSocket) -> bool:
    return current_browser_ws_user(ws) is not None


def current_browser_ws_user(ws: WebSocket) -> UserIdentity | None:
    if auth_mode() == "hf-oauth":
        return _oauth_user_from_session(_websocket_session(ws))
    cookie_token = _cookie_value(ws.headers.get("cookie", ""), UI_TOKEN_COOKIE)
    if _is_single_browser_authorized(
        host=ws.headers.get("host", ""),
        client_host=ws.client.host if ws.client else "",
        token_candidates=(
            _bearer_token(ws.headers.get("authorization", "")),
            ws.headers.get(UI_TOKEN_HEADER, ""),
            ws.query_params.get(UI_TOKEN_QUERY_PARAM, ""),
            cookie_token,
        ),
    ):
        return SINGLE_USER
    return None


def auth_mode() -> str:
    configured = os.environ.get(AUTH_MODE_ENV, "").strip().lower()
    if configured in {"hf-oauth", "single"}:
        return configured
    if (
        os.environ.get("OAUTH_CLIENT_ID")
        and os.environ.get("OAUTH_CLIENT_SECRET")
        and os.environ.get("OPENID_PROVIDER_URL")
    ):
        return "hf-oauth"
    return "single"


def oauth_routes_enabled() -> bool:
    return auth_mode() == "hf-oauth"


def should_expose_host_token() -> bool:
    return os.environ.get(UNSAFE_EXPOSE_HOST_TOKEN_ENV) == "1"


def has_user_token_secret() -> bool:
    return bool(_user_token_secret())


def user_host_token(user: UserIdentity) -> str:
    secret = _user_token_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Missing required user token signing secret: {USER_TOKEN_SECRET_ENV}",
        )
    payload = {
        "kind": "host",
        "sub": user.sub,
        "username": user.username,
        "version": 1,
    }
    payload_b64 = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _sign_payload(payload_b64, secret)
    return f"{SIGNED_HOST_TOKEN_PREFIX}.{payload_b64}.{signature}"


def user_from_host_token(token: str | None) -> UserIdentity | None:
    if not token:
        return None
    secret = _user_token_secret()
    if not secret:
        return None
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != SIGNED_HOST_TOKEN_PREFIX:
        return None
    _, payload_b64, signature = parts
    expected = _sign_payload(payload_b64, secret)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != "host" or payload.get("version") != 1:
        return None
    sub = payload.get("sub")
    username = payload.get("username")
    if not isinstance(sub, str) or not sub.strip():
        return None
    if not isinstance(username, str) or not username.strip():
        username = sub
    return UserIdentity(sub=sub.strip(), username=username.strip(), display_name=username.strip())


def current_host_ws_user(ws: WebSocket, expected_single_token: str | None = None) -> UserIdentity | None:
    token = _host_token_from_ws(ws)
    if auth_mode() == "hf-oauth":
        return user_from_host_token(token)
    if expected_single_token:
        return SINGLE_USER if _token_matches(token, expected_single_token) else None
    return SINGLE_USER


def _is_single_browser_authorized(
    *,
    host: str,
    client_host: str,
    token_candidates: tuple[str | None, ...],
) -> bool:
    expected = os.environ.get(UI_TOKEN_ENV)
    if expected:
        return any(_token_matches(candidate, expected) for candidate in token_candidates)
    if os.environ.get(TRUST_PROXY_AUTH_ENV) == "1":
        return True
    return _is_local_host(host) and _is_local_host(client_host)


def _token_matches(candidate: str | None, expected: str) -> bool:
    if not candidate:
        return False
    return hmac.compare_digest(candidate, expected)


def _bearer_token(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix):] if value.startswith(prefix) else ""


def _host_token_from_ws(ws: WebSocket) -> str:
    return (
        ws.headers.get(HOST_TOKEN_HEADER, "")
        or _bearer_token(ws.headers.get("authorization", ""))
        or ws.query_params.get("token", "")
    )


def _request_session(request: Request) -> dict | None:
    try:
        return request.session
    except AssertionError:
        return None


def _websocket_session(ws: WebSocket) -> dict | None:
    try:
        return ws.session
    except AssertionError:
        return None


def _oauth_user_from_session(session: dict | None) -> UserIdentity | None:
    if not session:
        return None
    oauth_info = session.get("oauth_info")
    if not isinstance(oauth_info, dict):
        return None
    userinfo = oauth_info.get("userinfo")
    if not isinstance(userinfo, dict):
        return None
    sub = userinfo.get("sub")
    username = userinfo.get("preferred_username")
    name = userinfo.get("name")
    if not isinstance(sub, str) or not sub.strip():
        return None
    if not isinstance(username, str) or not username.strip():
        username = sub
    display_name = name if isinstance(name, str) and name.strip() else username
    return UserIdentity(
        sub=sub.strip(),
        username=username.strip(),
        display_name=display_name.strip(),
    )


def _user_token_secret() -> str:
    return (
        os.environ.get(USER_TOKEN_SECRET_ENV, "").strip()
        or os.environ.get("OAUTH_CLIENT_SECRET", "").strip()
    )


def _sign_payload(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode()


def _cookie_value(header: str, key: str) -> str:
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == key:
            return unquote(value)
    return ""


def _is_local_host(value: str) -> bool:
    host = _strip_port(value).lower()
    return (
        host in {"localhost", "testserver", "testclient", "127.0.0.1", "::1"}
        or host.startswith("127.")
    )


def _strip_port(value: str) -> str:
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value
