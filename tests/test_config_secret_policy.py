from __future__ import annotations

import pytest
from sab.config import load_config
from sab.config_loader import ConfigLoadError


def _clear_kis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SAB_CONFIG", "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_BASE_URL"):
        monkeypatch.delenv(key, raising=False)


def test_load_config_rejects_kis_secrets_in_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  provider: kis
kis:
  app_key: leaked-key
  app_secret: leaked-secret
  base_url: https://openapi.koreainvestment.com
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _clear_kis_env(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    with pytest.raises(ConfigLoadError, match="Security policy violation"):
        load_config()


def test_load_config_reads_kis_secrets_from_env_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data:
  provider: kis
kis:
  base_url: https://openapi.koreainvestment.com
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _clear_kis_env(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("KIS_APP_KEY", "env-key")
    monkeypatch.setenv("KIS_APP_SECRET", "env-secret")

    cfg = load_config()

    assert cfg.kis_app_key == "env-key"
    assert cfg.kis_app_secret == "env-secret"
