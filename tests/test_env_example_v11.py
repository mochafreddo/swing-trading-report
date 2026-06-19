from __future__ import annotations

from collections import Counter
from pathlib import Path

import sab.config as sab_config
from sab.config_loader import load_yaml_config


def _extract_env_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.append(key)
    return keys


def test_env_example_contains_v11_required_keys() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    keys = set(_extract_env_keys(env_example_path))

    required = {
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "GITHUB_OWNER",
        "GITHUB_REPO",
        "GITHUB_PAT",
        "REPORT_RETENTION_DAYS",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    }

    missing = sorted(required - keys)
    assert not missing, f"Missing keys in .env.example: {missing}"


def test_env_example_has_no_duplicate_keys() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    keys = _extract_env_keys(env_example_path)

    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    assert not duplicates, f"Duplicate keys in .env.example: {duplicates}"


def test_docker_compose_forwards_toss_invest_env_to_web() -> None:
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")

    for key in (
        "TOSS_INVEST_CLIENT_ID",
        "TOSS_INVEST_CLIENT_SECRET",
        "TOSS_INVEST_ACCOUNT",
        "TOSS_INVEST_BASE_URL",
    ):
        assert f"{key}:" in compose_text


def test_env_example_retention_default_is_30_days() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    values: dict[str, str] = {}
    for raw_line in env_example_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    assert values.get("REPORT_RETENTION_DAYS") == "30"


def test_env_example_documents_market_regime_policy_without_active_override() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example_path.read_text(encoding="utf-8")
    active_keys = set(_extract_env_keys(env_example_path))

    assert "MARKET_REGIME_UNAVAILABLE_POLICY" in text
    assert "env override는 YAML이 없을 때만 허용됩니다" in text
    assert "MARKET_REGIME_UNAVAILABLE_POLICY" not in active_keys


def test_env_example_documents_entry_fatal_override_without_active_override() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example_path.read_text(encoding="utf-8")
    active_keys = set(_extract_env_keys(env_example_path))

    assert "ENTRY_FATAL_MISSING_PRICE_RATIO" in text
    assert "entry_check.fatal_missing_price_ratio" in text
    assert "env override는 YAML이 없을 때만 허용됩니다" in text
    assert "ENTRY_FATAL_MISSING_PRICE_RATIO" not in active_keys


def test_env_example_uses_active_kis_interval_in_commented_override() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example_path.read_text(encoding="utf-8")

    assert "# KIS_MIN_INTERVAL_MS=200" in text
    assert "# KIS_MIN_INTERVAL_MS=500" not in text


def test_env_example_conflict_check_treats_zero_yaml_values_as_present() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_data = load_yaml_config(str(repo_root / "config.yaml")).raw

    assert (
        sab_config._from_nested(config_data, "entry_check.fatal_missing_price_ratio")
        == 0.0
    )
    assert sab_config._yaml_path_exists(
        config_data, "entry_check.fatal_missing_price_ratio"
    )


def test_env_example_active_keys_do_not_conflict_with_config() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    active_keys = set(_extract_env_keys(repo_root / ".env.example"))
    config_data = load_yaml_config(str(repo_root / "config.yaml")).raw

    conflicting_keys = []
    for env_key, yaml_path in sab_config._ENV_YAML_CONFLICT_BINDINGS:
        if env_key in active_keys and sab_config._yaml_path_exists(
            config_data, yaml_path
        ):
            conflicting_keys.append(env_key)

    assert not conflicting_keys
