import socket
import struct
import threading
import time
import tkinter as tk
import json

serverName = 'localhost'
serverPort = 12000

clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

HEADER_FORMAT = '!4s B B I I Q H'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
running = True

# ===================== GUI SETUP =====================
root = tk.Tk()
root.title("Grid Clash Client")
root.geometry("500x550")

info_label = tk.Label(root, text="Connecting to server...", font=("Consolas", 12))
info_label.pack(pady=5)

frame = tk.Frame(root)
frame.pack(pady=10)

# 10x10 grid buttons
GRID_SIZE = 10
buttons = [[None for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
cell_owner = [[0 for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]  # track ownership locally
player_id = None  # optional (could be assigned by server)


def update_button_colors():
    """Update colors based on cell_owner values."""
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            val = cell_owner[r][c]
            if val == 0:
                color = "lightgray"
            elif val == 1:
                color = "lightblue"
            elif val == 2:
                color = "lightgreen"
            elif val == 3:
                color = "salmon"
            else:
                color = "plum"
            buttons[r][c].config(bg=color)


def on_cell_click(r, c):
    """Send ACQUIRE_CELL event to server."""
    msg = f"ACQUIRE_CELL {r} {c}".encode()
    data_packet = struct.pack(HEADER_FORMAT, b'DOMX', 1, 2, 0, 0, int(time.time() * 1000), len(msg))
    clientSocket.sendto(data_packet + msg, (serverName, serverPort))
    print(f"[EVENT] Sent ACQUIRE_CELL ({r}, {c})")


# Create grid buttons
for r in range(GRID_SIZE):
    for c in range(GRID_SIZE):
        # Use default arguments in lambda to capture current values of r and c.
        # This avoids late binding issues in Python closures within loops.
        b = tk.Button(frame, text=f"{r},{c}", width=5, height=2,
                      command=lambda r=r, c=c: on_cell_click(r, c))
        b.grid(row=r, column=c, padx=2, pady=2)
        buttons[r][c] = b

# ===================== NETWORKING =====================


def listen_for_snapshots():
    """Continuously listens for incoming snapshots and updates grid."""
    global cell_owner
    while running:
        try:
            data, serverAddress = clientSocket.recvfrom(2048)
            header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
            protocol_id, version, msg_type, snapshot_id, seq_num, timestamp, payload_len = header

            if msg_type in (3, 4, 5):  # FULL / DELTA / HEARTBEAT
                snapshot_data = data[HEADER_SIZE:HEADER_SIZE + payload_len]
                try:
                    grid = json.loads(snapshot_data.decode())
                except Exception:
                    grid = []
                if grid:
                    cell_owner = grid
                    root.after(0, update_button_colors)
                # send ACK
                response = struct.pack(HEADER_FORMAT, b'DOMX', 1, 1, 0, 0, int(time.time() * 1000), 0)
                clientSocket.sendto(response, serverAddress)
        except OSError:
            break
        except Exception as e:
            if running:
                print(f"[Listener Error]: {e}")
            break


# INIT handshake
init_packet = struct.pack(HEADER_FORMAT, b'DOMX', 1, 0, 0, 0, int(time.time() * 1000), 0)
clientSocket.sendto(init_packet, (serverName, serverPort))
info_label.config(text="Sent INIT message")
print("Sent INIT message")

# Wait for ACK
data, serverAddress = clientSocket.recvfrom(1200)
header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
print(f"Received ACK: msg_type={header[2]}")
info_label.config(text="Connected! Waiting for snapshots...")

# Start snapshot listener thread
threading.Thread(target=listen_for_snapshots, daemon=True).start()

# ===================== SHUTDOWN =====================
def on_close():
    global running
    running = False
    time.sleep(0.1)
    try:
        clientSocket.close()
    except:
        pass
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
