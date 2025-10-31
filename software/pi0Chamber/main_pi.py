# upd recieving server for pi0
import socket

UDP_IP = "0.0.0.0"
UDP_PORT = 4210

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
print(f"Listening on UDP {UDP_PORT}...")

while True:
    data, addr = sock.recvfrom(1024)  # buffer size 1024 bytes
    try:
        text = data.decode('utf-8').strip()
    except UnicodeDecodeError:
        print("Received non-text packet")
        continue
    # Example payload: "va1:0.300"
    if ':' in text:
        key, val = text.split(':', 1)
        try:
            value = float(val)
        except ValueError:
            print("Bad value:", val)
            continue
        print(f"{key} = {value} from {addr}")
        # --> set LEDs here, e.g. scale to 0..255 PWM
    else:
        print("Unknown format:", text)
