#!/bin/bash
# Starts and stops the studio's local tools. The desktop app calls this; it also works by hand:
#   services.sh list | start <id> | stop <id> | stop-all | status | open-models | open-outputs
#
# A tool counts as running only if this script started it (matching pid and process start time).
# Another program on a port, such as a separate ComfyUI on 8188, is never touched or reused.
set -uo pipefail

SERVICES_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export STUDIO_HOME="${STUDIO_HOME:-$(dirname "$SERVICES_ROOT")}"
# shellcheck source=env.sh
. "$SERVICES_ROOT/env.sh"
BREW_FFMPEG="/opt/homebrew/opt/ffmpeg@8"
SERVICE_DIR="$SERVICES_ROOT/services"
mkdir -p "$RUN_DIR" "$LOG_DIR" "$TMPDIR"

fail() { echo "$*" >&2; exit 1; }

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# Prints the first free port from START, trying ten in a row.
free_port() {
  local port="$1" last=$(( $1 + 9 ))
  while [ "$port" -le "$last" ]; do
    if ! port_in_use "$port"; then echo "$port"; return 0; fi
    port=$(( port + 1 ))
  done
  return 1
}

load_service() {
  local file="$SERVICE_DIR/$1.conf"
  case "$1" in *[!a-z0-9-]*|'') fail "Bad tool name: $1" ;; esac
  [ -f "$file" ] || fail "Tool is not installed: $1"
  # shellcheck disable=SC1090
  . "$file"
}

process_started() { ps -p "$1" -o lstart= 2>/dev/null; }

# True when the pid file names a live process that is still the one this script started,
# not an unrelated program that later received the same pid.
service_running() {
  local id="$1" pid
  [ -f "$RUN_DIR/$id.pid" ] && [ -f "$RUN_DIR/$id.started" ] || return 1
  pid="$(cat "$RUN_DIR/$id.pid")"
  [ "$(process_started "$pid")" = "$(cat "$RUN_DIR/$id.started")" ]
}

service_url() { echo "http://127.0.0.1:$(cat "$RUN_DIR/$1.port")${SERVICE_PATH:-/}"; }

cmd_list() {
  local file first=1
  printf '['
  for file in "$SERVICE_DIR"/*.conf; do
    [ -f "$file" ] || continue
    # shellcheck disable=SC1090
    ( . "$file"; [ "$first" = 1 ] || printf ','; printf '{"id":"%s","title":"%s"}' "$SERVICE_ID" "$SERVICE_TITLE" )
    first=0
  done
  printf ']\n'
}

cmd_start() {
  local id="$1" port pid waited=0
  load_service "$id"
  if service_running "$id"; then
    service_url "$id"
    return 0
  fi
  port="$(free_port "$SERVICE_PORT")" || fail "No free port near $SERVICE_PORT."
  echo "$port" > "$RUN_DIR/$id.port"

  # Output goes to the log, so the app waiting on this script's output is not held open.
  (
    export PORT="$port"
    cd "${SERVICE_CWD:-$STUDIO_HOME}" || exit 1
    service_command
  ) >> "$LOG_DIR/$id.log" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" > "$RUN_DIR/$id.pid"
  process_started "$pid" > "$RUN_DIR/$id.started"
  disown "$pid" 2>/dev/null || true

  local limit="${SERVICE_START_TIMEOUT:-180}"
  until curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$port${SERVICE_HEALTH_PATH:-/}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$RUN_DIR/$id.pid"
      fail "$SERVICE_TITLE stopped during startup. See $LOG_DIR/$id.log"
    fi
    if [ "$waited" -ge "$limit" ]; then
      stop_tree "$pid"
      rm -f "$RUN_DIR/$id.pid"
      fail "$SERVICE_TITLE did not start in $limit s. See $LOG_DIR/$id.log"
    fi
    sleep 2
    waited=$(( waited + 2 ))
  done
  service_url "$id"
}

stop_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do stop_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

cmd_stop() {
  local id="$1" pid waited=0
  if service_running "$id"; then
    pid="$(cat "$RUN_DIR/$id.pid")"
    stop_tree "$pid"
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 10 ]; do
      sleep 1
      waited=$(( waited + 1 ))
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$RUN_DIR/$id.pid" "$RUN_DIR/$id.started" "$RUN_DIR/$id.port"
}

cmd_stop_all() {
  local file id
  for file in "$RUN_DIR"/*.pid; do
    [ -f "$file" ] || continue
    id="$(basename "$file" .pid)"
    cmd_stop "$id"
  done
}

cmd_status() {
  local file
  for file in "$SERVICE_DIR"/*.conf; do
    [ -f "$file" ] || continue
    (
      # shellcheck disable=SC1090
      . "$file"
      if service_running "$SERVICE_ID"; then
        echo "$SERVICE_ID: running at $(service_url "$SERVICE_ID")"
      else
        echo "$SERVICE_ID: stopped"
      fi
    )
  done
}

cmd_open_models() {
  local app
  app="$(ls -d /Applications/Stability*Matrix*.app 2>/dev/null | head -1)"
  if [ -n "$app" ]; then open "$app"; else open "$MODELS_DIR"; fi
}

case "${1:-}" in
  list) cmd_list ;;
  start) [ -n "${2:-}" ] || fail "Usage: services.sh start <id>"; cmd_start "$2" ;;
  stop) [ -n "${2:-}" ] || fail "Usage: services.sh stop <id>"; cmd_stop "$2" ;;
  stop-all) cmd_stop_all ;;
  status) cmd_status ;;
  open-models) cmd_open_models ;;
  open-outputs) mkdir -p "$OUTPUT_DIR"; open "$OUTPUT_DIR" ;;
  *) fail "Usage: services.sh list|start <id>|stop <id>|stop-all|status|open-models|open-outputs" ;;
esac
