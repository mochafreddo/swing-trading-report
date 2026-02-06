from __future__ import annotations

import os
from pathlib import Path

import pytest
from sab import env_loader


def _force_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env_loader, "_load_with_python_dotenv", lambda **_: False)


def test_fallback_parser_loads_dotenv_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        (
            "# comment\n"
            "KIS_APP_KEY=test-key\n"
            "KIS_BASE_URL=https://openapi.koreainvestment.com # inline comment\n"
            'export FX_MODE="kis"\n'
            "USD_KRW_RATE='1320.5'\n"
            "NOT_A_VALID_LINE\n"
        ),
        encoding="utf-8",
    )

    _force_fallback(monkeypatch)
    for key in ("KIS_APP_KEY", "KIS_BASE_URL", "FX_MODE", "USD_KRW_RATE"):
        monkeypatch.delenv(key, raising=False)

    env_loader.load_dotenv_if_available(dotenv_path=dotenv_path, override=False)

    assert os.getenv("KIS_APP_KEY") == "test-key"
    assert os.getenv("KIS_BASE_URL") == "https://openapi.koreainvestment.com"
    assert os.getenv("FX_MODE") == "kis"
    assert os.getenv("USD_KRW_RATE") == "1320.5"


def test_fallback_parser_respects_override_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("KIS_APP_KEY=from-file\n", encoding="utf-8")

    _force_fallback(monkeypatch)
    monkeypatch.setenv("KIS_APP_KEY", "existing")

    env_loader.load_dotenv_if_available(dotenv_path=dotenv_path, override=False)
    assert os.getenv("KIS_APP_KEY") == "existing"

    env_loader.load_dotenv_if_available(dotenv_path=dotenv_path, override=True)
    assert os.getenv("KIS_APP_KEY") == "from-file"
