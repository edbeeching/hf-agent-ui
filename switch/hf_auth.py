from __future__ import annotations

import os
from urllib.parse import urlsplit


def resolve_hf_token(explicit_token: str | None = None) -> str | None:
    """Resolve a Hugging Face token for private Space requests."""
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    env_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    try:
        from huggingface_hub import get_token
    except Exception:
        return None

    try:
        cached_token = get_token()
    except Exception:
        return None

    if cached_token and cached_token.strip():
        return cached_token.strip()
    return None


def is_hf_space_url(hub_url: str) -> bool:
    return urlsplit(hub_url).netloc.endswith(".hf.space")


def missing_hf_token_message(hub_url: str, hf_token: str | None) -> str | None:
    if not is_hf_space_url(hub_url) or hf_token:
        return None
    return (
        "No Hugging Face token was found for this hf.space hub. Public Spaces may not need one, "
        "but private Hugging Face Spaces require --hf-token, HF_TOKEN, HUGGING_FACE_HUB_TOKEN, "
        "or a local Hugging Face login. If your command used --hf-token \"$HF_TOKEN\", make sure "
        "HF_TOKEN is exported and non-empty; otherwise Hugging Face rejects the WebSocket before "
        "agentic-ui sees it, often as HTTP 404."
    )
