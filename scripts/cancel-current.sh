#!/bin/bash
# Cancel processing - kill handler, retrigger on next change
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCKFILE="/tmp/com.myron.meetscribe.lock.d/pid"
WATCH_DIR="$(grep '^WATCH_DIR=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2-)"
WATCH_DIR="${WATCH_DIR:-$HOME/Videos/OBS}"

if [ -f "$LOCKFILE" ]; then
    pid=$(cat "$LOCKFILE" 2>/dev/null)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null
        pkill -P "$pid" 2>/dev/null
    fi
    rm -rf /tmp/com.myron.meetscribe.lock.d
fi

# Touch watch dir to trigger launchd retry
sleep 1
touch "$WATCH_DIR"
