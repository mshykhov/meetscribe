#!/bin/bash
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>

PROJECT_DIR="$HOME/projects/meeting-pipeline"
LOCKFILE="/tmp/com.myron.meeting-pipeline.lock"
LOG="$PROJECT_DIR/.logs/pipeline.log"
PROCESSED="$PROJECT_DIR/.processed"

# Check if currently processing
if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE" 2>/dev/null)" 2>/dev/null; then
    # Active - get current step from log
    step=$(tail -5 "$LOG" 2>/dev/null | grep -o '\[[1-4]/4\].*' | tail -1 | head -c 40)
    if [ -z "$step" ]; then
        step="Processing..."
    fi
    echo ":mic.fill: | sfSymbol=true color=#4CAF50"
    echo "---"
    echo "Processing meeting | color=#4CAF50"
    echo "$step | size=12"

    # Show elapsed time
    start_pid=$(cat "$LOCKFILE" 2>/dev/null)
    if [ -n "$start_pid" ]; then
        ps_start=$(ps -p "$start_pid" -o lstart= 2>/dev/null)
        if [ -n "$ps_start" ]; then
            start_epoch=$(date -j -f "%a %b %d %T %Y" "$ps_start" +%s 2>/dev/null)
            now_epoch=$(date +%s)
            if [ -n "$start_epoch" ]; then
                elapsed=$(( now_epoch - start_epoch ))
                elapsed_min=$(( elapsed / 60 ))
                elapsed_sec=$(( elapsed % 60 ))
                echo "Elapsed: ${elapsed_min}m ${elapsed_sec}s | size=12"
            fi
        fi
    fi
    echo "---"
    echo "Open logs | bash='tail' param1='-f' param2='$LOG' terminal=true"
else
    # Idle - show stats
    processed=0
    [ -f "$PROCESSED" ] && processed=$(wc -l < "$PROCESSED" | tr -d ' ')

    # Check service health
    if launchctl print "gui/$(id -u)/com.myron.meeting-pipeline" &>/dev/null; then
        echo ":mic: | sfSymbol=true"
    else
        echo ":mic.slash: | sfSymbol=true color=#F44336"
        echo "---"
        echo "Service NOT running! | color=#F44336"
        echo "Run install.sh | bash=$PROJECT_DIR/scripts/install.sh param1=install terminal=true"
        exit 0
    fi

    echo "---"
    echo "Meeting Pipeline | size=14"
    echo "Status: idle | color=#888888 size=12"
    echo "Processed: $processed videos | size=12"

    # Last processed
    if [ -f "$PROCESSED" ] && [ -s "$PROCESSED" ]; then
        last=$(tail -1 "$PROCESSED" | xargs basename)
        echo "Last: $last | size=11 color=#888888"
    fi

    echo "---"
    echo "Health check | bash=$PROJECT_DIR/scripts/install.sh param1=health terminal=true"
    echo "Open logs | bash='tail' param1='-f' param2='$LOG' terminal=true"
    echo "Open output folder | bash='open' param1='$HOME/docs/video' terminal=false"
    echo "---"
    echo "Watch: ~/Videos/OBS | size=11 color=#888888"
fi
