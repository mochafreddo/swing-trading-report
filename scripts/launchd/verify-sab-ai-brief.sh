#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

cd "${repo_root}"

plists=(
  "scripts/launchd/com.mochafreddo.sab.ai-brief.us.local-primary.plist"
  "scripts/launchd/com.mochafreddo.sab.ai-brief.us.local-retry.plist"
  "scripts/launchd/com.mochafreddo.sab.ai-brief.us.cutoff-alert.plist"
)

printf '%s\n' "checking launchd plist syntax"
plutil -lint "${plists[@]}"

printf '%s\n' "checking wrapper shell syntax"
bash -n "scripts/launchd/sab-ai-brief-wrapper.sh"

env_file="${SAB_SCHEDULER_ENV_FILE:-.env.scheduler.local}"
if [[ -r "${env_file}" ]]; then
  compose_env_file="${env_file}"
elif [[ -r ".env.example" ]]; then
  compose_env_file=".env.example"
  printf 'scheduler env file not found; using %s for compose structure check only\n' "${compose_env_file}" >&2
else
  printf 'scheduler env file not found and .env.example is unavailable: %s\n' "${env_file}" >&2
  exit 1
fi

printf '%s\n' "checking scheduler compose structure"
SAB_SCHEDULER_ENV_FILE="${compose_env_file}" docker compose \
  -f docker-compose.yml \
  -f docker-compose.scheduler.yml \
  config --quiet

printf '%s\n' "launchd labels to inspect after bootstrap:"
for plist in "${plists[@]}"; do
  label="$(plutil -extract Label raw "${plist}")"
  printf '  launchctl print gui/%s/%s\n' "$(id -u)" "${label}"
done
