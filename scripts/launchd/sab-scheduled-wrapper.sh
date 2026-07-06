#!/usr/bin/env bash
set -euo pipefail

pipeline=""
scope=""

usage() {
  printf '%s\n' "usage: $0 --pipeline ai-brief|scan|sell --scope KR|US|MIXED" >&2
  printf '%s\n' "scheduled sell delivery requires --pipeline sell --scope MIXED and SELL_AI_BRIEF_REPORT_PATH" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pipeline)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        usage
        exit 2
      fi
      pipeline="${2:-}"
      shift 2
      ;;
    --scope)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        usage
        exit 2
      fi
      scope="${2:-}"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

case "${pipeline}" in
  ai-brief|scan|sell) ;;
  *)
    usage
    exit 2
    ;;
esac

case "${scope}" in
  KR|US|MIXED) ;;
  *)
    usage
    exit 2
    ;;
esac

if [[ "${pipeline}" == "sell" && "${scope}" == "MIXED" && -n "${SELL_AI_BRIEF_REPORT_PATH:-}" ]]; then
  session_date="${SAB_SESSION_DATE:-$(date -u +%F)}"
  exec uv run python -m sab sell-ai-brief-scheduled \
    --sell-ai-brief-report "${SELL_AI_BRIEF_REPORT_PATH}" \
    --scope "${scope}" \
    --session-date "${session_date}" \
    --runner-role "${SAB_RUNNER_ROLE:-local-primary}" \
    --scheduled-tick "${SAB_SCHEDULED_TICK:-manual}" \
    --attempt-id "${SAB_ATTEMPT_ID:-}" \
    --run-url "${SAB_RUN_URL:-}"
fi

if [[ "${pipeline}" == "sell" ]]; then
  printf 'scheduled sell delivery requires SELL_AI_BRIEF_REPORT_PATH and scope=MIXED; got scope=%s\n' "${scope}" >&2
else
  printf 'generic scheduled wrapper requires pipeline-specific execution for pipeline=%s scope=%s\n' "${pipeline}" "${scope}" >&2
fi
exit 2
