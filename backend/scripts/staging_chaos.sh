#!/usr/bin/env bash
# Chaos experiments for the STAGING host (docker-compose.prod.yml). See backend/docs/DEPLOYMENT.md, "Chaos experiments".
#
#   sudo ./backend/scripts/staging_chaos.sh kill-worker  [--seconds 120]
#   sudo ./backend/scripts/staging_chaos.sh delay-db     [--seconds 120] [--delay-ms 300]
#   sudo ./backend/scripts/staging_chaos.sh drop-redis   [--seconds 120]
#   sudo ./backend/scripts/staging_chaos.sh all
#
# Each experiment states what should happen, injects the fault, watches /ready and a probe request, always undoes the
# fault (also on Ctrl-C or error), then checks the system recovered. It refuses to run unless the environment file says
# ZK_ENV=staging (ZK_ENV_FILE, default backend/.env.production) and --yes-this-is-staging is given. Values from the
# environment file are never printed.
set -euo pipefail

cd "$(dirname "$0")/../.."
ENV_FILE="${ZK_ENV_FILE:-backend/.env.production}"
DC=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)
API="${ZK_CHAOS_API:-http://127.0.0.1:8080}"
SECONDS_FAULT=120
DELAY_MS=300
CONFIRMED=0
EXPERIMENT="${1:-}"
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --seconds) SECONDS_FAULT="$2"; shift 2 ;;
    --delay-ms) DELAY_MS="$2"; shift 2 ;;
    --yes-this-is-staging) CONFIRMED=1; shift ;;
    *) echo "Unknown option $1" >&2; exit 2 ;;
  esac
done

refuse() { echo "Refusing: $1" >&2; exit 2; }
[ -f "$ENV_FILE" ] || refuse "no environment file at $ENV_FILE"
grep -Eq '^ZK_ENV=staging[[:space:]]*$' "$ENV_FILE" || refuse "$ENV_FILE is not a staging environment (ZK_ENV=staging)"
[ "$CONFIRMED" = 1 ] || refuse "add --yes-this-is-staging to confirm"

log() { printf '%s  %s\n' "$(date -u +%H:%M:%S)" "$*"; }
ready() { curl -fsS -o /dev/null --max-time 5 "$API/ready"; }
probe() { # a public read through the whole stack (API, database, cache); prints the HTTP status and time
  curl -s -o /dev/null --max-time 10 -w '%{http_code} %{time_total}s' "$API/v1/taxonomy" || echo "000 timeout"
}

watch_for() {
  local until=$(( $(date +%s) + $1 ))
  while [ "$(date +%s)" -lt "$until" ]; do
    if ready; then r=ready; else r=NOT-READY; fi
    log "  /ready: $r   probe: $(probe)"
    sleep 10
  done
}

recovered() {
  for _ in $(seq 1 30); do
    if ready && [ "$(probe | cut -d' ' -f1)" = 200 ]; then log "RECOVERED"; return 0; fi
    sleep 5
  done
  log "NOT RECOVERED after 150s: investigate before the next experiment"; return 1
}

kill_worker() {
  log "kill-worker: expect the API to stay ready; events and timers wait (zk_outbox_oldest_unpublished_seconds grows,"
  log "EventsNotPublished fires after 2 minutes) and are all delivered once the worker is back (nothing lost)."
  trap '"${DC[@]}" start worker >/dev/null' EXIT INT TERM
  "${DC[@]}" kill worker >/dev/null
  watch_for "$SECONDS_FAULT"
  "${DC[@]}" start worker >/dev/null
  trap - EXIT INT TERM
  recovered
}

delay_db() {
  local api_container
  api_container="$("${DC[@]}" ps -q api | head -1)"
  [ -n "$api_container" ] || refuse "the api container is not running"
  log "delay-db: ${DELAY_MS}ms added to every packet the API sends (database included). Expect slower answers and"
  log "possibly SlowSearch/SLO burn alerts, but no 5xx storm; it recovers as soon as the delay is removed."
  local netns=(docker run --rm --net "container:$api_container" --cap-add NET_ADMIN nicolaka/netshoot:v0.13)
  trap '"${netns[@]}" tc qdisc del dev eth0 root >/dev/null 2>&1 || true' EXIT INT TERM
  "${netns[@]}" tc qdisc add dev eth0 root netem delay "${DELAY_MS}ms" 50ms
  watch_for "$SECONDS_FAULT"
  "${netns[@]}" tc qdisc del dev eth0 root >/dev/null 2>&1 || true
  trap - EXIT INT TERM
  recovered
}

drop_redis() {
  log "drop-redis: Redis stopped. Expect the API to stay ready and answer: rate limits fall back to each process,"
  log "the read cache falls back to the database (warnings 'read cache unavailable' in the logs), nothing fails."
  trap '"${DC[@]}" start redis >/dev/null' EXIT INT TERM
  "${DC[@]}" stop redis >/dev/null
  watch_for "$SECONDS_FAULT"
  "${DC[@]}" start redis >/dev/null
  trap - EXIT INT TERM
  recovered
}

ready || refuse "the API at $API is not ready before the experiment; fix that first"
case "$EXPERIMENT" in
  kill-worker) kill_worker ;;
  delay-db) delay_db ;;
  drop-redis) drop_redis ;;
  all) kill_worker && delay_db && drop_redis ;;
  *) echo "Usage: $0 kill-worker|delay-db|drop-redis|all --yes-this-is-staging [--seconds N] [--delay-ms N]" >&2; exit 2 ;;
esac
