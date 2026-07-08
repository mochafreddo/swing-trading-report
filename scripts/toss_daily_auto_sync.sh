#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/share/mise/shims:${HOME}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:${PATH}}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${TOSS_SYNC_ENV_FILE:-${repo_root}/.env}"

cd "${repo_root}"

load_env_file() {
  local file_path="$1"
  if [[ ! -f "${file_path}" ]]; then
    return 0
  fi
  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    local line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    if [[ -z "${line}" || "${line}" == \#* ]]; then
      continue
    fi
    if [[ "${line}" == export[[:space:]]* ]]; then
      line="${line#export }"
    fi
    if [[ "${line}" != *=* ]]; then
      continue
    fi
    local key="${line%%=*}"
    local value="${line#*=}"
    key="${key//[[:space:]]/}"
    if [[ ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      continue
    fi
    value="${value%%[[:space:]]#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    if [[ -z "${!key+x}" ]]; then
      export "${key}=${value}"
    fi
  done < "${file_path}"
}

load_env_file "${env_file}"

curl_config_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\r'/}"
  value="${value//$'\n'/\\n}"
  printf '%s' "${value}"
}

normalize_timezone() {
  case "$1" in
    Asia/Seoul | KST)
      printf '%s\n' "Asia/Seoul"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

detect_current_timezone() {
  if [[ -n "${TOSS_SYNC_CURRENT_TZ_FOR_TEST:-}" ]]; then
    printf '%s\n' "${TOSS_SYNC_CURRENT_TZ_FOR_TEST}"
    return 0
  fi
  if command -v readlink >/dev/null 2>&1 && [[ -L /etc/localtime ]]; then
    local localtime_target
    localtime_target="$(readlink /etc/localtime 2>/dev/null || true)"
    case "${localtime_target}" in
      */Asia/Seoul)
        printf '%s\n' "Asia/Seoul"
        return 0
        ;;
    esac
  fi
  if [[ -f /etc/timezone ]]; then
    local timezone_file_value
    timezone_file_value="$(tr -d '[:space:]' < /etc/timezone)"
    if [[ -n "${timezone_file_value}" ]]; then
      printf '%s\n' "${timezone_file_value}"
      return 0
    fi
  fi
  date +%Z
}

fail_invalid_web_host_port() {
  printf '%s\n' "WEB_HOST_PORT must be an integer from 1 to 65535" >&2
  exit 2
}

expected_timezone="${TOSS_SYNC_EXPECTED_TZ:-Asia/Seoul}"
current_timezone="$(detect_current_timezone)"
if [[ "$(normalize_timezone "${current_timezone}")" != "$(normalize_timezone "${expected_timezone}")" ]]; then
  printf '%s\n' "Host timezone must be ${expected_timezone}; detected ${current_timezone:-unknown}" >&2
  exit 3
fi

web_host_port="${WEB_HOST_PORT:-55300}"
if [[ ! "${web_host_port}" =~ ^[0-9]{1,5}$ ]]; then
  fail_invalid_web_host_port
fi
web_host_port_number=$((10#${web_host_port}))
if (( web_host_port_number < 1 || web_host_port_number > 65535 )); then
  fail_invalid_web_host_port
fi
web_host_port="${web_host_port_number}"
base_url="http://127.0.0.1:${web_host_port}"
endpoint="${base_url}/api/holdings/toss-sync/scheduled"
session_date="${TOSS_SYNC_SESSION_DATE:-$(TZ=Asia/Seoul date +%F)}"

if [[ -z "${TOSS_SYNC_JOB_TOKEN:-}" ]]; then
  printf '%s\n' "TOSS_SYNC_JOB_TOKEN must be set" >&2
  exit 2
fi
job_token="${TOSS_SYNC_JOB_TOKEN}"
unset TOSS_SYNC_JOB_TOKEN
escaped_job_token="$(curl_config_escape "${job_token}")"

python_bin="${TOSS_SYNC_PYTHON_BIN:-python3}"
if ! command -v "${python_bin}" >/dev/null 2>&1; then
  printf '%s\n' "JSON parser command is not available: ${python_bin}" >&2
  exit 4
fi
if ! "${python_bin}" - <<'PY' >/dev/null 2>&1; then
import json
PY
  printf '%s\n' "JSON parser command failed: ${python_bin}" >&2
  exit 4
fi
if ! "${python_bin}" - "${session_date}" <<'PY' >/dev/null 2>&1; then
import datetime as dt
import re
import sys

value = sys.argv[1]
if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
    raise SystemExit(1)
try:
    parsed = dt.date.fromisoformat(value)
except ValueError:
    raise SystemExit(1) from None
if parsed.isoformat() != value:
    raise SystemExit(1)
PY
  printf '%s\n' "TOSS_SYNC_SESSION_DATE must be a valid YYYY-MM-DD date" >&2
  exit 2
fi

response_file="$(mktemp "${TMPDIR:-/tmp}/toss-auto-sync.XXXXXX.json")"
trap 'rm -f "${response_file}"' EXIT

set +e
http_status="$(
  curl -sS \
    --connect-timeout "${TOSS_SYNC_CURL_CONNECT_TIMEOUT_SECONDS:-5}" \
    --max-time "${TOSS_SYNC_CURL_MAX_TIME_SECONDS:-30}" \
    --retry "${TOSS_SYNC_CURL_RETRY:-2}" \
    --retry-delay "${TOSS_SYNC_CURL_RETRY_DELAY_SECONDS:-5}" \
    --retry-all-errors \
    --config - \
    --output "${response_file}" \
    --write-out '%{http_code}' <<CURL_CONFIG
request = "POST"
url = "${endpoint}"
header = "Content-Type: application/json"
header = "Accept: application/json"
header = "Origin: ${base_url}"
header = "Authorization: Bearer ${escaped_job_token}"
data = "{\"mode\":\"auto-apply\",\"sessionDate\":\"${session_date}\"}"
CURL_CONFIG
)"
curl_status=$?
set -e

set +e
summary_line="$(
  "${python_bin}" - "${response_file}" "${http_status:-000}" "${curl_status}" <<'PY'
import json
import sys
from pathlib import Path

response_path = Path(sys.argv[1])
http_status = sys.argv[2] or "000"
curl_status = int(sys.argv[3])

payload = {}
raw = response_path.read_text(encoding="utf-8") if response_path.exists() else ""
if raw.strip():
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError:
        candidate = {}
    if isinstance(candidate, dict):
        payload = candidate

status = str(payload.get("status") or "error")
summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
blocked = payload.get("blockedRows") if isinstance(payload.get("blockedRows"), list) else []
quarantined = payload.get("quarantinedTickers") if isinstance(payload.get("quarantinedTickers"), list) else []
quarantined_count = payload.get("quarantinedCount")
if not isinstance(quarantined_count, int):
    quarantined_count = len(quarantined)
print(
    "http={http_status} status={status} incoming={incoming} create={create} update={update} "
    "delete={delete} quarantined={quarantined} unchanged={unchanged} blocked={blocked}".format(
        http_status=http_status,
        status=status,
        incoming=summary.get("incomingCount", 0),
        create=summary.get("createCount", 0),
        update=summary.get("updateCount", 0),
        delete=summary.get("deleteCount", 0),
        quarantined=quarantined_count,
        unchanged=summary.get("unchangedCount", 0),
        blocked=len(blocked),
    )
)
http_ok = http_status.isdigit() and 200 <= int(http_status) < 300
raise SystemExit(
    0 if curl_status == 0 and http_ok and status in {"applied", "unchanged"} else 1
)
PY
)"
parse_status=$?
set -e
printf '%s\n' "${summary_line}"
exit "${parse_status}"
