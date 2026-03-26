from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast


def _load_supabase_config() -> dict[str, dict[str, object]]:
    config_path = Path("supabase/config.toml")
    return cast(
        dict[str, dict[str, object]],
        tomllib.loads(config_path.read_text(encoding="utf-8")),
    )


def test_local_supabase_disables_optional_idle_services() -> None:
    config = _load_supabase_config()

    assert config["realtime"]["enabled"] is False
    assert config["studio"]["enabled"] is False
    assert config["inbucket"]["enabled"] is False
    assert config["analytics"]["enabled"] is False
