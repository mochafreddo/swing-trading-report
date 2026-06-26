from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_status_json(
    path: str | os.PathLike[str], payload: Mapping[str, object]
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as tmp:
        json.dump(dict(payload), tmp, ensure_ascii=False, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)
