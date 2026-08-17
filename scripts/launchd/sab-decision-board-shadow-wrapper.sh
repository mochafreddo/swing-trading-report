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
gate_manifest=""
gate_manifest_sha256=""
input_ledger=""
expected_action_ledger=""
dry_run=false
runner_args=()

usage() {
  printf '%s\n' "usage: $0 --run-kind ENTRY|HOLDING --expected-at UTC-RFC3339 --run-id ID --journal-dir DIR --grace-seconds N --stale-seconds N [--gate-manifest PATH --gate-manifest-sha256 HASH --input-ledger PATH --expected-action-ledger PATH] [--dry-run] -- RUNNER [ARGS...]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-kind|--expected-at|--run-id|--journal-dir|--grace-seconds|--stale-seconds|--gate-manifest|--gate-manifest-sha256|--input-ledger|--expected-action-ledger)
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
        --gate-manifest) gate_manifest="$2" ;;
        --gate-manifest-sha256) gate_manifest_sha256="$2" ;;
        --input-ledger) input_ledger="$2" ;;
        --expected-action-ledger) expected_action_ledger="$2" ;;
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

gate_manifest_args=()
if [[ -n "${gate_manifest}" || -n "${gate_manifest_sha256}" || -n "${input_ledger}" || -n "${expected_action_ledger}" ]]; then
  if [[ -z "${gate_manifest}" || -z "${gate_manifest_sha256}" ]]; then
    usage
    exit 2
  fi
  gate_manifest_args=(--gate-manifest "${gate_manifest}" --gate-manifest-sha256 "${gate_manifest_sha256}")
  if [[ -n "${input_ledger}" || -n "${expected_action_ledger}" ]]; then
    if [[ -z "${input_ledger}" || -z "${expected_action_ledger}" ]]; then
      usage
      exit 2
    fi
    gate_manifest_args+=(--input-ledger "${input_ledger}" --expected-action-ledger "${expected_action_ledger}")
  fi
fi

exec uv run python -m sab decision-board-journal-run \
  --run-kind "${run_kind}" \
  --expected-at "${expected_at}" \
  --run-id "${run_id}" \
  --journal-dir "${journal_dir}" \
  --grace-seconds "${grace_seconds}" \
  --stale-seconds "${stale_seconds}" \
  "${gate_manifest_args[@]}" \
  "${dry_run_args[@]}" \
  -- "${runner_args[@]}"
