"""Own ordered response recording and offline report replay validation."""

import hashlib
import json
from datetime import datetime, timedelta
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


def report_deadline(calendar):
    """Return the preparation deadline from the verified session, or no deadline."""
    return (
        datetime.fromisoformat(calendar["open"]) - timedelta(minutes=60)
        if calendar
        else None
    )


def verify_readiness(output, record):
    """Validate saved preparation timing without consulting the current clock."""
    timing = json.loads((output / "readiness.json").read_text())
    checksum = timing.pop("sha256")
    if (
        digest(timing) != checksum
        or timing["record_sha256"] != record["sha256"]
        or timing["report_sha256"]
        != hashlib.sha256((output / "report.md").read_bytes()).hexdigest()
    ):
        raise DataError("readiness_integrity_mismatch")
    finished = datetime.fromisoformat(timing["collection_finished_at"])
    ready = datetime.fromisoformat(timing["report_ready_at"])
    if any(
        value.tzinfo is None or value.utcoffset() is None for value in (finished, ready)
    ):
        raise DataError("readiness_timing_mismatch")
    deadline = report_deadline(record["inputs"].get("calendar"))
    if (
        timing["collection_finished_at"] != record["collection_finished_at"]
        or ready < finished
        or timing["report_ready_by"] != (deadline.isoformat() if deadline else None)
        or timing["report_ready_on_time"] != bool(deadline and ready <= deadline)
        or timing["preparation_seconds"] != (ready - finished).total_seconds()
    ):
        raise DataError("readiness_timing_mismatch")
    return timing | {"sha256": checksum}


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
        cutoff = self.record.get("collection_cutoff")
        cutoff = datetime.fromisoformat(cutoff) if cutoff else None
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
            if cutoff and (datetime.fromisoformat(self.checked_at) >= cutoff) != (
                item.get("error") == "report_data_cutoff_reached"
            ):
                self._replay_failure = "replay_cutoff_mismatch"
                raise DataError(self._replay_failure)
            if "error" in item:
                raise DataError(item["error"])
            return item["body"]
        item = {"url": url}
        if cutoff and (checked := self._clock()) >= cutoff:
            self.checked_at = checked.isoformat()
            item.update(
                checked_at=self.checked_at,
                error="report_data_cutoff_reached",
                requested=False,
            )
            self.record["responses"].append(item)
            raise DataError(item["error"])
        try:
            item["body"] = self._fetch(url)
        except DataError as error:
            item["error"] = str(error)
            if str(error) == "report_data_cutoff_reached":
                item["requested"] = False
        finally:
            self.checked_at = self._clock().isoformat()
            item["checked_at"] = self.checked_at
            self.record["responses"].append(item)
        if cutoff and datetime.fromisoformat(self.checked_at) >= cutoff:
            if "error" in item:
                item["request_error"] = item["error"]
            item["error"] = "report_data_cutoff_reached"
        if "error" in item:
            raise DataError(item["error"])
        return item["body"]

    def save(self, inputs, result, render, **metadata):
        self.record.update(
            metadata,
            inputs=inputs,
            result=result,
            collection_finished_at=self._clock().isoformat(),
        )
        self.record["sha256"] = digest(self.record)
        (self.output / "record.json").write_text(
            json.dumps(self.record, indent=2, ensure_ascii=False) + "\n"
        )
        (self.output / "report.md").write_text(render(self.record))
        ready = self._clock()
        deadline = report_deadline(inputs.get("calendar"))
        timing = {
            "record_sha256": self.record["sha256"],
            "report_sha256": hashlib.sha256(
                (self.output / "report.md").read_bytes()
            ).hexdigest(),
            "collection_finished_at": self.record["collection_finished_at"],
            "report_ready_at": ready.isoformat(),
            "report_ready_by": deadline.isoformat() if deadline else None,
            "report_ready_on_time": bool(deadline and ready <= deadline),
            "preparation_seconds": (
                ready - datetime.fromisoformat(self.record["collection_finished_at"])
            ).total_seconds(),
        }
        timing["sha256"] = digest(timing)
        (self.output / "readiness.json").write_text(json.dumps(timing, indent=2) + "\n")
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
        verify_readiness(self.output, self.record)
        return self.record
