# Grid Clash Protocol (DOMX v1)

## Overview
This project implements a UDP-based multiplayer synchronization protocol for the **Grid Clash** game.  
It is part of the CSE361 (Computer Networking) course at Ain Shams University — Project 2: *State Synchronization using UDP*.

The **Grid Clash Protocol (DOMX v1)** enables multiple clients to connect to a central server, compete to claim grid cells, and stay synchronized with low latency using **Delta Encoding**.

---

## 🧩 Features
- UDP-based communication with structured message headers.
- Server broadcasts snapshots (Full, Delta, Heartbeat) at a configurable frequency.
- Delta Encoding strategy — only changed cells are sent.
- Heartbeat messages when no grid changes occur.
- Client GUI (Tkinter) showing a 10×10 clickable grid.
- Automatic GAME_OVER message with winner/loser display.

---

## ⚙️ Requirements
- **Python 3.10+**
- **Tkinter** (preinstalled with most Python distributions)
- **Windows or Linux terminal**

---

## 🧠 Protocol Summary
| Message Type | Code | Direction | Description |
|---------------|-------|------------|--------------|
| INIT | 0 | Client → Server | Client joins |
| ACK | 1 | Client → Server | Snapshot acknowledgment |
| EVENT | 2 | Client → Server | Cell acquisition event and Game over |
| FULL | 3 | Server → Client | Entire grid snapshot |
| DELTA | 4 | Server → Client | Changed cells only |
| HEARTBEAT | 5 | Server → Client | No state change |

---

## Demo Video Link

https://drive.google.com/drive/folders/1vN0y8G6QoTjQEefphvbgA9B2HeaHuAs7?usp=sharing

---

## 🖥️ How to Run Locally (Manual Setup)

### 1. Navigate to the project folder
```bash
cd "C:\Users\Aser\Desktop\Drive\ASU\5th Term FALL 2025\CSE361 - Computer Networking\Grid Clash Protocol\My Try"
```

### 2. Start the server
```bash
python server.py
```

### 3. Launch clients (in separate terminals)
```bash
python client.py
python client.py
python client.py
python client.py
```

Each client will open a **Tkinter grid interface** where cells can be clicked.  
Each click sends an **EVENT** to the server, which updates all clients through **DELTA** or **FULL** snapshots.

### 4. Game Over
When all 100 cells are acquired:
- The server sends a **GAME_OVER** message to all clients.  
- Clients display either:
  - 🏆 *"You won! Winner: Player X"*  
  - ❌ *"You lost! Winner: Player X"*

---

## 🧪 Automated Baseline Local Test

An automated baseline test script is included for demonstration purposes.

### Run the script:
```bash
run_baseline.bat
```

This will:
1. Start the server.
2. Launch 4 clients automatically (each in a new window).
3. Demonstrate the core multiplayer synchronization locally.

---

## 🧰 Files Included
| File | Description |
|------|--------------|
| `server.py` | Main server file handling UDP communication and snapshot broadcasting |
| `client.py` | Client with Tkinter GUI for interacting with the grid |
| `run_baseline.bat` | Automated script to launch the baseline test |
| `README.md` | Project documentation and usage guide |

---

## 🧩 Developer Notes
- Default server port: `12000`
- Max packet size: `1200 bytes`
- Snapshot frequency: 20 Hz (adjustable in `server.py`)
- Protocol ID: `"DOMX"`
- Header format: `!4s B B I I Q H`

---
