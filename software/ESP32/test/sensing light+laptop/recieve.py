"""
ESP32 Bluetooth Serial listener for the VEML7700 sketch.
Two modes:
1) Serial port mode (recommended) - connect to the COM/tty port the OS creates when you pair the device.
2) RFCOMM mode (Linux, optional) - connect directly to BT address using PyBluez.
Usage examples:
  python esp32_bt_listener.py                 # interactively choose a serial port
  python esp32_bt_listener.py --port COM5     # Windows
  python esp32_bt_listener.py --port /dev/tty.SLAB_USBtoUART  # macOS
  python esp32_bt_listener.py --outfile data.csv
  python esp32_bt_listener.py --rfccom 00:11:22:33:44:55  # direct RFCOMM (Linux)
"""
import argparse
import csv
import sys
import time
import threading
import signal

try:
    import serial
    import serial.tools.list_ports
except Exception as e:
    print("pyserial is required. Install with: pip install pyserial")
    raise

# Optional nicer saving (not required)
try:
    import pandas as pd
except:
    pd = None

# Optional PyBluez RFCOMM support (Linux)
try:
    import bluetooth  # pybluez
except:
    bluetooth = None

STOP = threading.Event()

def list_serial_ports():
    ports = serial.tools.list_ports.comports()
    return list(ports)

def choose_port_interactive():
    ports = list_serial_ports()
    if not ports:
        print("No serial ports found. Make sure the ESP32 is paired and a serial port created.")
        return None
    print("Available serial ports:")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p.device} - {p.description}")
    idx = input("Choose port index (or press Enter to cancel): ").strip()
    if idx == "":
        return None
    try:
        i = int(idx)
        return ports[i].device
    except Exception:
        print("Invalid selection.")
        return None

def parse_line(line):
    """
    Parse a line from the ESP32 sketch.
    Expected format: millis,lux1,lux2,avgLux
    Returns dict or None on parse error.
    """
    line = line.strip()
    if not line:
        return None
    # Some error messages are text like "Sensor 1 failed" - return raw message
    parts = line.split(",")
    if len(parts) != 4:
        return {"raw": line}
    try:
        millis = int(float(parts[0]))
        lux1 = float(parts[1])
        lux2 = float(parts[2])
        avg = float(parts[3])
        # Convert millis to an approximate epoch timestamp (local) for convenience:
        ts_epoch = time.time()  # current time in seconds
        return {
            "millis": millis,
            "lux1": lux1,
            "lux2": lux2,
            "avg": avg,
            "recv_time": ts_epoch,
            "raw": line
        }
    except Exception as e:
        return {"raw": line, "error": str(e)}

def serial_reader_loop(port, baud, outfile=None):
    """Read lines from a serial.Serial port and optionally save to CSV."""
    ser = None
    writer = None
    csvfile = None
    while not STOP.is_set():
        try:
            if ser is None:
                print(f"Opening {port} @ {baud}...")
                ser = serial.Serial(port, baud, timeout=2)
                print("Connected.")
                # open CSV file if requested
                if outfile and csvfile is None:
                    csvfile = open(outfile, "a", newline="")
                    writer = csv.writer(csvfile)
                    # write header if file empty
                    if csvfile.tell() == 0:
                        writer.writerow(["recv_iso", "millis", "lux1", "lux2", "avg", "raw"])
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parsed = parse_line(line)
            if "raw" in parsed and len(parsed) == 1:
                # It's some non-CSV message like "Ready!" or "Sensor 1 failed"
                print(f"[MSG] {parsed['raw']}")
                if writer:
                    recv_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                    writer.writerow([recv_iso, "", "", "", "", parsed['raw']])
                    csvfile.flush()
                continue
            # normal CSV data
            recv_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(parsed["recv_time"]))
            print(f"{recv_iso}  millis={parsed['millis']:>8}  lux1={parsed['lux1']:.3f}  lux2={parsed['lux2']:.3f}  avg={parsed['avg']:.3f}")
            if writer:
                writer.writerow([recv_iso, parsed["millis"], parsed["lux1"], parsed["lux2"], parsed["avg"], parsed["raw"]])
                csvfile.flush()
        except serial.SerialException as e:
            print("Serial error:", e)
            if ser:
                try:
                    ser.close()
                except:
                    pass
                ser = None
            print("Reconnecting in 2s...")
            time.sleep(2)
        except KeyboardInterrupt:
            STOP.set()
            break
        except Exception as e:
            print("Unexpected error:", e)
            time.sleep(1)

    if ser:
        try:
            ser.close()
        except:
            pass
    if csvfile:
        csvfile.close()
    print("Serial reader stopped.")

def rfcomm_reader_loop(bt_addr, outfile=None):
    """
    Use PyBluez to connect via RFCOMM directly to a BT address.
    Only works on platforms supporting Bluetooth sockets (Linux).
    """
    if bluetooth is None:
        print("PyBluez not installed. Install with: pip install pybluez")
        return
    sock = None
    writer = None
    csvfile = None
    while not STOP.is_set():
        try:
            if sock is None:
                print(f"Connecting to {bt_addr} RFCOMM port 1...")
                sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                sock.connect((bt_addr, 1))
                sock.settimeout(2.0)
                print("RFCOMM connected.")
                if outfile and csvfile is None:
                    csvfile = open(outfile, "a", newline="")
                    writer = csv.writer(csvfile)
                    if csvfile.tell() == 0:
                        writer.writerow(["recv_iso", "millis", "lux1", "lux2", "avg", "raw"])
            data = sock.recv(1024)
            if not data:
                continue
            lines = data.decode("utf-8", errors="replace").splitlines()
            for line in lines:
                parsed = parse_line(line)
                if "raw" in parsed and len(parsed) == 1:
                    print(f"[MSG] {parsed['raw']}")
                    if writer:
                        recv_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                        writer.writerow([recv_iso, "", "", "", "", parsed['raw']])
                        csvfile.flush()
                    continue
                recv_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(parsed["recv_time"]))
                print(f"{recv_iso}  millis={parsed['millis']:>8}  lux1={parsed['lux1']:.3f}  lux2={parsed['lux2']:.3f}  avg={parsed['avg']:.3f}")
                if writer:
                    writer.writerow([recv_iso, parsed["millis"], parsed["lux1"], parsed["lux2"], parsed["avg"], parsed["raw"]])
                    csvfile.flush()
        except bluetooth.btcommon.BluetoothError as e:
            print("Bluetooth error:", e)
            if sock:
                try:
                    sock.close()
                except:
                    pass
                sock = None
            print("Reconnecting RFCOMM in 3s...")
            time.sleep(3)
        except KeyboardInterrupt:
            STOP.set()
            break
        except Exception as e:
            print("Unexpected error (RFCOMM):", e)
            time.sleep(1)
    if sock:
        try:
            sock.close()
        except:
            pass
    if csvfile:
        csvfile.close()
    print("RFCOMM reader stopped.")

def signal_handler(sig, frame):
    print("Stopping...")
    STOP.set()

def main():
    parser = argparse.ArgumentParser(description="ESP32 Bluetooth/serial listener for lux data.")
    parser.add_argument("--port", "-p", help="Serial port (e.g. COM5 or /dev/tty.SLAB_USBtoUART). If omitted you'll be prompted.")
    parser.add_argument("--baud", "-b", default=115200, type=int, help="Baud rate (default 115200).")
    parser.add_argument("--outfile", "-o", help="Append incoming data to CSV file.")
    parser.add_argument("--rfccom", nargs="?", const=True, help="Use RFCOMM mode with BT address (Linux). Pass address like 00:11:22:33:44:55 or just --rfccom to list availability.")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)

    if args.rfccom:
        # RFCOMM mode
        if args.rfccom is True:
            print("RFCOMM mode requested but no address given. Please pass a Bluetooth address, e.g.:")
            print("  python esp32_bt_listener.py --rfccom 00:11:22:33:44:55")
            sys.exit(1)
        bt_addr = args.rfccom
        rfcomm_reader_loop(bt_addr, outfile=args.outfile)
        return

    port = args.port
    if not port:
        port = choose_port_interactive()
        if not port:
            print("No port chosen. Exiting.")
            sys.exit(0)

    serial_reader_loop(port, args.baud, outfile=args.outfile)

if __name__ == "__main__":
    main()