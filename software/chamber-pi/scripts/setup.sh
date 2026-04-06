#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  setup.sh — Install update.sh + start.sh, setup Python venv,
#             and run update.
#  Run once on a fresh Pi to bootstrap your repo workflow.
#  Usage: bash setup.sh
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_UPDATE="$SCRIPT_DIR/update.sh"
SOURCE_START="$SCRIPT_DIR/start.sh"
REPO_DIR="$HOME/ORCA-Optical-Replication-Control-Apparatus"
CHAMBER_DIR="$REPO_DIR/software/chamber-pi"
VENV_DIR="$CHAMBER_DIR/.venv"

echo "──────────────────────────────────────"
echo " Setup Script"
echo "──────────────────────────────────────"

# ── 1. Verify scripts exist alongside setup.sh ────────────────
for SCRIPT in "$SOURCE_UPDATE" "$SOURCE_START"; do
    if [ ! -f "$SCRIPT" ]; then
        echo "[ERROR] $(basename $SCRIPT) not found at: $SCRIPT"
        echo "        Make sure all scripts are in the same directory as setup.sh."
        exit 1
    fi
done

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

# ── 3. Install update and start globally ──────────────────────
for ENTRY in "update.sh:update" "start.sh:start"; do
    SRC="$SCRIPT_DIR/${ENTRY%%:*}"
    DEST="/usr/local/bin/${ENTRY##*:}"
    echo "[INFO] Installing $DEST..."
    sudo cp "$SRC" "$DEST"
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to copy $(basename $SRC). Are you running with sudo privileges?"
        exit 1
    fi
    sudo chmod +x "$DEST"
    echo "[SUCCESS] Installed: $DEST"
done

echo "[INFO] You can now run 'update' and 'start' from anywhere."

# ── 4. Run update to clone the repo first ─────────────────────
echo ""
echo "[INFO] Cloning repository..."
echo "──────────────────────────────────────"
/usr/local/bin/update

# ── 5. Install Python venv dependencies ───────────────────────
echo ""
echo "[INFO] Installing Python build dependencies..."
sudo apt install -y python3-venv python3-pip build-essential
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install Python dependencies."
    exit 1
fi
echo "[SUCCESS] Python dependencies installed."

# ── 6. Create venv inside chamber-pi if it doesn't exist ──────
cd "$CHAMBER_DIR" || { echo "[ERROR] Cannot enter $CHAMBER_DIR"; exit 1; }

if [ ! -d "$VENV_DIR" ]; then
    echo "[INFO] Creating virtual environment at: $VENV_DIR"
    python3 -m venv .venv
    if [ $? -eq 0 ]; then
        echo "[SUCCESS] Virtual environment created."
    else
        echo "[ERROR] Failed to create virtual environment."
        exit 1
    fi
else
    echo "[INFO] Virtual environment already exists, skipping creation."
fi

# ── 7. Activate and install requirements ──────────────────────
echo "[INFO] Activating virtual environment..."
source "$VENV_DIR/bin/activate" || { echo "[ERROR] Failed to activate venv."; exit 1; }

echo "[INFO] Installing requirements..."
pip install -r requirements.txt
if [ $? -eq 0 ]; then
    echo "[SUCCESS] Requirements installed."
else
    echo "[ERROR] pip install failed."
    exit 1
fi

echo ""
echo "──────────────────────────────────────"
echo " Setup complete!"
echo " 'update' — pull latest + sync deps"
echo " 'start'  — launch main.py"
echo "──────────────────────────────────────"