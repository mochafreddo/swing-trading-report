from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path


def write_status_json(
    path: str | os.PathLike[str], payload: Mapping[str, object]
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, raw_tmp_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(raw_tmp_path)
    replaced = False

    try:
        try:
            file_obj = os.fdopen(fd, "w", encoding="utf-8")
        except Exception:
            os.close(fd)
            raise
        with file_obj as tmp:
            json.dump(dict(payload), tmp, ensure_ascii=False, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        replaced = True
    finally:
        if not replaced:
            with suppress(FileNotFoundError):
                tmp_path.unlink()
