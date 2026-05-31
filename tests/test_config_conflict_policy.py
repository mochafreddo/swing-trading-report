from __future__ import annotations

import pytest
from sab import env_loader
from sab.config import load_config
from sab.config_loader import ConfigLoadError


def _reset_conflict_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SAB_CONFIG", "DATA_PROVIDER", "SCREEN_LIMIT", "FX_MODE"):
        monkeypatch.delenv(key, raising=False)


def _force_fallback_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env_loader, "_load_with_python_dotenv", lambda **_: False)


def test_load_config_rejects_duplicate_keys_between_env_and_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  screen_limit: 30
fx:
  mode: manual
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_conflict_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("SCREEN_LIMIT", "10")
    monkeypatch.setenv("FX_MODE", "kis")

    with pytest.raises(
        ConfigLoadError, match="Config conflict policy violation"
    ) as exc:
        load_config()

    msg = str(exc.value)
    assert "SCREEN_LIMIT (data.screen_limit)" in msg
    assert "FX_MODE (fx.mode)" in msg
    assert "Resolve by removing one side of each duplicate key" in msg
    assert "keep secrets in .env/environment" in msg
    assert "config.local.yaml with SAB_CONFIG=config.local.yaml" in msg


def test_load_config_detects_conflicts_before_cli_override(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  provider: pykrx
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_conflict_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("DATA_PROVIDER", "kis")

    with pytest.raises(ConfigLoadError, match=r"DATA_PROVIDER \(data.provider\)"):
        load_config(provider_override="kis")


def test_load_config_allows_env_when_yaml_key_is_absent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  provider: pykrx
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_conflict_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("SCREEN_LIMIT", "12")

    cfg = load_config()

    assert cfg.data_provider == "pykrx"
    assert cfg.screen_limit == 12


def test_load_config_resolves_sab_config_from_dotenv_before_loading_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        """
data:
  screen_limit: 42
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        f"SAB_CONFIG={config_path}\n",
        encoding="utf-8",
    )

    _reset_conflict_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)

    cfg = load_config()

    assert cfg.screen_limit == 42
