#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  update.sh — Pull latest changes or clone if not present
#  Place this file at: /usr/local/bin/update  (done by setup.sh)
#  Usage: update
# ─────────────────────────────────────────────────────────────

REPO_URL="git@github.com:harshith998/ORCA-Optical-Replication-Control-Apparatus.git"
REPO_DIR="/root/ORCA-Optical-Replication-Control-Apparatus"

echo "──────────────────────────────────────"
echo " Git Update Script"
echo "──────────────────────────────────────"

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

echo "──────────────────────────────────────"