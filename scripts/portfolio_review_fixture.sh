#!/usr/bin/env bash
# Separate synthetic servers for manual UX. No inherited credentials or root env.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_port="${PORTFOLIO_FIXTURE_WEB_PORT:-43217}"
data_port="${PORTFOLIO_FIXTURE_DATA_PORT:-43218}"
for port in "$web_port" "$data_port"; do
  if [[ ! "$port" =~ ^[0-9]{4,5}$ ]] || (( port < 1024 || port > 65535 )); then
    echo 'Invalid fixture port' >&2
    exit 1
  fi
done
if [[ "$web_port" == "$data_port" ]]; then
  echo 'Fixture ports must differ' >&2
  exit 1
fi
node_bin="$(command -v node)"
fixture_pid=''
web_pid=''
cleanup() {
  if [[ -n "$web_pid" ]]; then kill "$web_pid" 2>/dev/null || true; fi
  if [[ -n "$fixture_pid" ]]; then kill "$fixture_pid" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
cd "$repo_dir/web"
env -i PATH="$PATH" "$node_bin" e2e/decision-board-fixture-server.mjs "$data_port" &
fixture_pid=$!
# Direct Next CLI avoids a child process wrapper that could outlive this script.
env -i PATH="$PATH" SAB_SKIP_ROOT_ENV=1 SAB_PORTFOLIO_R2_FIXTURE=1 \
  SAB_BASIC_AUTH_USER=fixture-admin SAB_BASIC_AUTH_PASS=fixture-password \
  SAB_SESSION_SECRET=fixture-session-secret-at-least-32-bytes \
  SAB_SESSION_COOKIE_SECURE=false SAB_TRUST_HOST_HEADER_FOR_LOCAL_REQUESTS=1 \
  SUPABASE_URL="http://127.0.0.1:$data_port" SUPABASE_SECRET_KEY=sb_secret_fixture_only \
  SUPABASE_REPORTS_BUCKET=reports REPORT_SEARCH_WINDOW=100 RUN_DISPATCH_ENABLED=0 \
  NEXT_TELEMETRY_DISABLED=1 \
  "$node_bin" node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port "$web_port" &
web_pid=$!
echo "Synthetic review: http://127.0.0.1:$web_port/today#stored-review"
echo 'Public fixture login: fixture-admin / fixture-password. Stop with Ctrl-C.'
# Bash 5 is already required by the repository toolchain.
wait -n "$fixture_pid" "$web_pid"
