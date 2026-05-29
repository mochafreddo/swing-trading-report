#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/share/mise/shims:${HOME}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

repo_root=""
env_file=""
market=""
schedule_role=""
runner_role=""
scheduled_tick=""
dry_run="false"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

usage() {
  printf '%s\n' "usage: $0 --repo-root PATH --env-file PATH --market KR|US --schedule-role ROLE --runner-role ROLE --scheduled-tick HHMM [--dry-run]" >&2
}

trim_value() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

load_host_alert_env() {
  if [[ ! -r "${env_file}" ]]; then
    return 0
  fi

  local line key value
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="$(trim_value "${line}")"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    if [[ "${line}" == export\ * ]]; then
      line="${line#export }"
    fi
    [[ "${line}" != *=* ]] && continue
    key="$(trim_value "${line%%=*}")"
    value="$(trim_value "${line#*=}")"
    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    case "${key}" in
      TELEGRAM_BOT_TOKEN) TELEGRAM_BOT_TOKEN="${value}" ;;
      TELEGRAM_CHAT_ID) TELEGRAM_CHAT_ID="${value}" ;;
    esac
  done < "${env_file}"
}

send_host_failure_alert() {
  local reason="$1"
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    return 0
  fi
  local text
  text="[SAB][ai-brief][host-failure]
market=${market}
schedule_role=${schedule_role}
runner_role=${runner_role}
reason=${reason}"
  curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    -d disable_web_page_preview=true >/dev/null || true
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="${2:-}"
      shift 2
      ;;
    --env-file)
      env_file="${2:-}"
      shift 2
      ;;
    --market)
      market="${2:-}"
      shift 2
      ;;
    --schedule-role)
      schedule_role="${2:-}"
      shift 2
      ;;
    --runner-role)
      runner_role="${2:-}"
      shift 2
      ;;
    --scheduled-tick)
      scheduled_tick="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${repo_root}" || -z "${env_file}" || -z "${market}" || -z "${schedule_role}" || -z "${runner_role}" || -z "${scheduled_tick}" ]]; then
  usage
  exit 2
fi

cd "${repo_root}"
mkdir -p logs/launchd

guard_status=0
uv run python -m sab ai-brief-scheduled \
  --market "${market}" \
  --schedule-role "${schedule_role}" \
  --runner-role "${runner_role}" \
  --scheduled-tick "${scheduled_tick}" \
  --guard-only > "logs/launchd/${market}-${schedule_role}.guard.log" 2>&1 || guard_status=$?

if [[ "${guard_status}" -eq 75 ]]; then
  exit 0
fi
if [[ "${guard_status}" -ne 0 ]]; then
  load_host_alert_env
  send_host_failure_alert "guard_failed"
  printf 'guard failed before env/docker preflight: status=%s\n' "${guard_status}" >&2
  exit "${guard_status}"
fi

SAB_SCHEDULER_ENV_FILE="${env_file}"
if [[ ! -r "${SAB_SCHEDULER_ENV_FILE}" ]]; then
  printf 'scheduler env file is missing or unreadable: %s\n' "${SAB_SCHEDULER_ENV_FILE}" >&2
  exit 1
fi

load_host_alert_env

if ! docker info >/dev/null 2>&1; then
  send_host_failure_alert "docker_daemon_unavailable"
  exit 1
fi

attempt_id="${scheduled_tick}-$(date -u +%Y%m%dT%H%M%SZ)-host$$"
cmd=(
  docker compose
  -f docker-compose.yml
  -f docker-compose.scheduler.yml
  run
  --rm
  scheduler
  uv run python -m sab ai-brief-scheduled
  --market "${market}"
  --schedule-role "${schedule_role}"
  --runner-role "${runner_role}"
  --scheduled-tick "${scheduled_tick}"
  --attempt-id "${attempt_id}"
)
if [[ "${dry_run}" == "true" ]]; then
  cmd+=(--dry-run)
fi

printf 'running command:' > "logs/launchd/${market}-${schedule_role}.cmd.log"
printf ' %q' "${cmd[@]}" >> "logs/launchd/${market}-${schedule_role}.cmd.log"
printf '\n' >> "logs/launchd/${market}-${schedule_role}.cmd.log"

if ! SAB_SCHEDULER_ENV_FILE="${SAB_SCHEDULER_ENV_FILE}" "${cmd[@]}"; then
  send_host_failure_alert "scheduler_container_failed"
  exit 1
fi
