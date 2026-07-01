#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${TOSS_SYNC_ENV_FILE:-${repo_root}/.env.scheduler.local}"

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

web_host_port="${WEB_HOST_PORT:-55300}"
base_url="http://127.0.0.1:${web_host_port}"
endpoint="${base_url}/api/holdings/toss-sync/scheduled"

if [[ -z "${TOSS_SYNC_JOB_TOKEN:-}" ]]; then
  printf '%s\n' "TOSS_SYNC_JOB_TOKEN must be set" >&2
  exit 2
fi

response_file="$(mktemp "${TMPDIR:-/tmp}/toss-auto-sync.XXXXXX.json")"
trap 'rm -f "${response_file}"' EXIT

set +e
http_status="$(
  curl -sS \
    -X POST "${endpoint}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "Origin: ${base_url}" \
    -H "Authorization: Bearer ${TOSS_SYNC_JOB_TOKEN}" \
    --data '{"mode":"auto-apply"}' \
    --output "${response_file}" \
    --write-out '%{http_code}'
)"
curl_status=$?
set -e

set +e
summary_line="$(
  uv run python - "${response_file}" "${http_status:-000}" "${curl_status}" <<'PY'
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
print(
    "http={http_status} status={status} incoming={incoming} create={create} update={update} "
    "delete={delete} unchanged={unchanged} blocked={blocked}".format(
        http_status=http_status,
        status=status,
        incoming=summary.get("incomingCount", 0),
        create=summary.get("createCount", 0),
        update=summary.get("updateCount", 0),
        delete=summary.get("deleteCount", 0),
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
