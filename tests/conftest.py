from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def default_single_user_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_AGENT_UI_AUTH_MODE", "single")
