"""Report existing local checks without fixing code or storing history."""

import os
import shlex
import shutil
import subprocess
import tempfile
import time
import tomllib
from collections import deque
from pathlib import Path


def run_check(command, env):
    started = time.monotonic()
    code = None
    try:
        argv = shlex.split(command)
        required = [argv[0]]
        if argv[0] == "actionlint":
            required.append("shellcheck")
        missing = [tool for tool in required if not shutil.which(tool)]
        if missing:
            return "SKIPPED", None, 0.0, "Missing tool: " + ", ".join(missing)
        with tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8", errors="replace"
        ) as log:
            result = subprocess.run(
                argv, env=env, stdout=log, stderr=subprocess.STDOUT, check=False
            )
            code = result.returncode
            log.seek(0)
            detail = "".join(deque(log, maxlen=50)) if code else ""
        status = "PASSED" if code == 0 else "FAILED"
        return status, code, time.monotonic() - started, detail
    except (OSError, ValueError) as error:
        return "ERROR", code, time.monotonic() - started, str(error)


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    try:
        config = tomllib.loads((root / "mise.toml").read_text(encoding="utf-8"))
        commands = []
        for task in ("lint", "test", "negative-controls"):
            run = config["tasks"][task]["run"]
            if isinstance(run, str):
                run = [run]
            if not isinstance(run, list) or not run:
                raise ValueError(f"No check commands: {task}")
            for command in run:
                if not isinstance(command, str) or not shlex.split(command):
                    raise ValueError(f"Invalid check command: {task}")
                commands.append(command)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}")
        return 1

    env = {**os.environ, "MISE_AUTO_INSTALL": "0"}
    rows = []
    for command in commands:
        print(f"Running: {command}", flush=True)
        rows.append((command, *run_check(command, env)))
    print("\nCommand | Status | Exit | Duration")
    print("--- | --- | --- | ---")
    for command, status, code, duration, _ in rows:
        print(
            f"{command} | {status} | {code if code is not None else '-'} | {duration:.2f}s"
        )
    for command, status, _, _, detail in rows:
        if status != "PASSED":
            print(f"\n{command}:\n{detail or 'No diagnostic output.'}")
    success = all(row[1] == "PASSED" for row in rows)
    print("\nOverall: " + ("SUCCESS" if success else "INCOMPLETE"))
    return 0 if success else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nINTERRUPTED: health checks did not complete.")
        raise SystemExit(130) from None
