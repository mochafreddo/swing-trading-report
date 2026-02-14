from __future__ import annotations

from collections import Counter
from pathlib import Path


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
        "KIS_BASE_URL",
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
