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

    # Determine step number and name (4 steps: transcribe, align, diarize, summarize)
    step_num=1
    step_name="Starting..."
    substatus=""
    if [ -n "$process_log" ]; then
        last_step=$(grep -o '\[[1-4]/4\] [A-Za-z]*' "$process_log" 2>/dev/null | tail -1)
        if [ -n "$last_step" ]; then
            step_num=$(echo "$last_step" | grep -o '[1-4]/' | tr -d '/')
            # Strip [N/4] prefix - progress bar already shows the number
            step_name=$(echo "$last_step" | sed 's/\[[1-4]\/4\] //')
        fi

        # Per-stage live details
        case "$step_num" in
            1)
                pct=$(grep -o 'Transcription progress: [0-9.]*%' "$process_log" 2>/dev/null | tail -1 | grep -o '[0-9.]*%')
                if [ -n "$pct" ]; then
                    substatus="Transcription: $pct"
                fi
                ;;
            2)
                pct=$(grep -o 'Progress: [0-9.]*%' "$process_log" 2>/dev/null | tail -1 | grep -o '[0-9.]*%')
                if [ -n "$pct" ]; then
                    substatus="Alignment: $pct"
                fi
                ;;
            3)
                if grep -q "Backend: senko" "$process_log" 2>/dev/null; then
                    substatus="Backend: Senko CoreML"
                elif grep -q "Backend: pyannote" "$process_log" 2>/dev/null; then
                    substatus="Backend: pyannote"
                fi
                ;;
            4)
                chunk=$(grep -o 'Summarizing chunk [0-9]*/[0-9]*' "$process_log" 2>/dev/null | tail -1)
                if [ -n "$chunk" ]; then
                    substatus="$chunk"
                elif grep -q "Merging chunk" "$process_log" 2>/dev/null; then
                    substatus="Merging summaries..."
                else
                    substatus="Generating..."
                fi
                ;;
        esac

        # Detected language
        lang=$(grep -o 'Detected language: [a-z]*' "$process_log" 2>/dev/null | tail -1 | sed 's/Detected language: //')
        if [ -n "$lang" ]; then
            substatus="${substatus:+$substatus | }Lang: $lang"
        fi

        # Segment count (after transcription)
        seg_count=$(grep -o 'Transcript: [0-9]* segments' "$process_log" 2>/dev/null | tail -1 | grep -o '[0-9]*')
        if [ -n "$seg_count" ]; then
            substatus="${substatus:+$substatus | }${seg_count} segments"
        fi
    fi

    # Progress bar
    total_steps=4
    filled=""
    empty=""
    for i in 1 2 3 4; do
        if [ "$i" -le "$step_num" ]; then
            filled="${filled}█"
        else
            empty="${empty}░"
        fi
    done
    progress="${filled}${empty} ${step_num}/${total_steps}"

    # Filename
    pipeline_log="$LOGDIR/pipeline.log"
    filename=""
    filepath=""
    if [ -f "$pipeline_log" ]; then
        filepath=$(grep "Processing:" "$pipeline_log" 2>/dev/null | tail -1 | sed 's/.*Processing: //')
        if [ -n "$filepath" ]; then
            filename=$(basename "$filepath")
        fi
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

    # Menu bar - show step progress
    echo "MS ${step_num}/4 | sfimage=waveform.circle.fill color=#4CAF50"

    # Dropdown
    echo "---"
    echo "Meetscribe - Processing | size=14 color=#4CAF50"
    echo "---"
    if [ -n "$filename" ]; then
        echo "$filename | size=12"
        echo "$filepath | size=9 color=#666666"
    fi
    echo "$progress | size=12 font=Menlo"
    echo "$step_name | size=12 color=#4CAF50"
    case "$step_num" in
        1) echo "Speech-to-text with MLX GPU | size=10 color=#666666" ;;
        2) echo "Word-level timestamp alignment | size=10 color=#666666" ;;
        3) echo "Speaker identification (Senko CoreML) | size=10 color=#666666" ;;
        4) echo "Claude generating summary + action items | size=10 color=#666666" ;;
    esac
    if [ -n "$substatus" ]; then
        echo "$substatus | size=10 color=#88AAFF"
    fi
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
    echo "Skip this video | bash='$PROJECT_DIR/scripts/skip-current.sh' terminal=false refresh=true color=#FF9800"
    echo "Cancel (will retry) | bash='$PROJECT_DIR/scripts/cancel-current.sh' terminal=false refresh=true color=#FF6B6B"
    echo "---"
    echo "Open output folder | bash='open' param1='$HOME/docs/video' terminal=false"
    if [ -n "$process_log" ]; then
        echo "Open process log | bash='open' param1='-a' param2='Console' param3='$process_log' terminal=false"
    fi
    echo "Open pipeline log | bash='open' param1='-a' param2='Console' param3='$LOGDIR/pipeline.log' terminal=false"
    echo "Health check | bash='$PROJECT_DIR/scripts/install.sh' param1='health' terminal=true"
else
    exit 0
fi
