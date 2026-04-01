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
PROCESSED_LOG="$PROJECT_DIR/.processed"
LOCKFILE="/tmp/com.myron.meeting-pipeline.lock"
EXTENSIONS="mkv mp4 webm flv mov avi"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

notify() {
    local title="$1"
    local message="$2"
    local sound="${3:-default}"
    terminal-notifier -title "$title" -message "$message" -sound "$sound" -group "meeting-pipeline" 2>/dev/null || true
}

# Prevent parallel runs
if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE")" 2>/dev/null; then
    log "Already running (PID $(cat "$LOCKFILE")), exiting"
    exit 0
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

mkdir -p "$PROJECT_DIR/.logs"
touch "$PROCESSED_LOG"

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

    filename="$(basename "$file")"
    log "New file detected: $file"
    notify "Meeting Pipeline" "Обнаружена новая запись: $filename" "Blow"

    # Wait for recording to finish (OBS holds file open)
    wait_count=0
    while lsof -- "$file" >/dev/null 2>&1; do
        if [ $wait_count -eq 0 ]; then
            log "File still being recorded, waiting..."
            notify "Meeting Pipeline" "Запись ещё идет, жду завершения..." "Blow"
        fi
        sleep 10
        wait_count=$((wait_count + 1))
        if [ $wait_count -ge 360 ]; then
            log "ERROR: Timeout waiting for file after 1 hour: $file"
            notify "Meeting Pipeline" "ОШИБКА: таймаут ожидания записи $filename" "Basso"
            continue 2
        fi
    done

    if [ $wait_count -gt 0 ]; then
        log "Recording finished, starting processing"
        sleep 2  # brief pause after file close
    fi

    # Validate video file
    dur_sec=$(ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null | cut -d. -f1)
    if [ -z "$dur_sec" ] || [ "$dur_sec" -lt 5 ] 2>/dev/null; then
        log "SKIP: File too short or corrupted: $file (${dur_sec:-0}s)"
        notify "Meeting Pipeline" "Пропущен битый/короткий файл: $filename" "Basso"
        echo "$file" >> "$PROCESSED_LOG"
        continue
    fi

    # Process
    log "Processing: $file"
    dur_min=$(( dur_sec / 60 ))
    est_min=$(( dur_min / 5 ))
    [ "$est_min" -lt 1 ] && est_min=1
    notify "Meeting Pipeline" "Обработка ${dur_min}м видео (ETA ~${est_min}м)..." "Blow"
    start_time=$(date +%s)

    process_log="$PROJECT_DIR/.logs/process-$(date +%s).log"
    if "$PROJECT_DIR/.venv/bin/python" -m src.process "$file" >"$process_log" 2>&1; then
        echo "$file" >> "$PROCESSED_LOG"
        elapsed=$(( $(date +%s) - start_time ))
        mins=$(( elapsed / 60 ))
        secs=$(( elapsed % 60 ))

        output_dir=$(grep "Done! Output:" "$process_log" | sed 's/.*Output: //')
        log "Done: $file (${mins}m ${secs}s) -> $(basename "$output_dir")"
        notify "Meeting Pipeline" "Готово за ${mins}м ${secs}с! $(basename "$output_dir")" "Glass"
    else
        log "ERROR: Failed to process: $file"
        log "See details: $process_log"
        tail -5 "$process_log" | while read -r line; do log "  $line"; done
        notify "Meeting Pipeline" "ОШИБКА: $filename. Проверь логи." "Basso"
    fi
done

log "Watch handler finished"
