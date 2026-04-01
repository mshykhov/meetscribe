#!/bin/bash
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>

PROJECT_DIR="$HOME/projects/meetscribe"
LOCKFILE="/tmp/com.myron.meetscribe.lock.d/pid"
LOGDIR="$PROJECT_DIR/.logs"

if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE" 2>/dev/null)" 2>/dev/null; then
    # Find latest process log
    process_log=$(find "$LOGDIR" -name "process-*.log" -type f 2>/dev/null | sort | tail -1)

    # Get current step
    step="Starting..."
    if [ -n "$process_log" ]; then
        last_step=$(grep -o '\[[1-4]/4\].*' "$process_log" 2>/dev/null | tail -1)
        if [ -n "$last_step" ]; then
            step="$last_step"
        fi
        # Check if generating summary
        if grep -q "Generating summary" "$process_log" 2>/dev/null; then
            step="[5/5] AI Summary..."
        fi
    fi

    # Get filename being processed
    pipeline_log="$LOGDIR/pipeline.log"
    filename=""
    if [ -f "$pipeline_log" ]; then
        filename=$(grep "Processing:" "$pipeline_log" 2>/dev/null | tail -1 | sed 's/.*Processing: //' | xargs basename 2>/dev/null)
    fi

    # Elapsed time
    elapsed_text=""
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
                elapsed_text="${elapsed_min}m ${elapsed_sec}s"
            fi
        fi
    fi

    # Menu bar title with icon
    ICON_B64=$(cat "$PROJECT_DIR/assets/menubar-icon.b64" 2>/dev/null)
    echo "$elapsed_text | templateImage=$ICON_B64"
    echo "---"
    if [ -n "$filename" ]; then
        echo "$filename | size=13"
    fi
    echo "$step | size=12 color=#4CAF50"
    if [ -n "$elapsed_text" ]; then
        echo "Elapsed: $elapsed_text | size=12 color=#888888"
    fi
    echo "---"
    echo "One video at a time (sequential) | size=11 color=#888888"
    echo "Open logs | bash='tail' param1='-f' param2='$pipeline_log' terminal=true"
else
    exit 0
fi
