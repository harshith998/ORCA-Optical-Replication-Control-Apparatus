# chamber-pi

Raspberry Pi software for the ORCA chamber controller. Controls LED strips via PWM, receives light data from the satellite module over LoRa or RS-485, and serves a live dashboard on port 5000.

---

## First-Time Setup

### 1. Prepare the Pi OS

Install Raspberry Pi OS (64-bit, Bookworm recommended). Then enable SPI and I2C:

```bash
sudo raspi-config
# Interface Options → SPI → Enable
# Interface Options → I2C → Enable
```

### 2. Add SSH key to GitHub

```bash
ssh-keygen -t ed25519 -C "youremail@example.com"
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub   # paste this into GitHub → Settings → SSH Keys
ssh -T git@github.com       # verify
```

### 3. Clone and run setup

```bash
git clone git@github.com:harshith998/ORCA-Optical-Replication-Control-Apparatus.git
bash ORCA-Optical-Replication-Control-Apparatus/software/chamber-pi/scripts/setup.sh
sudo reboot
```

`setup.sh` handles everything: venv creation, dependency install, global commands, UART/PWM config, systemd auto-start, and hotspot profile.

---

## Global Commands

Run `chamber-help` on the Pi for a quick reference. Full list:

| Command | Description |
|---------|-------------|
| `start` | Start ORCA manually (stops systemd service if running) |
| `update` | `git pull` + reinstall global scripts + sync pip deps |
| `hotspot` | Switch to AP mode |
| `wifi <ssid>` | Connect to an open WiFi network |
| `wifi <ssid> <password>` | Connect to a secured WiFi network |
| `chamber-help` | Show all commands with hotspot details |

---

## Networking / Hotspot

The Pi boots into **hotspot mode** by default — no external WiFi required to access the dashboard.

| | |
|---|---|
| SSID | `ORCA-Pi` |
| Password | `orca1234` |
| Pi IP | `10.42.0.1` |
| Dashboard | `http://10.42.0.1:5000` |
| SSH | `ssh pi@10.42.0.1` |

**Connect your laptop to `ORCA-Pi`**, then open the dashboard or SSH in.

### Switching to WiFi

```bash
wifi "NetworkName"              # open network
wifi "NetworkName" "password"   # secured network
```

### Switching back to hotspot

```bash
hotspot
```

The Pi always reboots back into hotspot mode regardless of what it was connected to before.

---

## Systemd Service

ORCA starts automatically on boot via `orca.service`.

```bash
sudo systemctl status orca      # check status
sudo systemctl stop orca        # stop
sudo systemctl restart orca     # restart
sudo journalctl -u orca -f      # live logs
```

---

## Development

```bash
source .venv/bin/activate
python src/main.py

# Tests
python -m pytest tests/
```

### Verify UART assignment (after reboot)

```bash
ls -la /dev/serial0   # must show -> ttyAMA0
```

If it shows `ttyS0`, add `dtoverlay=disable-bt` to `/boot/firmware/config.txt` and reboot.
