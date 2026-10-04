"""Own ordered response recording and offline report replay validation."""

import hashlib
import json
from pathlib import Path


class DataError(ValueError):
    """A safe diagnostic code, containing no upstream response or credentials."""


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def code_hash(paths) -> dict:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (*paths, Path(__file__))
    }


def identity(rules, paths, contract) -> dict:
    return {
        "format_version": 2,
        "rules": rules,
        "code_sha256": code_hash(paths),
        "contract": contract.read_text(),
    }


class ExecutionRecord:
    """Keep response order, observed time and validation behind one read seam."""

    def __init__(self, output, record, *, fetch=None, clock=None):
        self.output = output
        self.record = record
        self.checked_at = record["as_of"]
        self._fetch = fetch
        self._clock = clock
        self._remaining = iter(record["responses"]) if fetch is None else None
        self._replay_failure = None

    @classmethod
    def start(cls, output, metadata, fetch, clock):
        output.mkdir(parents=True, exist_ok=False)
        return cls(output, metadata | {"responses": []}, fetch=fetch, clock=clock)

    @classmethod
    def load(cls, output, expected):
        record = json.loads((output / "record.json").read_text())
        checksum = record.pop("sha256")
        if digest(record) != checksum:
            raise DataError("record_integrity_mismatch")
        if any(record.get(key) != value for key, value in expected.items()):
            raise DataError("replay_version_mismatch")
        record["sha256"] = checksum
        return cls(output, record)

    def read(self, url):
        if self._remaining is not None:
            if self._replay_failure:
                raise DataError(self._replay_failure)
            item = next(self._remaining, None)
            if item is None or item["url"] != url:
                self._replay_failure = (
                    "replay_response_missing"
                    if item is None
                    else "replay_request_mismatch"
                )
                raise DataError(self._replay_failure)
            self.checked_at = item["checked_at"]
            if "error" in item:
                raise DataError(item["error"])
            return item["body"]
        item = {"url": url}
        try:
            item["body"] = self._fetch(url)
        except DataError as error:
            item["error"] = str(error)
            raise
        finally:
            self.checked_at = self._clock().isoformat()
            item["checked_at"] = self.checked_at
            self.record["responses"].append(item)
        return item["body"]

    def save(self, inputs, result, render, **metadata):
        self.record.update(metadata, inputs=inputs, result=result)
        self.record["sha256"] = digest(self.record)
        (self.output / "record.json").write_text(
            json.dumps(self.record, indent=2, ensure_ascii=False) + "\n"
        )
        (self.output / "report.md").write_text(render(self.record))
        return self.record

    def verify(self, inputs, result, render):
        if self._replay_failure:
            raise DataError(self._replay_failure)
        if (
            next(self._remaining, None) is not None
            or inputs != self.record["inputs"]
            or result != self.record["result"]
        ):
            raise DataError("replay_result_mismatch")
        if (self.output / "report.md").read_text() != render(self.record):
            raise DataError("replay_report_mismatch")
        return self.record
