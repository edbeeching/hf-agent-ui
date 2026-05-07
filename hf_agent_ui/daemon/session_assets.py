from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import uuid

ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ASSET_CACHE_ENV = "HF_AGENT_UI_ASSET_CACHE_DIR"


@dataclass(frozen=True)
class SavedSessionImage:
    path: Path
    mime_type: str
    size: int


class SessionImageError(ValueError):
    pass


def save_session_image(
    *,
    session_id: str,
    mime_type: object,
    data_base64: object,
    filename: object = None,
) -> SavedSessionImage:
    if not isinstance(mime_type, str) or mime_type not in ALLOWED_IMAGE_TYPES:
        raise SessionImageError("Unsupported image type")
    if not isinstance(data_base64, str) or not data_base64:
        raise SessionImageError("Missing image data")
    try:
        data = base64.b64decode(_strip_data_url(data_base64), validate=True)
    except ValueError as exc:
        raise SessionImageError("Invalid image data") from exc
    if not data:
        raise SessionImageError("Image data is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise SessionImageError("Image is too large")
    if not _magic_bytes_match(mime_type, data):
        raise SessionImageError("Image data does not match its MIME type")

    root_dir = _asset_root()
    root_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_dir.chmod(0o700)
    session_dir = root_dir / _safe_path_segment(session_id)
    session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    session_dir.chmod(0o700)
    path = session_dir / _asset_filename(mime_type, filename)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return SavedSessionImage(path=path, mime_type=mime_type, size=len(data))


def _asset_root() -> Path:
    configured = os.environ.get(ASSET_CACHE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache).expanduser() / "hf-agent-ui" / "session-assets"
    return Path.home() / ".cache" / "hf-agent-ui" / "session-assets"


def _asset_filename(mime_type: str, filename: object) -> str:
    extension = ALLOWED_IMAGE_TYPES[mime_type]
    stem = "screenshot"
    if isinstance(filename, str) and filename.strip():
        candidate = Path(filename.strip()).stem
        if candidate:
            stem = _safe_path_segment(candidate)[:48] or stem
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{stem}-{uuid.uuid4().hex[:12]}{extension}"


def _safe_path_segment(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value.strip())
    return cleaned.strip(".-") or "image"


def _strip_data_url(value: str) -> str:
    if value.startswith("data:"):
        _, _, payload = value.partition(",")
        return payload
    return value


def _magic_bytes_match(mime_type: str, data: bytes) -> bool:
    if mime_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/webp":
        return data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP"
    return False
