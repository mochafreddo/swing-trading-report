#!/usr/bin/env bash
set -euo pipefail

pipeline=""
scope=""

usage() {
  printf '%s\n' "usage: $0 --pipeline ai-brief|scan|sell --scope KR|US|MIXED [pipeline-specific args]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pipeline)
      pipeline="${2:-}"
      shift 2
      ;;
    --scope)
      scope="${2:-}"
      shift 2
      ;;
    *)
      break
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
