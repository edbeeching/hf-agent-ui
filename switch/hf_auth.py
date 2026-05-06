from __future__ import annotations

import os


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
