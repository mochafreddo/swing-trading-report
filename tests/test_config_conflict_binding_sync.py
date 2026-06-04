from __future__ import annotations

import ast
from pathlib import Path

import sab.config as config


def _collect_env_keys_from_usage(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    keys: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
            continue

        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getenv"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
            continue

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {
                "env_bool",
                "env_int",
                "env_float",
                "env_optional_float",
                "env_str",
            }
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)

        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "_parse_optional_int"
            and any(
                isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
                for keyword in node.keywords
                if keyword.arg == "env_key"
            )
        ):
            for keyword in node.keywords:
                if (
                    keyword.arg == "env_key"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    keys.add(keyword.value.value)

        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "_resolve_mode_string"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            keys.add(node.args[1].value)

    return keys


def test_env_yaml_conflict_bindings_stay_in_sync_with_config_usage() -> None:
    module_path = Path(config.__file__).resolve()
    used_env_keys = _collect_env_keys_from_usage(module_path)

    intentionally_unpaired_env_keys = {
        "CI",
        "GITHUB_ACTIONS",
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "SAB_CONFIG_STRICT",
    }
    expected_mapped_keys = used_env_keys - intentionally_unpaired_env_keys

    mapped_keys = {env_key for env_key, _ in config._ENV_YAML_CONFLICT_BINDINGS}

    missing = sorted(expected_mapped_keys - mapped_keys)
    stale = sorted(mapped_keys - expected_mapped_keys)

    assert missing == [], (
        "새 env 키가 config에서 사용되지만 충돌 매핑에 없습니다. "
        "config._ENV_YAML_CONFLICT_BINDINGS를 업데이트하세요: "
        f"{missing}"
    )
    assert stale == [], (
        "충돌 매핑에 남아 있지만 config에서 더 이상 사용하지 않는 키가 있습니다. "
        "config._ENV_YAML_CONFLICT_BINDINGS를 정리하세요: "
        f"{stale}"
    )
