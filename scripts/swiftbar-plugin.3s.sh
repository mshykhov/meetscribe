#!/bin/bash
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>

PROJECT_DIR="$HOME/projects/meetscribe"
LOCKFILE="/tmp/com.myron.meetscribe.lock.d/pid"
LOGDIR="$PROJECT_DIR/.logs"
ENV_FILE="$PROJECT_DIR/.env"

if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE" 2>/dev/null)" 2>/dev/null; then
    process_log=$(find "$LOGDIR" -name "process-*.log" -type f 2>/dev/null | sort | tail -1)

    # Determine step number and name
    step_num=1
    step_name="Starting..."
    if [ -n "$process_log" ]; then
        last_step=$(grep -o '\[[1-4]/4\] [A-Za-z]*' "$process_log" 2>/dev/null | tail -1)
        if [ -n "$last_step" ]; then
            step_num=$(echo "$last_step" | grep -o '[1-4]/' | tr -d '/')
            step_name="$last_step"
        fi
        if grep -q "Generating summary" "$process_log" 2>/dev/null; then
            step_num=5
            step_name="[5/5] AI Summary"
        fi
    fi

    # Progress bar
    filled=""
    empty=""
    for i in 1 2 3 4 5; do
        if [ "$i" -le "$step_num" ]; then
            filled="${filled}█"
        else
            empty="${empty}░"
        fi
    done
    progress="${filled}${empty} ${step_num}/5"

    # Filename
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

    # Video duration
    dur_info=""
    if [ -n "$process_log" ]; then
        dur_line=$(grep "Video duration:" "$process_log" 2>/dev/null | head -1)
        if [ -n "$dur_line" ]; then
            dur_info=$(echo "$dur_line" | sed 's/.*Video duration: //')
        fi
    fi

    # Model name
    model=$(grep '^WHISPER_MODEL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
    model="${model:-unknown}"

    # Menu bar - just icon
    ICON_B64=$(cat "$PROJECT_DIR/assets/menubar-icon.b64" 2>/dev/null)
    echo "| templateImage=$ICON_B64"

    # Dropdown
    echo "---"
    echo "Meetscribe - Processing | size=14 color=#4CAF50"
    echo "---"
    if [ -n "$filename" ]; then
        echo "$filename | size=12"
    fi
    echo "$progress | size=12 font=Menlo"
    echo "$step_name | size=12 color=#4CAF50"
    if [ -n "$dur_info" ]; then
        echo "Video: $dur_info | size=11 color=#888888"
    fi
    echo "Model: $model | size=11 color=#888888"
    if [ -n "$elapsed_text" ]; then
        echo "Elapsed: $elapsed_text | size=11 color=#888888"
    fi
    echo "---"
    processed=0
    [ -f "$PROJECT_DIR/.processed" ] && processed=$(wc -l < "$PROJECT_DIR/.processed" | tr -d ' ')
    echo "Total processed: $processed videos | size=11 color=#888888"
    echo "---"
    echo "Cancel processing | bash='kill' param1=$(cat "$LOCKFILE" 2>/dev/null) terminal=false refresh=true color=#FF6B6B"
    echo "---"
    echo "Open output folder | bash='open' param1='$HOME/docs/video' terminal=false"
    echo "Open logs | bash='tail' param1='-f' param2='$LOGDIR/pipeline.log' terminal=true"
    echo "Health check | bash='$PROJECT_DIR/scripts/install.sh' param1='health' terminal=true"
else
    exit 0
fi
