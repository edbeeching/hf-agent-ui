from __future__ import annotations

import base64
import stat
from pathlib import Path

import pytest

from hf_agent_ui.daemon import session_assets
from hf_agent_ui.daemon.session_assets import SessionImageError, save_session_image


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png"


def test_save_session_image_writes_private_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_AGENT_UI_ASSET_CACHE_DIR", str(tmp_path / "assets"))

    image = save_session_image(
        session_id="session/with spaces",
        filename="screen shot.png",
        mime_type="image/png",
        data_base64=base64.b64encode(PNG_BYTES).decode(),
    )

    assert image.path.read_bytes() == PNG_BYTES
    assert image.mime_type == "image/png"
    assert image.size == len(PNG_BYTES)
    assert image.path.suffix == ".png"
    assert image.path.parent.name == "session-with-spaces"
    assert stat.S_IMODE(image.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(image.path.stat().st_mode) == 0o600


def test_save_session_image_rejects_mime_mismatch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_AGENT_UI_ASSET_CACHE_DIR", str(tmp_path / "assets"))

    with pytest.raises(SessionImageError, match="MIME"):
        save_session_image(
            session_id="session-id",
            filename="screenshot.jpg",
            mime_type="image/jpeg",
            data_base64=base64.b64encode(PNG_BYTES).decode(),
        )


def test_save_session_image_rejects_oversized_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_AGENT_UI_ASSET_CACHE_DIR", str(tmp_path / "assets"))
    monkeypatch.setattr(session_assets, "MAX_IMAGE_BYTES", 4)

    with pytest.raises(SessionImageError, match="too large"):
        save_session_image(
            session_id="session-id",
            filename="screenshot.png",
            mime_type="image/png",
            data_base64=base64.b64encode(PNG_BYTES).decode(),
        )
