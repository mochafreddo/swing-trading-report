#!/usr/bin/env bash
set -euo pipefail

home_dir="${HOME:-}"
export PATH="${PATH:+${PATH}:}/opt/homebrew/bin:/usr/local/bin${home_dir:+:${home_dir}/.local/share/mise/shims:${home_dir}/.local/bin}:/usr/bin:/bin:/usr/sbin:/sbin"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
cd "${repo_root}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"

run_kind=""
expected_at=""
run_id=""
journal_dir=""
grace_seconds=""
stale_seconds=""
dry_run=false
runner_args=()

usage() {
  printf '%s\n' "usage: $0 --run-kind ENTRY|HOLDING --expected-at UTC-RFC3339 --run-id ID --journal-dir DIR --grace-seconds N --stale-seconds N [--dry-run] -- RUNNER [ARGS...]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-kind|--expected-at|--run-id|--journal-dir|--grace-seconds|--stale-seconds)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        usage
        exit 2
      fi
      case "$1" in
        --run-kind) run_kind="$2" ;;
        --expected-at) expected_at="$2" ;;
        --run-id) run_id="$2" ;;
        --journal-dir) journal_dir="$2" ;;
        --grace-seconds) grace_seconds="$2" ;;
        --stale-seconds) stale_seconds="$2" ;;
      esac
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --)
      shift
      runner_args=("$@")
      break
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${run_kind}" || -z "${expected_at}" || -z "${run_id}" || -z "${journal_dir}" || -z "${grace_seconds}" || -z "${stale_seconds}" || ${#runner_args[@]} -eq 0 ]]; then
  usage
  exit 2
fi

dry_run_args=()
if [[ "${dry_run}" == true ]]; then
  dry_run_args=(--dry-run)
fi

exec uv run python -m sab decision-board-journal-run \
  --run-kind "${run_kind}" \
  --expected-at "${expected_at}" \
  --run-id "${run_id}" \
  --journal-dir "${journal_dir}" \
  --grace-seconds "${grace_seconds}" \
  --stale-seconds "${stale_seconds}" \
  "${dry_run_args[@]}" \
  -- "${runner_args[@]}"
