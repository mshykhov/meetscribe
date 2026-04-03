#!/bin/bash
# Install/uninstall the meetscribe launchd service
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_NAME="com.myron.meetscribe"
PLIST_SRC="$PROJECT_DIR/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
DOMAIN="gui/$(id -u)"

case "${1:-install}" in
    install)
        echo "=== Meetscribe Installer ==="

        # Check prerequisites
        if [ ! -f "$PROJECT_DIR/.env" ]; then
            echo "ERROR: .env not found. Copy .env.example to .env and fill in tokens."
            exit 1
        fi

        if [ ! -d "$PROJECT_DIR/.venv" ]; then
            echo "ERROR: .venv not found. Create it first:"
            echo "  cd $PROJECT_DIR && python3 -m venv .venv && .venv/bin/pip install -e ."
            exit 1
        fi

        # Check ffmpeg
        if ! command -v ffmpeg &>/dev/null; then
            echo "ERROR: ffmpeg not found. Install: brew install ffmpeg"
            exit 1
        fi

        # Create directories
        mkdir -p "$PROJECT_DIR/.logs"

        # Extract WATCH_DIR from .env
        WATCH_DIR=$(grep '^WATCH_DIR=' "$PROJECT_DIR/.env" | cut -d= -f2-)
        WATCH_DIR="${WATCH_DIR:-$HOME/Videos/OBS}"
        mkdir -p "$WATCH_DIR"
        echo "Watch directory: $WATCH_DIR"

        OUTPUT_DIR=$(grep '^OUTPUT_DIR=' "$PROJECT_DIR/.env" | cut -d= -f2-)
        OUTPUT_DIR="${OUTPUT_DIR:-$HOME/docs/video}"
        mkdir -p "$OUTPUT_DIR"
        echo "Output directory: $OUTPUT_DIR"

        # Unload if already loaded
        launchctl bootout "$DOMAIN/$PLIST_NAME" 2>/dev/null || true

        # Install plist
        cp "$PLIST_SRC" "$PLIST_DST"

        # Update WatchPaths in plist to match .env
        /usr/libexec/PlistBuddy -c "Set :WatchPaths:0 $WATCH_DIR" "$PLIST_DST"

        chmod 644 "$PLIST_DST"
        plutil -lint "$PLIST_DST"

        # Load
        launchctl bootstrap "$DOMAIN" "$PLIST_DST"

        # SwiftBar menu bar plugin
        SWIFTBAR_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
        if [ -d "/Applications/SwiftBar.app" ]; then
            mkdir -p "$SWIFTBAR_DIR"
            ln -sf "$PROJECT_DIR/scripts/swiftbar-plugin.1s.sh" "$SWIFTBAR_DIR/meetscribe.1s.sh"
            defaults write com.ameba.SwiftBar PluginDirectory "$SWIFTBAR_DIR"
            echo "SwiftBar plugin linked"
        else
            echo "SwiftBar not found - skip menu bar plugin (brew install --cask swiftbar)"
        fi

        echo ""
        echo "Installed and running!"
        echo "Health: $0 health"
        ;;

    uninstall)
        echo "Uninstalling meetscribe..."
        launchctl bootout "$DOMAIN/$PLIST_NAME" 2>/dev/null || true
        rm -f "$PLIST_DST"
        echo "Done."
        ;;

    status)
        launchctl print "$DOMAIN/$PLIST_NAME" 2>/dev/null || echo "Not loaded"
        ;;

    logs)
        tail -f "$PROJECT_DIR/.logs/pipeline.log"
        ;;

    health)
        echo "=== Meetscribe Health Check ==="
        ok=true

        # 1. launchd service
        if launchctl print "$DOMAIN/$PLIST_NAME" &>/dev/null; then
            echo "[OK] launchd service loaded"
        else
            echo "[FAIL] launchd service NOT loaded. Run: $0 install"
            ok=false
        fi

        # 2. .env
        if [ -f "$PROJECT_DIR/.env" ]; then
            echo "[OK] .env exists"
        else
            echo "[FAIL] .env missing"
            ok=false
        fi

        # 3. HF_TOKEN
        hf_token=$(grep '^HF_TOKEN=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2-)
        if [ -n "$hf_token" ] && [ "$hf_token" != "hf_xxx" ]; then
            echo "[OK] HF_TOKEN configured"
        else
            echo "[FAIL] HF_TOKEN not set in .env"
            ok=false
        fi

        # 4. venv + whisperx
        if "$PROJECT_DIR/.venv/bin/python" -c "import whisperx_mlx" 2>/dev/null; then
            echo "[OK] Python venv + whisperx-mlx"
        else
            echo "[FAIL] venv or whisperx-mlx broken"
            ok=false
        fi

        # 5. ffmpeg
        if command -v ffmpeg &>/dev/null; then
            echo "[OK] ffmpeg installed"
        else
            echo "[FAIL] ffmpeg not found"
            ok=false
        fi

        # 6. claude CLI
        claude_cli=$(grep '^CLAUDE_CLI=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2-)
        claude_cli="${claude_cli:-claude}"
        if [ -x "$claude_cli" ] || command -v "$claude_cli" &>/dev/null; then
            echo "[OK] claude CLI available"
        else
            echo "[FAIL] claude CLI not found at: $claude_cli"
            ok=false
        fi

        # 6b. terminal-notifier
        if command -v terminal-notifier &>/dev/null; then
            echo "[OK] terminal-notifier installed"
        else
            echo "[WARN] terminal-notifier missing (no notifications). brew install terminal-notifier"
        fi

        # 7. Watch dir
        WATCH_DIR=$(grep '^WATCH_DIR=' "$PROJECT_DIR/.env" | cut -d= -f2-)
        WATCH_DIR="${WATCH_DIR:-$HOME/Videos/OBS}"
        if [ -d "$WATCH_DIR" ]; then
            video_count=$(find "$WATCH_DIR" -maxdepth 1 -type f \( -name "*.mkv" -o -name "*.mp4" -o -name "*.webm" -o -name "*.mov" \) 2>/dev/null | wc -l | tr -d ' ')
            echo "[OK] Watch dir exists ($video_count unprocessed videos)"
        else
            echo "[FAIL] Watch dir missing: $WATCH_DIR"
            ok=false
        fi

        # 8. Processed / failed counts
        processed=0
        [ -f "$PROJECT_DIR/.processed" ] && processed=$(wc -l < "$PROJECT_DIR/.processed" | tr -d ' ')
        echo "[INFO] Total processed: $processed videos"
        if [ -f "$PROJECT_DIR/.failed" ] && [ -s "$PROJECT_DIR/.failed" ]; then
            failed_unique=$(sort -u "$PROJECT_DIR/.failed" | wc -l | tr -d ' ')
            echo "[WARN] Failed files: $failed_unique (run: $0 retry)"
        fi

        # 9. Last log entry
        if [ -f "$PROJECT_DIR/.logs/pipeline.log" ]; then
            last_log=$(tail -1 "$PROJECT_DIR/.logs/pipeline.log")
            echo "[INFO] Last log: $last_log"
        fi

        echo ""
        if [ "$ok" = true ]; then
            echo "All checks passed. Pipeline is ready."
        else
            echo "Some checks FAILED. Fix issues above."
        fi
        ;;

    retry)
        echo "Resetting failed files for retry..."
        if [ -f "$PROJECT_DIR/.failed" ]; then
            failed_count=$(sort -u "$PROJECT_DIR/.failed" | wc -l | tr -d ' ')
            rm -f "$PROJECT_DIR/.failed"
            echo "Cleared $failed_count failed entries. Next trigger will retry them."
            echo "Touch the watch dir to trigger: touch \"$(grep '^WATCH_DIR=' "$PROJECT_DIR/.env" | cut -d= -f2-)\""
        else
            echo "No failed files."
        fi
        ;;

    reprocess)
        if [ -z "${2:-}" ]; then
            echo "Usage: $0 reprocess /path/to/video.mp4"
            exit 1
        fi
        video="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
        # Remove from processed log
        if [ -f "$PROJECT_DIR/.processed" ]; then
            grep -vxF "$video" "$PROJECT_DIR/.processed" > "$PROJECT_DIR/.processed.tmp" || true
            mv "$PROJECT_DIR/.processed.tmp" "$PROJECT_DIR/.processed"
        fi
        # Remove from failed log
        if [ -f "$PROJECT_DIR/.failed" ]; then
            grep -vxF "$video" "$PROJECT_DIR/.failed" > "$PROJECT_DIR/.failed.tmp" || true
            mv "$PROJECT_DIR/.failed.tmp" "$PROJECT_DIR/.failed"
        fi
        echo "Removed $video from processed/failed logs."
        echo "Touch the watch dir to trigger reprocessing."
        ;;

    *)
        echo "Usage: $0 {install|uninstall|status|logs|health|retry|reprocess}"
        exit 1
        ;;
esac
