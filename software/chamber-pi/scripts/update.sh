#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  update.sh — Pull latest changes or clone if not present,
#              re-install global scripts, then sync venv deps.
#  Place this file at: /usr/local/bin/update  (done by setup.sh)
#  Usage: update
# ─────────────────────────────────────────────────────────────

REPO_URL="git@github.com:harshith998/ORCA-Optical-Replication-Control-Apparatus.git"
REPO_DIR="$HOME/ORCA-Optical-Replication-Control-Apparatus"
CHAMBER_DIR="$REPO_DIR/software/chamber-pi"
SCRIPTS_DIR="$CHAMBER_DIR/scripts"
VENV_DIR="$CHAMBER_DIR/.venv"

echo "──────────────────────────────────────"
echo " Git Update Script"
echo "──────────────────────────────────────"

# ── 1. Pull or clone ───────────────────────────────────────────
if [ -d "$REPO_DIR/.git" ]; then
    echo "[INFO] Repository found at: $REPO_DIR"
    echo "[INFO] Pulling latest changes..."
    cd "$REPO_DIR" || { echo "[ERROR] Cannot enter $REPO_DIR"; exit 1; }

    git pull
    if [ $? -eq 0 ]; then
        echo "[SUCCESS] Repository updated successfully."
    else
        echo "[ERROR] git pull failed. Check your network or SSH keys."
        exit 1
    fi
else
    echo "[INFO] Repository not found at: $REPO_DIR"
    echo "[INFO] Attempting to clone from: $REPO_URL"

    git clone "$REPO_URL" "$REPO_DIR"
    if [ $? -eq 0 ]; then
        echo "[SUCCESS] Repository cloned to: $REPO_DIR"
    else
        echo "[ERROR] git clone failed. Check the URL, network, or SSH keys."
        exit 1
    fi
fi

# ── 2. Re-install global scripts from repo ────────────────────
echo ""
echo "[INFO] Updating global scripts from repo..."
for ENTRY in "update.sh:update" "start.sh:start"; do
    SRC="$SCRIPTS_DIR/${ENTRY%%:*}"
    DEST="/usr/local/bin/${ENTRY##*:}"
    if [ -f "$SRC" ]; then
        sudo cp "$SRC" "$DEST" && sudo chmod +x "$DEST"
        echo "[SUCCESS] Updated: $DEST"
    else
        echo "[WARN] Script not found in repo, skipping: $SRC"
    fi
done

# ── 3. Enter chamber-pi ────────────────────────────────────────
cd "$CHAMBER_DIR" || { echo "[ERROR] Cannot enter $CHAMBER_DIR"; exit 1; }

# ── 4. Activate venv and install requirements ──────────────────
echo ""
echo "[INFO] Activating virtual environment..."
source "$VENV_DIR/bin/activate" || { echo "[ERROR] Failed to activate venv. Has setup.sh been run?"; exit 1; }

echo "[INFO] Installing/updating requirements..."
pip install -r requirements.txt
if [ $? -eq 0 ]; then
    echo "[SUCCESS] Requirements installed."
else
    echo "[ERROR] pip install failed."
    exit 1
fi

echo "──────────────────────────────────────"