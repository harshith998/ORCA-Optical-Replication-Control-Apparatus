#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  data-delete.sh — Wipe all logged data from chamber_data.db
#  Place this file at: /usr/local/bin/data-delete  (done by setup.sh)
#  Usage: data-delete
# ─────────────────────────────────────────────────────────────

REPO_DIR="$HOME/ORCA-Optical-Replication-Control-Apparatus"
CHAMBER_DIR="$REPO_DIR/software/chamber-pi"
DB_PATH="$CHAMBER_DIR/src/chamber_data.db"

echo "──────────────────────────────────────"
echo " ORCA Data Delete"
echo "──────────────────────────────────────"

if [ ! -f "$DB_PATH" ]; then
    echo "[ERROR] Database not found at: $DB_PATH"
    exit 1
fi

echo ""
echo " This will permanently delete ALL rows from:"
echo "   • lux_history"
echo "   • spectral_history"
echo ""
echo " The database file is kept. System settings are not affected."
echo ""
read -r -p " Type YES to confirm: " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
    echo "[ABORTED] No data was deleted."
    exit 0
fi

sqlite3 "$DB_PATH" "DELETE FROM lux_history; DELETE FROM spectral_history; VACUUM;"

if [ $? -eq 0 ]; then
    echo "[SUCCESS] All data deleted and database compacted."
else
    echo "[ERROR] sqlite3 failed. Is sqlite3 installed? (sudo apt install sqlite3)"
    exit 1
fi
