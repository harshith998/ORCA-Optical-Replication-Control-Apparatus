#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  start.sh — Activate the venv and run main.py
#  Place this file at: /usr/local/bin/start  (done by setup.sh)
#  Usage: start
# ─────────────────────────────────────────────────────────────

REPO_DIR="$HOME/ORCA-Optical-Replication-Control-Apparatus"
CHAMBER_DIR="$REPO_DIR/software/chamber-pi"
VENV_DIR="$CHAMBER_DIR/.venv"

echo "──────────────────────────────────────"
echo " Starting ORCA"
echo "──────────────────────────────────────"

# ── 1. Enter chamber-pi ────────────────────────────────────────
cd "$CHAMBER_DIR" || { echo "[ERROR] Cannot enter $CHAMBER_DIR"; exit 1; }

# ── 2. Activate venv ───────────────────────────────────────────
echo "[INFO] Activating virtual environment..."
source "$VENV_DIR/bin/activate" || { echo "[ERROR] Failed to activate venv. Has setup.sh been run?"; exit 1; }

# ── 3. Run main.py ─────────────────────────────────────────────
echo "[INFO] Running main.py..."
echo "──────────────────────────────────────"
python main.py