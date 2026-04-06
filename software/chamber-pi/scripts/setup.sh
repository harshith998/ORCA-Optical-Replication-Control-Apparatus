#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  setup.sh — Install update.sh and run it
#  Run once on a fresh Pi to bootstrap your repo workflow.
#  Usage: bash setup.sh
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_SCRIPT="$SCRIPT_DIR/update.sh"
INSTALL_PATH="/usr/local/bin/update"

echo "──────────────────────────────────────"
echo " Setup Script"
echo "──────────────────────────────────────"

# ── 1. Verify update.sh exists alongside this script ──────────
if [ ! -f "$SOURCE_SCRIPT" ]; then
    echo "[ERROR] update.sh not found at: $SOURCE_SCRIPT"
    echo "        Make sure update.sh is in the same directory as setup.sh."
    exit 1
fi

# ── 2. Install git if missing ──────────────────────────────────
if ! command -v git &>/dev/null; then
    echo "[INFO] git not found. Installing..."
    sudo apt-get update -qq && sudo apt-get install -y git
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install git."
        exit 1
    fi
    echo "[SUCCESS] git installed."
else
    echo "[INFO] git is already installed: $(git --version)"
fi

# ── 3. Copy update.sh to /usr/local/bin/update ────────────────
echo "[INFO] Copying update.sh to: $INSTALL_PATH"
sudo cp "$SOURCE_SCRIPT" "$INSTALL_PATH"
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to copy script. Are you running with sudo privileges?"
    exit 1
fi

# ── 4. Make it executable ─────────────────────────────────────
sudo chmod +x "$INSTALL_PATH"
echo "[SUCCESS] Installed: $INSTALL_PATH"
echo "[INFO]  You can now run 'update' from anywhere."

# ── 5. Run update now ─────────────────────────────────────────
echo ""
echo "[INFO] Running update now..."
echo "──────────────────────────────────────"
"$INSTALL_PATH"