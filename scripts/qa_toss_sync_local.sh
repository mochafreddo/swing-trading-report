#!/usr/bin/env bash
set -euo pipefail
umask 077

export PATH="${PATH:+${PATH}:}/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/share/mise/shims:${HOME}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${TOSS_SYNC_QA_ENV_FILE:-${repo_root}/.env}"
work_dir="${TOSS_SYNC_QA_WORK_DIR:-}"
remove_work_dir=0
runner_bin="${TOSS_SYNC_QA_RUNNER_BIN:-${repo_root}/scripts/toss_daily_auto_sync.sh}"
python_bin="${TOSS_SYNC_PYTHON_BIN:-python3}"

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

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    printf '%s\n' "${name} must be set for Toss sync QA" >&2
    exit 2
  fi
}

assert_local_supabase() {
  case "${SUPABASE_URL:-}" in
    http://127.0.0.1:* | http://localhost:* | http://[::1]:* | http://host.docker.internal:*)
      return 0
      ;;
  esac
  if [[ "${TOSS_SYNC_QA_ALLOW_NONLOCAL_SUPABASE:-0}" == "1" ]]; then
    return 0
  fi
  printf '%s\n' "refuses to run against non-local SUPABASE_URL: ${SUPABASE_URL:-unset}" >&2
  exit 3
}

assert_loopback_base_url() {
  case "${base_url:-}" in
    http://127.0.0.1:* | http://localhost:* | http://[::1]:*)
      return 0
      ;;
  esac
  if [[ "${TOSS_SYNC_QA_ALLOW_NONLOCAL_BASE_URL:-0}" == "1" ]]; then
    return 0
  fi
  printf '%s\n' "refuses to run against non-local TOSS_SYNC_QA_BASE_URL: ${base_url:-unset}" >&2
  exit 3
}

container_supabase_url() {
  case "${SUPABASE_URL}" in
    http://127.0.0.1:*)
      printf 'http://host.docker.internal:%s\n' "${SUPABASE_URL#http://127.0.0.1:}"
      ;;
    http://localhost:*)
      printf 'http://host.docker.internal:%s\n' "${SUPABASE_URL#http://localhost:}"
      ;;
    *)
      printf '%s\n' "${SUPABASE_URL}"
      ;;
  esac
}

json_body() {
  "${python_bin}" - "$@"
}

curl_config() {
  curl -fsS --config -
}

post_json_with_cookie() {
  local url="$1"
  local body_file="$2"
  curl_config <<CURL_CONFIG
request = "POST"
url = "${url}"
header = "Content-Type: application/json"
header = "Accept: application/json"
header = "Origin: ${base_url}"
cookie = "${cookie_jar}"
cookie-jar = "${cookie_jar}"
data-binary = "@${body_file}"
CURL_CONFIG
}

restore_holdings() {
  if [[ "${restore_needed:-0}" != "1" || ! -s "${backup_yaml:-}" ]]; then
    return 0
  fi
  json_body "${backup_yaml}" > "${restore_body}" <<'PY'
import json
import sys
from pathlib import Path

document = Path(sys.argv[1]).read_text(encoding="utf-8")
json.dump({"document": document, "apply": True}, sys.stdout, separators=(",", ":"))
PY
  post_json_with_cookie "${base_url}/api/holdings/yaml" "${restore_body}" >/dev/null
  printf '%s\n' "restored original holdings YAML"
}

restore_web_container() {
  if [[ "${web_restore_needed:-0}" != "1" ]]; then
    return 0
  fi
  TOSS_SYNC_SOURCE= \
  TOSS_SYNC_QA_FIXTURE_ENABLED= \
  TOSS_SYNC_AUTO_APPLY_ENABLED="${original_toss_sync_auto_apply_enabled:-}" \
  SUPABASE_URL="${original_supabase_url:-}" \
  docker compose up -d --build web >/dev/null
}

cleanup() {
  local status=$?
  set +e
  restore_holdings
  restore_web_container
  rm -f "${cookie_jar:-}" "${login_body:-}" "${seed_body:-}" "${restore_body:-}" "${backup_yaml:-}"
  if [[ "${remove_work_dir:-0}" == "1" && -n "${work_dir:-}" ]]; then
    rmdir "${work_dir}" 2>/dev/null || true
  fi
  exit "${status}"
}

load_env_file "${env_file}"

require_env SUPABASE_URL
require_env SAB_BASIC_AUTH_USER
require_env SAB_BASIC_AUTH_PASS
require_env SAB_SESSION_SECRET
require_env TOSS_SYNC_JOB_TOKEN

if ! command -v "${python_bin}" >/dev/null 2>&1; then
  printf '%s\n' "JSON parser command is not available: ${python_bin}" >&2
  exit 4
fi

web_host_port="${WEB_HOST_PORT:-55300}"
base_url="${TOSS_SYNC_QA_BASE_URL:-http://127.0.0.1:${web_host_port}}"
assert_local_supabase
assert_loopback_base_url

original_supabase_url="${SUPABASE_URL}"
original_toss_sync_auto_apply_enabled="${TOSS_SYNC_AUTO_APPLY_ENABLED:-}"
web_supabase_url="$(container_supabase_url)"
if [[ -z "${work_dir}" ]]; then
  work_dir="$(mktemp -d "${TMPDIR:-/tmp}/toss-sync-qa.XXXXXX")"
  remove_work_dir=1
fi
mkdir -p "${work_dir}"
chmod 700 "${work_dir}"
cookie_jar="${work_dir}/cookies.txt"
login_body="${work_dir}/login.json"
seed_body="${work_dir}/seed.json"
restore_body="${work_dir}/restore.json"
backup_yaml="${work_dir}/holdings.backup.yaml"
restore_needed=0
web_restore_needed=0
trap cleanup EXIT

json_body > "${login_body}" <<'PY'
import json
import os
import sys

json.dump(
    {
        "username": os.environ["SAB_BASIC_AUTH_USER"],
        "password": os.environ["SAB_BASIC_AUTH_PASS"],
    },
    sys.stdout,
    separators=(",", ":"),
)
PY

TOSS_SYNC_SOURCE=fixture \
TOSS_SYNC_QA_FIXTURE_ENABLED=1 \
TOSS_SYNC_AUTO_APPLY_ENABLED=1 \
SUPABASE_URL="${web_supabase_url}" \
docker compose up -d --build web
web_restore_needed=1

curl -fsS -o /dev/null "${base_url}/login"
post_json_with_cookie "${base_url}/api/auth/login" "${login_body}" >/dev/null

curl -fsS --cookie "${cookie_jar}" "${base_url}/api/holdings/yaml" > "${backup_yaml}"
restore_needed=1

json_body > "${seed_body}" <<'PY'
import json
import sys

seed = """version: 1
holdings:
  - ticker: "005930"
    quantity: 1
    entry_price: 69000
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 185
    entry_currency: USD
"""
json.dump({"document": seed, "apply": True}, sys.stdout, separators=(",", ":"))
PY
post_json_with_cookie "${base_url}/api/holdings/yaml" "${seed_body}" >/dev/null

runner_output="$(
  TOSS_SYNC_ENV_FILE="${env_file}" \
  TOSS_SYNC_BASE_URL="${base_url}" \
  WEB_HOST_PORT="${web_host_port}" \
  "${runner_bin}"
)"
printf '%s\n' "${runner_output}"

if [[ "${runner_output}" != *"status=applied"* ]]; then
  printf '%s\n' "Toss sync QA runner did not apply the seeded fixture diff" >&2
  exit 5
fi

holdings_json="$(curl -fsS --cookie "${cookie_jar}" "${base_url}/api/holdings?limit=10")"
json_body "${holdings_json}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
items = payload.get("items") if isinstance(payload, dict) else None
by_ticker = {item.get("ticker"): item for item in items or [] if isinstance(item, dict)}
expected = {
    "005930": {"quantity": 2, "entry_price": 70000},
    "AAPL.NAS": {"quantity": 1, "entry_price": 190},
}
missing = set(expected) - set(by_ticker)
if missing:
    raise SystemExit(f"missing expected QA holdings: {', '.join(sorted(missing))}")
for ticker, values in expected.items():
    row = by_ticker[ticker]
    for field, expected_value in values.items():
        actual = row.get(field)
        if actual != expected_value:
            raise SystemExit(
                f"unexpected QA holding values: {ticker}.{field}={actual!r}"
            )
PY
printf '%s\n' "qa holdings verified"
