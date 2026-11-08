#!/usr/bin/env bash
# Demo poll booster: temporarily speed up the assessment/stage sweep.
#
#   ./scripts/demo_poll_boost.sh           # boost to 5s, auto-restore after 1 hour
#   BOOST_INTERVAL_S=10 BOOST_DURATION_S=120 ./scripts/demo_poll_boost.sh
#   ./scripts/demo_poll_boost.sh --restore  # bail out early: restore + recreate now
#
# How it works: sets ASSESSMENT_POLL_INTERVAL_S in the repo-root .env and
# recreates the recruitment-backend container WITHOUT rebuilding (same image,
# env-only change), so the poll loop picks up the new cadence. After
# BOOST_DURATION_S it restores the .env to its exact previous state and
# recreates the container again. No code is touched; nothing needs a merge.
#
# Run it detached (it sleeps for the whole boost window):
#   setsid -f ./scripts/demo_poll_boost.sh </dev/null >>/tmp/demo_poll_boost.log 2>&1
set -euo pipefail

INTERVAL="${BOOST_INTERVAL_S:-5}"
DURATION="${BOOST_DURATION_S:-3600}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
LOCK_FILE="/tmp/demo_poll_boost.lock"
PID_FILE="/tmp/demo_poll_boost.pid"
KEY="ASSESSMENT_POLL_INTERVAL_S"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

set_interval() { # $1 = value; adds the key if missing
    if grep -q "^${KEY}=" "$ENV_FILE"; then
        sed -i "s/^${KEY}=.*/${KEY}=$1/" "$ENV_FILE"
    else
        printf '%s=%s\n' "$KEY" "$1" >>"$ENV_FILE"
    fi
}

restore_previous() { # restores exact previous state (value or key-absent)
    if [[ "$PREV_STATE" == "ABSENT" ]]; then
        sed -i "/^${KEY}=/d" "$ENV_FILE"
    else
        set_interval "$PREV_STATE"
    fi
}

recreate_backend() {
    (cd "$ROOT/backend" && docker compose up -d recruitment-backend >/dev/null)
}

await_poll_log() { # $1 = expected interval; best-effort confirmation
    for _ in $(seq 1 30); do
        if docker logs recruitment-backend --tail=30 2>&1 | grep -q "assessment poll every $1"; then
            log "confirmed: backend polling every ${1}s"
            return 0
        fi
        sleep 1
    done
    log "WARNING: no poll log after 30s (continuing anyway)"
}

read_previous() {
    if grep -q "^${KEY}=" "$ENV_FILE"; then
        grep "^${KEY}=" "$ENV_FILE" | tail -1 | cut -d= -f2
    else
        echo "ABSENT"
    fi
}

if [[ "${1:-}" == "--restore" ]]; then
    PREV_STATE="$(read_previous)"
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        log "stopped booster pid $(cat "$PID_FILE")"
    fi
    # Previous state is unknown here: the booster saved nothing durable, so
    # fall back to the shipped default (300s) rather than guessing.
    set_interval 300
    recreate_backend
    log "restored ${KEY}=300 and recreated backend"
    rm -f "$PID_FILE"
    exit 0
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "a boost is already running; use --restore to end it early"
    exit 1
fi
echo $$ >"$PID_FILE"
PREV_STATE="$(read_previous)"
log "previous state: ${KEY}=${PREV_STATE} (default 300 when absent)"

cleanup() { rm -f "$PID_FILE"; }
trap cleanup EXIT

log "boosting to every ${INTERVAL}s for ${DURATION}s"
set_interval "$INTERVAL"
recreate_backend
await_poll_log "$INTERVAL"

sleep "$DURATION"

log "window over; restoring"
restore_previous
recreate_backend
if [[ "$PREV_STATE" == "ABSENT" ]]; then
    await_poll_log 300
else
    await_poll_log "$PREV_STATE"
fi
log "done"
