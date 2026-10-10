"""Manually deliver a saved report without automatic retries."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

import universe_run
from execution_record import report_deadline, verify_readiness
from single_run import NY, DataError, NoRedirect, credentials_for_run, replay, timestamp


def _save(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


def deliver(
    output: Path,
    *,
    send=None,
    edit_caption=None,
    target=None,
    now=None,
    retry=False,
    confirm=None,
    live=False,
):
    """Record intent before sending; only a user's missing receipt permits retry."""
    with (output / ".delivery.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DataError("delivery_busy") from None
        whole = "markets" in json.loads((output / "record.json").read_text())["rules"]
        record = universe_run.replay(output) if whole else replay(output)
        readiness = verify_readiness(output, record)
        report = (output / "report.md").read_bytes()
        report_hash = hashlib.sha256(report).hexdigest()
        path = output / "delivery.json"
        state = (
            json.loads(path.read_text())
            if path.exists()
            else {
                "version": 1,
                "record_sha256": record["sha256"],
                "report_sha256": report_hash,
                "scope": "universe_report" if whole else "single_symbol_preview",
                "synthetic": record["synthetic"],
                "attempts": [],
            }
        )
        if (
            state["record_sha256"] != record["sha256"]
            or state["report_sha256"] != report_hash
        ):
            raise DataError("delivery_report_changed")
        moment = now or datetime.now(UTC)
        timestamp(moment.isoformat())
        attempts = state["attempts"]
        if confirm is not None:
            if confirm not in {"received", "missing"} or not attempts:
                raise DataError("invalid_receipt_confirmation")
            attempt = attempts[-1]
            if attempt.get("receipt") is not None:
                raise DataError("receipt_already_confirmed")
            attempt["receipt"] = confirm
            attempt["receipt_checked_at"] = moment.isoformat()
            _save(path, state)
            return state
        if send is None or not target:
            raise DataError("delivery_target_missing")
        target_hash = hashlib.sha256(target.encode()).hexdigest()
        if attempts:
            if not retry or attempts[-1].get("receipt") != "missing":
                raise DataError("delivery_requires_user_confirmed_missing")
            if state["target_sha256"] != target_hash:
                raise DataError("delivery_target_changed")
        elif retry:
            raise DataError("delivery_not_previously_attempted")
        state["target_sha256"] = target_hash
        attempt = {
            "number": len(attempts) + 1,
            "transport": "telegram" if live else "simulation",
            "attempted_at": moment.isoformat(),
            "status": "unknown",
            "reason": "interrupted_or_response_unknown",
            "receipt": None,
            "timing": "preview",
            "on_time": False,
            "publication_on_time": False,
            "report_ready_on_time": readiness["report_ready_on_time"],
            "report_ready_at": readiness["report_ready_at"],
        }
        deadline = report_deadline(record["inputs"].get("calendar"))
        if deadline is not None:
            attempt["scheduled_at"] = deadline.isoformat()
        attempts.append(attempt)
        if whole and (
            deadline is None
            or moment > deadline + timedelta(minutes=30)
            or moment.astimezone(NY).date().isoformat() != record["report_date"]
        ):
            attempt.update(
                status="not_sent",
                timing="missed",
                reason="premarket_delivery_window_closed",
            )
            _save(path, state)
            return state
        if whole and live and edit_caption is None:
            raise DataError("delivery_caption_editor_missing")
        _save(path, state)
        delayed = False
        if whole:
            delayed = deadline is not None and (
                moment >= deadline + timedelta(minutes=1)
                or not readiness["report_ready_on_time"]
            )
            caption = f"{'지연 ' if delayed else ''}전체 종목군 보고서 ({record['report_date']})."
            if record["synthetic"]:
                caption = "검증용 사례: " + caption
        else:
            caption = f"미리보기: MU 한 종목 보고서 ({record['report_date']}). 전체 탐색 보고서가 아닙니다."
        sending_at = now or datetime.now(UTC)
        if whole and (
            sending_at > deadline + timedelta(minutes=30)
            or sending_at.astimezone(NY).date().isoformat() != record["report_date"]
        ):
            attempt.update(
                status="not_sent",
                timing="missed",
                reason="premarket_delivery_window_closed",
            )
            _save(path, state)
            return state
        try:
            response = send(report, caption)
            if not isinstance(response, dict):
                raise ValueError()
            if (
                response.get("ok") is False
                and type(response.get("error_code")) is int
                and 400 <= response["error_code"] < 500
            ):
                attempt.update(
                    status="not_sent", reason=f"telegram_{response['error_code']}"
                )
            elif response.get("ok") is True:
                message = response["result"]
                if not isinstance(message, dict):
                    raise ValueError()
                if (
                    type(message["message_id"]) is not int
                    or message["message_id"] <= 0
                    or type(message["date"]) is not int
                ):
                    raise ValueError("invalid_message")
                published = datetime.fromtimestamp(message["date"], UTC)
                if (
                    not moment - timedelta(seconds=60)
                    <= published
                    <= (now or datetime.now(UTC)) + timedelta(seconds=60)
                ):
                    raise ValueError()
                attempt.update(
                    status="sent",
                    reason="api_confirmed",
                    message_id=message["message_id"],
                    published_at=published.isoformat(),
                )
                if deadline is not None:
                    attempt["publication_on_time"] = (
                        deadline <= published < deadline + timedelta(minutes=1)
                        and timestamp(record["as_of"]) <= published
                        and published.astimezone(NY).date().isoformat()
                        == record["report_date"]
                    )
                    attempt["on_time"] = (
                        attempt["publication_on_time"]
                        and readiness["report_ready_on_time"]
                        and timestamp(readiness["report_ready_at"]) <= published
                    )
                    attempt["timing"] = (
                        "opening_minus_60_minutes"
                        if attempt["on_time"]
                        else "delayed"
                        if whole
                        and deadline <= published <= deadline + timedelta(minutes=30)
                        else "missed_deadline"
                        if whole and published > deadline + timedelta(minutes=30)
                        else "preview"
                    )
            else:
                raise ValueError("invalid_response")
        except OSError, ValueError, KeyError, TypeError, OverflowError:
            attempt.update(status="unknown", reason="interrupted_or_response_unknown")
        attempt["response_checked_at"] = (now or datetime.now(UTC)).isoformat()
        _save(path, state)
        if (
            whole
            and attempt["status"] == "sent"
            and (
                attempt["timing"] == "missed_deadline"
                or (attempt["timing"] == "delayed" and not delayed)
            )
        ):
            corrected = (
                ("시한 초과 " if delayed else "시한 초과 지연 ")
                if attempt["timing"] == "missed_deadline"
                else "지연 "
            ) + caption
            attempt["caption_update"] = "unknown"
            _save(path, state)
            if edit_caption is not None:
                try:
                    edited = edit_caption(attempt["message_id"], corrected)
                    message = edited.get("result") if isinstance(edited, dict) else None
                    if (
                        edited.get("ok") is True
                        and isinstance(message, dict)
                        and (
                            message.get("message_id") == attempt["message_id"]
                            and message.get("caption") == corrected
                        )
                    ):
                        attempt["caption_update"] = "updated"
                except OSError, ValueError, KeyError, TypeError, AttributeError:
                    pass
            _save(path, state)
        return state


def _request(token, method, body, content_type):
    try:
        request = Request(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=body,
            headers={"Content-Type": content_type},
        )
        try:
            response = build_opener(NoRedirect).open(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            status = getattr(response, "status", 200)
            if not (200 <= status < 300 or 400 <= status < 500):
                return {"ok": None}
            data = response.read(100_001)
        if len(data) > 100_000:
            raise ValueError()
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        if status >= 400 and (
            value.get("ok") is not False or value.get("error_code") != status
        ):
            return {"ok": None}
        return value
    except OSError, ValueError, HTTPException:
        # The request URL contains the token. Never propagate upstream exceptions.
        return {"ok": None}


def send_document(token, chat_id, report, caption):
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in (("chat_id", chat_id), ("caption", caption)):
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="report.md"\r\nContent-Type: text/markdown; charset=utf-8\r\n\r\n'
    ).encode()
    body += report + f"\r\n--{boundary}--\r\n".encode()
    result = _request(
        token, "sendDocument", body, "multipart/form-data; boundary=" + boundary
    )
    if result.get("ok") is True:
        message = result.get("result")
        if not isinstance(message, dict) or not isinstance(message.get("chat"), dict):
            return {"ok": None}
        chat = message["chat"]
        if chat.get("type") != "private" or str(chat.get("id")) != chat_id:
            return {"ok": None}
    return result


def edit_message_caption(token, chat_id, message_id, caption):
    result = _request(
        token,
        "editMessageCaption",
        json.dumps(
            {"chat_id": chat_id, "message_id": message_id, "caption": caption}
        ).encode(),
        "application/json",
    )
    if result.get("ok") is True:
        message = result.get("result")
        chat = message.get("chat") if isinstance(message, dict) else None
        if (
            not isinstance(chat, dict)
            or chat.get("type") != "private"
            or str(chat.get("id")) != chat_id
        ):
            return {"ok": None}
    return result


def telegram_sender(credentials):
    token = credentials.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = credentials.get("TELEGRAM_CHAT_ID", "")
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token) or not re.fullmatch(
        r"[1-9][0-9]*", chat_id
    ):
        raise DataError("telegram_credentials_invalid")
    chat = _request(
        token, "getChat", json.dumps({"chat_id": chat_id}).encode(), "application/json"
    )
    if (
        chat.get("ok") is not True
        or not isinstance(chat.get("result"), dict)
        or chat["result"].get("type") != "private"
        or str(chat["result"].get("id")) != chat_id
    ):
        raise DataError("telegram_private_chat_unverified")
    return partial(send_document, token, chat_id), token.split(":", 1)[
        0
    ] + ":" + chat_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("send", "retry", "confirm"):
        child = sub.add_parser(command)
        child.add_argument("output", type=Path)
        if command == "confirm":
            child.add_argument("receipt", choices=("received", "missing"))
        else:
            child.add_argument("--credentials-file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "confirm":
            state = deliver(args.output, confirm=args.receipt)
        else:
            credentials = credentials_for_run(
                args.credentials_file,
                False,
                names={"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"},
            )
            sender, target = telegram_sender(credentials)
            state = deliver(
                args.output,
                send=sender,
                edit_caption=partial(
                    edit_message_caption,
                    credentials["TELEGRAM_BOT_TOKEN"],
                    credentials["TELEGRAM_CHAT_ID"],
                ),
                target=target,
                retry=args.command == "retry",
                live=True,
            )
        attempt = state["attempts"][-1]
        print(json.dumps(attempt, ensure_ascii=False))
        return 0 if args.command == "confirm" or attempt["status"] == "sent" else 2
    except OSError, ValueError, KeyError, TypeError:
        print(
            "전송 처리 실패. 설정·보고서·수신 확인 상태를 확인하세요. 자동 재전송하지 않습니다."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
