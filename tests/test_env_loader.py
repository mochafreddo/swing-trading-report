from __future__ import annotations

import os
import threading
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


def test_fallback_parser_respects_python_dotenv_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("KIS_APP_KEY=from-file\n", encoding="utf-8")

    _force_fallback(monkeypatch)
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "true")

    env_loader.load_dotenv_if_available(dotenv_path=dotenv_path, override=False)

    assert os.getenv("KIS_APP_KEY") is None


def test_suppress_config_env_keys_blocks_dotenv_reload_without_mutating_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("HOLDINGS_FILE=from-file\n", encoding="utf-8")

    _force_fallback(monkeypatch)
    monkeypatch.setenv("HOLDINGS_FILE", "existing")

    with env_loader.suppress_config_env_keys(["HOLDINGS_FILE"]):
        assert env_loader.getenv("HOLDINGS_FILE") is None
        assert os.getenv("HOLDINGS_FILE") == "existing"
        env_loader.load_dotenv_if_available(dotenv_path=dotenv_path, override=False)
        assert env_loader.getenv("HOLDINGS_FILE") is None
        assert os.getenv("HOLDINGS_FILE") == "existing"

    assert os.getenv("HOLDINGS_FILE") == "existing"


def test_suppress_config_env_keys_respects_python_dotenv_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "KIS_APP_KEY=from-file\nHOLDINGS_FILE=from-file\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.setenv("HOLDINGS_FILE", "existing")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "true")

    with env_loader.suppress_config_env_keys(["HOLDINGS_FILE"]):
        env_loader.load_dotenv_if_available(dotenv_path=dotenv_path, override=False)

    assert os.getenv("KIS_APP_KEY") is None
    assert os.getenv("HOLDINGS_FILE") == "existing"


def test_suppress_config_env_keys_preserves_python_dotenv_interpolation_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "BASE=from-file\nCOMBINED=${BASE}\nHOLDINGS_FILE=from-file\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BASE", "from-env")
    monkeypatch.delenv("COMBINED", raising=False)
    monkeypatch.setenv("HOLDINGS_FILE", "existing")

    with env_loader.suppress_config_env_keys(["HOLDINGS_FILE"]):
        env_loader.load_dotenv_if_available(dotenv_path=dotenv_path, override=False)

    assert os.getenv("BASE") == "from-env"
    assert os.getenv("COMBINED") == "from-env"
    assert os.getenv("HOLDINGS_FILE") == "existing"


def test_suppress_config_env_keys_does_not_hide_value_from_other_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOLDINGS_FILE", "existing")
    observed: list[tuple[str | None, str | None]] = []

    def observe_env() -> None:
        observed.append(
            (
                env_loader.getenv("HOLDINGS_FILE"),
                os.getenv("HOLDINGS_FILE"),
            )
        )

    with env_loader.suppress_config_env_keys(["HOLDINGS_FILE"]):
        assert env_loader.getenv("HOLDINGS_FILE") is None
        assert os.getenv("HOLDINGS_FILE") == "existing"
        thread = threading.Thread(target=observe_env)
        thread.start()
        thread.join(timeout=1)

    assert observed == [("existing", "existing")]


def test_env_flag_returns_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAB_TEST_FLAG", raising=False)
    assert env_loader.env_flag("SAB_TEST_FLAG") is False
    assert env_loader.env_flag("SAB_TEST_FLAG", default=True) is True


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "y", "on", "  On  "])
def test_env_flag_recognizes_truthy_values(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SAB_TEST_FLAG", raw)
    assert env_loader.env_flag("SAB_TEST_FLAG") is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "", "maybe"])
def test_env_flag_treats_other_values_as_false(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SAB_TEST_FLAG", raw)
    assert env_loader.env_flag("SAB_TEST_FLAG") is False
