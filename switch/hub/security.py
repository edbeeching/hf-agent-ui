from __future__ import annotations

import hmac
import os
from urllib.parse import unquote

from fastapi import HTTPException, Request, WebSocket, status

UI_TOKEN_ENV = "SWITCH_UI_TOKEN"
TRUST_PROXY_AUTH_ENV = "SWITCH_TRUST_PROXY_AUTH"
UNSAFE_EXPOSE_HOST_TOKEN_ENV = "SWITCH_UNSAFE_EXPOSE_HOST_TOKEN"

UI_TOKEN_HEADER = "x-agentic-ui-token"
UI_TOKEN_QUERY_PARAM = "uiToken"
UI_TOKEN_COOKIE = "agentic_ui_token"


def is_browser_http_authorized(request: Request) -> bool:
    return _is_browser_authorized(
        host=request.headers.get("host", ""),
        client_host=request.client.host if request.client else "",
        token_candidates=(
            _bearer_token(request.headers.get("authorization", "")),
            request.headers.get(UI_TOKEN_HEADER, ""),
            request.query_params.get(UI_TOKEN_QUERY_PARAM, ""),
            request.cookies.get(UI_TOKEN_COOKIE, ""),
        ),
    )


def require_browser_http(request: Request) -> None:
    if not is_browser_http_authorized(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="agentic-ui browser auth required",
        )


def is_browser_ws_authorized(ws: WebSocket) -> bool:
    cookie_token = _cookie_value(ws.headers.get("cookie", ""), UI_TOKEN_COOKIE)
    return _is_browser_authorized(
        host=ws.headers.get("host", ""),
        client_host=ws.client.host if ws.client else "",
        token_candidates=(
            _bearer_token(ws.headers.get("authorization", "")),
            ws.headers.get(UI_TOKEN_HEADER, ""),
            ws.query_params.get(UI_TOKEN_QUERY_PARAM, ""),
            cookie_token,
        ),
    )


def should_expose_host_token() -> bool:
    return os.environ.get(UNSAFE_EXPOSE_HOST_TOKEN_ENV) == "1"


def _is_browser_authorized(
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
    return _is_local_host(host) or _is_local_host(client_host)


def _token_matches(candidate: str | None, expected: str) -> bool:
    if not candidate:
        return False
    return hmac.compare_digest(candidate, expected)


def _bearer_token(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix):] if value.startswith(prefix) else ""


def _cookie_value(header: str, key: str) -> str:
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == key:
            return unquote(value)
    return ""


def _is_local_host(value: str) -> bool:
    host = _strip_port(value).lower()
    return (
        host in {"localhost", "testserver", "127.0.0.1", "::1", ""}
        or host.startswith("127.")
    )


def _strip_port(value: str) -> str:
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value
