from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
