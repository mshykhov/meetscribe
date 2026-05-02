#!/usr/bin/env bash
# meetscribe one-line installer. Idempotent - re-running upgrades.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mshykhov/meetscribe/main/bootstrap.sh | bash
# Override the tarball:
#   MEETSCRIBE_TARBALL_URL=https://.../tarball/v0.5.0 curl ... | bash
set -euo pipefail

INSTALL_ROOT="${HOME}/.local/share/meetscribe"
INSTALL_DIR="${INSTALL_ROOT}/install"
VENV_DIR="${INSTALL_ROOT}/.venv"
LOGS_DIR="${INSTALL_ROOT}/logs"
CONFIG_DIR="${HOME}/.config/meetscribe"
BIN_DIR="${HOME}/.local/bin"
LA_DIR="${HOME}/Library/LaunchAgents"
SWIFTBAR_PLUGIN_DIR="${HOME}/Library/Application Support/SwiftBar/Plugins"
TARBALL_URL="${MEETSCRIBE_TARBALL_URL:-https://github.com/mshykhov/meetscribe/tarball/main}"
DOMAIN="gui/$(id -u)"

echo "==> meetscribe installer"

# 1. Prerequisites via Homebrew.
if ! command -v brew >/dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
for pkg in python@3.12 ffmpeg terminal-notifier; do
    brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg"
done
brew list --cask swiftbar >/dev/null 2>&1 || brew install --cask swiftbar || true

# Locate python3.12 (Homebrew-installed; not the system Python).
PY="$(brew --prefix python@3.12)/bin/python3.12"
[ -x "$PY" ] || PY="python3.12"

# 2. Detect fresh vs upgrade.
fresh=1
[ -d "$INSTALL_DIR" ] && fresh=0

# 3. Stop services if upgrading.
if [ "$fresh" = 0 ]; then
    echo "Stopping existing services..."
    launchctl bootout "$DOMAIN/com.myron.meetscribe.watcher" 2>/dev/null || true
    launchctl bootout "$DOMAIN/com.myron.meetscribe.worker" 2>/dev/null || true
fi

# 4. Download + extract tarball.
mkdir -p "$INSTALL_ROOT" "$LOGS_DIR"
TMP_TARBALL="$(mktemp -t meetscribe.XXXXXX).tar.gz"
TMP_EXTRACT="$(mktemp -d -t meetscribe-extract.XXXXXX)"
trap 'rm -f "$TMP_TARBALL"; rm -rf "$TMP_EXTRACT"' EXIT

echo "Downloading $TARBALL_URL..."
curl -fsSL "$TARBALL_URL" -o "$TMP_TARBALL"
tar -xzf "$TMP_TARBALL" -C "$TMP_EXTRACT"
SRC_TOP="$(find "$TMP_EXTRACT" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -d "$SRC_TOP/src" ] || { echo "Tarball missing src/ directory"; exit 1; }

# Atomic swap.
[ -d "${INSTALL_DIR}.old" ] && rm -rf "${INSTALL_DIR}.old"
[ -d "$INSTALL_DIR" ] && mv "$INSTALL_DIR" "${INSTALL_DIR}.old"
mv "$SRC_TOP" "$INSTALL_DIR"
[ -d "${INSTALL_DIR}.old" ] && rm -rf "${INSTALL_DIR}.old"

# 5. Venv + dependencies.
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating venv at $VENV_DIR..."
    "$PY" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
echo "Installing meetscribe + deps..."
"$VENV_DIR/bin/pip" install --quiet -e "$INSTALL_DIR"
"$VENV_DIR/bin/pip" install --quiet "senko @ git+https://github.com/narcotic-sh/senko.git"

# 6. .env.
mkdir -p "$CONFIG_DIR"
NEEDS_HF_TOKEN=0
if [ ! -f "$CONFIG_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$CONFIG_DIR/.env"
    NEEDS_HF_TOKEN=1
fi

# 7. Migrations.
"$VENV_DIR/bin/meetscribe" migrate || true

# 8. Render plists + bootstrap launchd.
mkdir -p "$LA_DIR"
"$VENV_DIR/bin/python" "$INSTALL_DIR/scripts/render_plists.py" \
    --install-dir "$INSTALL_DIR" \
    --venv "$VENV_DIR" \
    --output-dir "$LA_DIR" \
    --logs-dir "$LOGS_DIR"
launchctl bootstrap "$DOMAIN" "$LA_DIR/com.myron.meetscribe.watcher.plist"
launchctl bootstrap "$DOMAIN" "$LA_DIR/com.myron.meetscribe.worker.plist"

# 9. SwiftBar plugin.
if [ -d "/Applications/SwiftBar.app" ]; then
    mkdir -p "$SWIFTBAR_PLUGIN_DIR"
    rm -f "$SWIFTBAR_PLUGIN_DIR/meetscribe.5s.sh"
    ln -sf "$INSTALL_DIR/scripts/meetscribe.5s.sh" "$SWIFTBAR_PLUGIN_DIR/meetscribe.5s.sh"
    defaults write com.ameba.SwiftBar PluginDirectory "$SWIFTBAR_PLUGIN_DIR" 2>/dev/null || true
fi

# 10. ~/.local/bin/meetscribe shim.
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/meetscribe" "$BIN_DIR/meetscribe"

# 11. PATH check.
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo ""; echo "WARNING: $BIN_DIR is not on your PATH."
       echo "Add this to ~/.zshrc:    export PATH=\"\$HOME/.local/bin:\$PATH\""
       ;;
esac

# 12. Summary.
WATCH_DIR="$(grep '^WATCH_DIR=' "$CONFIG_DIR/.env" 2>/dev/null | cut -d= -f2- || echo '~/Videos/OBS')"
WATCH_DIR="${WATCH_DIR/#\~/$HOME}"
mkdir -p "$WATCH_DIR"

echo ""
echo "=========================================="
if [ "$fresh" = 1 ]; then
    echo " meetscribe installed."
else
    echo " meetscribe upgraded."
fi
echo "=========================================="
echo " Drop videos:    $WATCH_DIR"
echo " Inspect state:  meetscribe ls"
echo " Edit config:    meetscribe config"
echo " Web history:    meetscribe web"
echo " Uninstall:      meetscribe self-uninstall"
echo "=========================================="
if [ "$NEEDS_HF_TOKEN" = 1 ]; then
    echo ""
    echo "FIRST-TIME SETUP: set HF_TOKEN before processing videos:"
    echo "  open '$CONFIG_DIR/.env'"
fi
