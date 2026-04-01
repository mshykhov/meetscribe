#!/bin/bash
# Install/uninstall the meeting-pipeline launchd service
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_NAME="com.myron.meeting-pipeline"
PLIST_SRC="$PROJECT_DIR/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
DOMAIN="gui/$(id -u)"

case "${1:-install}" in
    install)
        echo "=== Meeting Pipeline Installer ==="

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
            ln -sf "$PROJECT_DIR/scripts/swiftbar-plugin.3s.sh" "$SWIFTBAR_DIR/meeting-pipeline.3s.sh"
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
        echo "Uninstalling meeting-pipeline..."
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
        echo "=== Meeting Pipeline Health Check ==="
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
        if "$PROJECT_DIR/.venv/bin/python" -c "import whisperx" 2>/dev/null; then
            echo "[OK] Python venv + whisperx"
        else
            echo "[FAIL] venv or whisperx broken"
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
        if command -v "$claude_cli" &>/dev/null; then
            echo "[OK] claude CLI available"
        else
            echo "[FAIL] claude CLI not found at: $claude_cli"
            ok=false
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

        # 8. Processed count
        if [ -f "$PROJECT_DIR/.processed" ]; then
            processed=$(wc -l < "$PROJECT_DIR/.processed" | tr -d ' ')
            echo "[INFO] Total processed: $processed videos"
        else
            echo "[INFO] No videos processed yet"
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

    *)
        echo "Usage: $0 {install|uninstall|status|logs|health}"
        exit 1
        ;;
esac
