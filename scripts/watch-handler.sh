#!/bin/bash
# Handler script invoked by launchd when WATCH_DIR changes.
# Finds new video files, waits for recording to finish, processes them.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load only needed config (don't export secrets)
WATCH_DIR="$(grep '^WATCH_DIR=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
WATCH_DIR="${WATCH_DIR:-$HOME/Videos/OBS}"
OUTPUT_DIR="$(grep '^OUTPUT_DIR=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
OUTPUT_DIR="${OUTPUT_DIR:-$HOME/docs/video}"
PROCESSED_LOG="$PROJECT_DIR/.processed"
FAILED_LOG="$PROJECT_DIR/.failed"
LOCKDIR="/tmp/com.myron.meetscribe.lock.d"
MAX_RETRIES=3
EXTENSIONS="mkv mp4 webm flv mov avi"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

notify() {
    local title="$1"
    local message="$2"
    local sound="${3:-default}"
    terminal-notifier -title "$title" -message "$message" -sound "$sound" -group "meetscribe" \
        -appIcon "$PROJECT_DIR/assets/icon.png" 2>/dev/null || true
}

# Atomic lock via mkdir (POSIX atomic operation)
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    # Check if owning process is still alive
    if [ -f "$LOCKDIR/pid" ] && kill -0 "$(cat "$LOCKDIR/pid")" 2>/dev/null; then
        log "Already running (PID $(cat "$LOCKDIR/pid")), exiting"
        exit 0
    fi
    # Stale lock - remove and retry
    rm -rf "$LOCKDIR"
    if ! mkdir "$LOCKDIR" 2>/dev/null; then
        log "Cannot acquire lock, exiting"
        exit 0
    fi
fi
echo $$ > "$LOCKDIR/pid"
trap 'rm -rf "$LOCKDIR"' EXIT

mkdir -p "$PROJECT_DIR/.logs"
touch "$PROCESSED_LOG"
touch "$FAILED_LOG"

# Protect against OUTPUT_DIR == WATCH_DIR
real_watch="$(cd "$WATCH_DIR" 2>/dev/null && pwd -P || echo "$WATCH_DIR")"
real_output="$(cd "$OUTPUT_DIR" 2>/dev/null && pwd -P || echo "$OUTPUT_DIR")"
if [ "$real_watch" = "$real_output" ]; then
    log "ERROR: WATCH_DIR and OUTPUT_DIR are the same directory! Aborting."
    notify "Meetscribe" "ОШИБКА: WATCH_DIR == OUTPUT_DIR!" "Basso"
    exit 1
fi

# Cleanup old process logs (keep last 20)
find "$PROJECT_DIR/.logs" -name "process-*.log" -type f | sort -r | tail -n +21 | xargs rm -f 2>/dev/null || true

# Cleanup orphaned tmp transcripts
find "$OUTPUT_DIR" -maxdepth 1 -name ".tmp-*-transcript.txt" -mmin +60 -delete 2>/dev/null || true

# Build find pattern for video extensions
find_args=()
first=true
for ext in $EXTENSIONS; do
    if [ "$first" = true ]; then
        find_args+=(-name "*.$ext")
        first=false
    else
        find_args+=(-o -name "*.$ext")
    fi
done

# Find new video files
find "$WATCH_DIR" -maxdepth 1 -type f \( "${find_args[@]}" \) | while read -r file; do
    # Skip already processed
    if grep -qxF "$file" "$PROCESSED_LOG"; then continue; fi

    # Skip files that exceeded max retries
    fail_count=0
    if [ -s "$FAILED_LOG" ]; then
        fail_count=$(grep -cxF "$file" "$FAILED_LOG" || true)
    fi
    if [ "$fail_count" -ge "$MAX_RETRIES" ]; then
        log "SKIP: $file exceeded $MAX_RETRIES retries"
        continue
    fi

    filename="$(basename "$file")"
    log "New file detected: $file (attempt $(( fail_count + 1 ))/$MAX_RETRIES)"
    notify "Meetscribe" "Новая запись: $filename" "Blow"

    # Wait for recording to finish (OBS holds file open)
    wait_count=0
    while lsof -- "$file" >/dev/null 2>&1; do
        if [ $wait_count -eq 0 ]; then
            log "File still being recorded, waiting..."
            notify "Meetscribe" "Запись идет, жду завершения..." "Blow"
        fi
        sleep 10
        wait_count=$((wait_count + 1))
        if [ $wait_count -ge 360 ]; then
            log "ERROR: Timeout waiting for file after 1 hour: $file"
            notify "Meetscribe" "ОШИБКА: таймаут записи $filename" "Basso"
            continue 2
        fi
    done

    if [ $wait_count -gt 0 ]; then
        log "Recording finished, starting processing"
        sleep 2
    fi

    # Validate video file
    dur_sec=$(ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null | head -1 | cut -d. -f1)
    if [ -z "$dur_sec" ] || ! [ "$dur_sec" -ge 5 ] 2>/dev/null; then
        log "SKIP: File too short or corrupted: $file (${dur_sec:-0}s)"
        notify "Meetscribe" "Пропущен битый/короткий файл: $filename" "Basso"
        echo "$file" >> "$PROCESSED_LOG"
        continue
    fi

    # Process
    log "Processing: $file"
    dur_min=$(( dur_sec / 60 ))
    est_min=$(( dur_min / 5 ))
    [ "$est_min" -lt 1 ] && est_min=1
    notify "Meetscribe" "Обработка ${dur_min}м видео (ETA ~${est_min}м)..." "Blow"
    start_time=$(date +%s)

    process_log="$PROJECT_DIR/.logs/process-$(date +%s).log"
    if "$PROJECT_DIR/.venv/bin/python" -m src.process "$file" >"$process_log" 2>&1; then
        echo "$file" >> "$PROCESSED_LOG"
        elapsed=$(( $(date +%s) - start_time ))
        mins=$(( elapsed / 60 ))
        secs=$(( elapsed % 60 ))

        output_dir=$(grep "Done! Output:" "$process_log" | sed 's/.*Output: //')
        log "Done: $file (${mins}m ${secs}s) -> $(basename "$output_dir")"
        notify "Meetscribe" "Готово за ${mins}м ${secs}с! $(basename "$output_dir")" "Glass"
    else
        echo "$file" >> "$FAILED_LOG"
        fail_count=$((fail_count + 1))
        log "ERROR: Failed to process: $file (attempt $fail_count/$MAX_RETRIES)"
        log "See details: $process_log"
        tail -5 "$process_log" | while read -r line; do log "  $line"; done
        if [ "$fail_count" -ge "$MAX_RETRIES" ]; then
            notify "Meetscribe" "ОШИБКА: $filename провалился $MAX_RETRIES раз. Пропущен." "Basso"
        else
            notify "Meetscribe" "ОШИБКА: $filename (попытка $fail_count/$MAX_RETRIES)" "Basso"
        fi
    fi
done

log "Watch handler finished"
