#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  setup.sh — Install update + start globally, setup Python venv
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

# ── 4. Clone the repo (git pull/clone only, no venv yet) ──────
echo ""
echo "[INFO] Cloning/updating repository..."
echo "──────────────────────────────────────"

REPO_URL="git@github.com:harshith998/ORCA-Optical-Replication-Control-Apparatus.git"
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR" && git pull
else
    git clone "$REPO_URL" "$REPO_DIR"
fi
if [ $? -ne 0 ]; then
    echo "[ERROR] git operation failed."
    exit 1
fi

# ── 5. Install Python build dependencies ──────────────────────
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

# ── 7. Assign PL011 (good UART) to GPIO pins, disable mini-UART and BT ───
# By default the PL011 (/dev/ttyAMA0) is claimed by Bluetooth and the
# weaker mini-UART (/dev/ttyS0) is routed to BCM 14/15.  We want the
# opposite: PL011 on BCM 14 TX / BCM 15 RX, mini-UART and BT disabled.
#
# dtoverlay=disable-bt  — detaches BT from PL011, routes PL011 to GPIO
# enable_uart=1         — ensures the UART is active (required on Pi 3/4/5)
# dtoverlay=disable-miniuart-bt is NOT used; disable-bt is sufficient.

CONFIG_FILE='/boot/firmware/config.txt'
# Fall back to legacy path on older Pi OS images
[ -f "$CONFIG_FILE" ] || CONFIG_FILE='/boot/config.txt'

echo "[INFO] Configuring $CONFIG_FILE for PL011 on BCM 14/15..."
for LINE in 'dtoverlay=disable-bt' 'enable_uart=1'; do
    if ! grep -qF "$LINE" "$CONFIG_FILE"; then
        echo "$LINE" | sudo tee -a "$CONFIG_FILE" > /dev/null
        echo "[SUCCESS] Added: $LINE"
    else
        echo "[INFO] Already present: $LINE"
    fi
done

# Disable the Bluetooth UART service so it no longer holds /dev/ttyAMA0
sudo systemctl disable --now hciuart 2>/dev/null || true
echo "[SUCCESS] hciuart service disabled."
echo "[INFO] A reboot is required for the UART reassignment to take effect."
echo "       After reboot, verify: ls -la /dev/serial0  (should show -> ttyAMA0)"

# ── 8. Free UART from serial console so Python can use it exclusively ─
# By default Pi OS puts a kernel console and a getty login shell on the
# UART.  Both must be removed or they will fight with rs_receiver.py.
#
#  cmdline.txt: remove 'console=serial0,115200' kernel parameter
#  systemd:     disable serial-getty@ttyAMA0 login service

CMDLINE_FILE='/boot/firmware/cmdline.txt'
[ -f "$CMDLINE_FILE" ] || CMDLINE_FILE='/boot/cmdline.txt'

echo "[INFO] Removing serial console from $CMDLINE_FILE..."
if grep -q 'console=serial0' "$CMDLINE_FILE"; then
    # sed in-place: strip the console=serial0,<baud> token (with or without trailing space)
    sudo sed -i 's/console=serial0,[0-9]* \?//g' "$CMDLINE_FILE"
    echo "[SUCCESS] Removed console=serial0 from $CMDLINE_FILE"
else
    echo "[INFO] console=serial0 not present in $CMDLINE_FILE — nothing to remove."
fi

echo "[INFO] Disabling serial-getty on ttyAMA0..."
sudo systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true
echo "[SUCCESS] serial-getty@ttyAMA0 disabled."

# ── 9. Add user to dialout group for persistent UART access ───
# Group membership survives udev permission resets; no sudo needed at runtime.
if groups "$USER" | grep -qw dialout; then
    echo "[INFO] $USER is already in the dialout group."
else
    sudo usermod -aG dialout "$USER"
    echo "[SUCCESS] Added $USER to dialout group (takes effect after reboot)."
fi

# ── 10. Install systemd service to auto-start ORCA on boot ───
# Creates /etc/systemd/system/orca.service and enables it.
# After reboot, ORCA starts automatically. Useful commands:
#   sudo systemctl status orca   — check if running
#   sudo systemctl stop orca     — stop it
#   sudo journalctl -u orca -f   — live log output

SERVICE_FILE='/etc/systemd/system/orca.service'
echo "[INFO] Writing $SERVICE_FILE..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ORCA Chamber Controller
After=network.target

[Service]
Type=simple
User=$USER
ExecStart=/usr/local/bin/start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable orca
echo "[SUCCESS] orca.service installed and enabled — will start on next boot."

# ── 12. Run update to activate venv and install requirements ──
echo ""
echo "[INFO] Running update to install requirements..."
echo "──────────────────────────────────────"
/usr/local/bin/update


echo ""
echo "──────────────────────────────────────"
echo " Setup complete!"
echo " 'update' — pull latest + sync deps"
echo " 'start'  — launch main.py"
echo ""
echo " *** REBOOT REQUIRED ***"
echo " Run: sudo reboot"
echo " Then verify: ls -la /dev/serial0"
echo " Expected:    /dev/serial0 -> ttyAMA0"
echo ""
echo " ORCA will start automatically on boot."
echo " To check status:  sudo systemctl status orca"
echo " To view logs:     sudo journalctl -u orca -f"
echo "──────────────────────────────────────"