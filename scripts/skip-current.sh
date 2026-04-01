#!/bin/bash
# Skip currently processing video - kill handler and mark as processed
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCKFILE="/tmp/com.myron.meetscribe.lock.d/pid"
PIPELINE_LOG="$PROJECT_DIR/.logs/pipeline.log"
PROCESSED_LOG="$PROJECT_DIR/.processed"

if [ ! -f "$LOCKFILE" ]; then
    echo "Nothing is processing"
    exit 0
fi

# Get current file from log
current_file=$(grep "Processing:" "$PIPELINE_LOG" 2>/dev/null | tail -1 | sed 's/.*Processing: //')

# Kill handler
pid=$(cat "$LOCKFILE" 2>/dev/null)
if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null
    # Kill child python process too
    pkill -P "$pid" 2>/dev/null
fi
rm -rf /tmp/com.myron.meetscribe.lock.d

# Mark as processed so it won't retry
if [ -n "$current_file" ]; then
    echo "$current_file" >> "$PROCESSED_LOG"
    echo "Skipped: $current_file"
fi

# Touch watch dir to trigger processing of remaining files
WATCH_DIR="$(grep '^WATCH_DIR=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2-)"
WATCH_DIR="${WATCH_DIR:-$HOME/Videos/OBS}"
sleep 1
touch "$WATCH_DIR"
