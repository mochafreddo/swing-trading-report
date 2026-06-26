#!/usr/bin/env bash
set -euo pipefail

pipeline=""
scope=""

usage() {
  printf '%s\n' "usage: $0 --pipeline ai-brief|scan|sell --scope KR|US|MIXED" >&2
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

printf 'generic scheduled wrapper requires pipeline-specific execution for pipeline=%s scope=%s\n' "${pipeline}" "${scope}" >&2
exit 2
