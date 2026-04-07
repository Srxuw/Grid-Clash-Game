import socket
import threading
import time
import struct
import json
import csv
import psutil
import os
from collections import defaultdict
from datetime import datetime

# Output directory for metrics CSV files (can be set via METRICS_OUTPUT_DIR env var)
METRICS_OUTPUT_DIR = os.environ.get('METRICS_OUTPUT_DIR', '.')

serverPort = 12000
# socket.AF_INET – Address Family for IPv4. 
# socket.SOCK_DGRAM – Socket type for UDP (User Datagram Protocol).
serverSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Bind the socket to the server address and port
serverSocket.bind(('', serverPort))

print(f"Server Started on port number {serverPort}")

# Target 20 Hz, slight overclock to 21 Hz to compensate for system scheduling overhead
frequency = 21
TICK_INTERVAL = 1 / frequency

clients = {}  # Track connected clients
clientNumber = 0     # PROBLEM

rows, cols = 5, 5
grid = [[0 for _ in range(cols)] for _ in range(rows)]
numberOfClicks = 0  # Use for checking if Game is Over
gameOver = False

# Metrics tracking for CSV
metrics_data = []
client_recv_times = defaultdict(list)  # Track packet arrival times per client
client_latencies = defaultdict(list)  # Track latencies per client

# Player colors mapping (for display)
PLAYER_COLORS = {
    1: "Blue", 2: "Green", 3: "Salmon", 4: "Plum",
    5: "Purple", 6: "Orange", 7: "Pink", 8: "Cyan"
}

# '!4sB B I I Q H' = protocol_id, version, msg_type, snapshot_id, seq_num, timestamp, payload_len
HEADER_FORMAT = '!4s B B I I Q H'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

modifiedFlag = True  # Tracks if the grid was modified

# Message type name mapping
MSG_TYPE_NAMES = {0: 'INIT', 1: 'ACK', 2: 'EVENT', 3: 'FULL', 4: 'DELTA', 5: 'HEARTBEAT', 6: 'GAME_OVER'}

# Server CPU monitoring - initialize and prime cpu_percent
server_process = psutil.Process()
last_server_cpu = psutil.cpu_percent(interval=0.1)  # Prime with blocking call
server_cpu_sample_count = 0

# Authoritative position log (Section 6 compliance)
authoritative_positions = []  # [(timestamp_ms, grid_state), ...]


# ======================================
# Helper Function: Log Authoritative Position
# ======================================
def log_authoritative_position(timestamp_ms, grid_state):
    """Log server's authoritative position with timestamp (Section 6)."""
    global authoritative_positions
    authoritative_positions.append((timestamp_ms, [row[:] for row in grid_state]))
    # Keep only last 1000 positions
    if len(authoritative_positions) > 1000:
        authoritative_positions.pop(0)


# ======================================
# Helper Function: Log Metrics for All Packets
# ======================================
def log_packet_metrics(client_id, msg_type, snapshot_id, seq_num, server_timestamp, recv_time=None, 
                       packet_size=0, is_sent=True):
    """Log metrics for any packet type (INIT, ACK, FULL, DELTA, HEARTBEAT, etc.)"""
    if recv_time is None:
        recv_time = int(time.time() * 1000)
    
    latency = recv_time - server_timestamp if server_timestamp > 0 else 0
    
    # Calculate jitter if we have previous receive times
    jitter = 0
    if client_id in client_recv_times and len(client_recv_times[client_id]) >= 2:
        inter_arrival = recv_time - client_recv_times[client_id][-1]
        if len(client_recv_times[client_id]) >= 2:
            prev_inter_arrival = client_recv_times[client_id][-1] - client_recv_times[client_id][-2]
            jitter = abs(inter_arrival - prev_inter_arrival)
    
    # Calculate perceived position error based on latency variance
    perceived_error = 0
    if client_id in client_latencies and len(client_latencies[client_id]) >= 2:
        recent_latencies = client_latencies[client_id][-5:]
        if len(recent_latencies) >= 2:
            latency_variance = max(recent_latencies) - min(recent_latencies)
            # Scale: 10ms variance = 1 unit of position error
            perceived_error = min(latency_variance / 10.0, 10.0)
    
    # Get CPU usage (system-wide, 0-100%)
    global server_cpu_sample_count, last_server_cpu
    try:
        server_cpu_sample_count += 1
        # Every 10th call, do a proper measurement with small interval
        if server_cpu_sample_count % 10 == 0:
            cpu_usage = psutil.cpu_percent(interval=0.05)
        else:
            cpu_usage = psutil.cpu_percent(interval=None)
        
        # Keep last known good value
        if cpu_usage > 0:
            last_server_cpu = cpu_usage
        else:
            cpu_usage = last_server_cpu
    except:
        cpu_usage = last_server_cpu
    
    bandwidth_kbps = (packet_size * 8 * frequency) / 1024 if packet_size > 0 else 0
    
    # Track times for this client
    client_recv_times[client_id].append(recv_time)
    if latency > 0:
        client_latencies[client_id].append(latency)
    
    metrics_data.append({
        'client_id': client_id,
        'msg_type': msg_type,
        'msg_type_name': MSG_TYPE_NAMES.get(msg_type, 'UNKNOWN'),
        'snapshot_id': snapshot_id,
        'seq_num': seq_num,
        'server_timestamp_ms': server_timestamp,
        'recv_time_ms': recv_time,
        'latency_ms': latency,
        'jitter_ms': jitter,
        'perceived_position_error': perceived_error,
        'cpu_percent': cpu_usage,
        'bandwidth_per_client_kbps': bandwidth_kbps
    })


# ======================================
# CSV Logging Function
# ======================================
def save_metrics_to_csv():
    """Save all collected metrics to a CSV file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(METRICS_OUTPUT_DIR, f"game_metrics_{timestamp}.csv")
    
    # Ensure output directory exists
    os.makedirs(METRICS_OUTPUT_DIR, exist_ok=True)
    
    try:
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = [
                'client_id', 'msg_type', 'msg_type_name', 'snapshot_id', 'seq_num', 
                'server_timestamp_ms', 'recv_time_ms', 'latency_ms', 'jitter_ms', 
                'perceived_position_error', 'cpu_percent', 'bandwidth_per_client_kbps'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in metrics_data:
                writer.writerow(row)
        
        print(f"\n[CSV] Metrics saved to {filename}")
        return filename
    except Exception as e:
        print(f"[ERROR] Failed to save CSV: {e}")
        return None


def save_authoritative_positions():
    """Save authoritative positions to a CSV file for Section 6 position error analysis."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(METRICS_OUTPUT_DIR, f"authoritative_positions_{timestamp}.csv")
    
    # Ensure output directory exists
    os.makedirs(METRICS_OUTPUT_DIR, exist_ok=True)
    
    try:
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = ['timestamp_ms', 'row', 'col', 'player']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for entry in authoritative_positions:
                ts = entry['timestamp_ms']
                grid_state = entry['grid']
                for r, row in enumerate(grid_state):
                    for c, cell in enumerate(row):
                        if cell > 0:
                            writer.writerow({
                                'timestamp_ms': ts,
                                'row': r,
                                'col': c,
                                'player': cell
                            })
        
        print(f"[CSV] Authoritative positions saved to {filename}")
        return filename
    except Exception as e:
        print(f"[ERROR] Failed to save authoritative positions: {e}")
        return None


# ======================================
# Calculate Winner and Leaderboard
# ======================================
def calculate_leaderboard():
    """Count cells owned by each player and return sorted leaderboard."""
    scores = defaultdict(int)
    
    for row in grid:
        for cell in row:
            if cell > 0:
                scores[cell] += 1
    
    # Sort by score (descending)
    leaderboard = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return leaderboard


# ======================================
# Send Game Over Message
# ======================================
def broadcast_game_over():
    """Send game over message with leaderboard to all clients."""
    global gameOver
    gameOver = True
    
    leaderboard = calculate_leaderboard()
    
    # Prepare leaderboard data
    leaderboard_data = {
        "status": "GAME_OVER",
        "leaderboard": []
    }
    
    print("\n" + "="*50)
    print("GAME OVER - Final Leaderboard:")
    print("="*50)
    
    for rank, (player_id, score) in enumerate(leaderboard, 1):
        color = PLAYER_COLORS.get(player_id, f"Player{player_id}")
        print(f"{rank}. Player #{player_id} ({color}): {score} cells")
        leaderboard_data["leaderboard"].append({
            "rank": rank,
            "player_id": player_id,
            "color": color,
            "score": score
        })
    
    print("="*50 + "\n")
    
    # Broadcast to all clients (msg_type=6 for GAME_OVER)
    game_over_payload = json.dumps(leaderboard_data).encode()
    payloadLen = len(game_over_payload)
    
    for client_addr, info in list(clients.items()):
        info['seq'] += 1
        game_over_packet = struct.pack(
            HEADER_FORMAT, b'DOMX', 1, 6, 0, info['seq'],
            int(time.time() * 1000), payloadLen
        )
        serverSocket.sendto(game_over_packet + game_over_payload, client_addr)
    
    # Save metrics to CSV
    print("[SERVER] Saving metrics to CSV...")
    csv_file = save_metrics_to_csv()
    if csv_file:
        print(f"[SERVER] Game data saved successfully!")
    
    # Save authoritative positions for Section 6 analysis
    pos_file = save_authoritative_positions()
    if pos_file:
        print(f"[SERVER] Authoritative positions saved!")


# ======================================
# Delta Encoding Functions
# ======================================
def calculate_delta_changes(old_grid, new_grid):
    """
    Calculate what cells changed between old and new grid states.
    Returns list of changes in format: [player_id, row, col]
    """
    changes = []
    for r in range(len(new_grid)):
        for c in range(len(new_grid[r])):
            if old_grid[r][c] != new_grid[r][c]:
                # Cell changed: send new player_id, row, col
                changes.append([new_grid[r][c], r, c])
    return changes


def encode_delta_payload(changes):
    """
    Encode delta changes as space-separated string.
    Format: "player_id row col player_id row col ..."
    Example: "1 3 4 2 1 2" means player 1 took (3,4) and player 2 took (1,2)
    """
    if not changes:
        return ""
    
    # Flatten the changes list and join with spaces
    flat_changes = []
    for change in changes:
        flat_changes.extend([str(change[0]), str(change[1]), str(change[2])])
    
    return " ".join(flat_changes)


def decode_delta_payload(delta_string, current_grid):
    """
    Apply delta changes to current grid state.
    delta_string format: "player_id row col player_id row col ..."
    """
    if not delta_string.strip():
        return current_grid
    
    # Parse the delta string
    parts = delta_string.split()
    if len(parts) % 3 != 0:
        print(f"[ERROR] Invalid delta format: {delta_string}")
        return current_grid
    
    # Apply changes
    new_grid = [row[:] for row in current_grid]  # Deep copy
    for i in range(0, len(parts), 3):
        try:
            player_id = int(parts[i])
            row = int(parts[i + 1])
            col = int(parts[i + 2])
            
            if 0 <= row < len(new_grid) and 0 <= col < len(new_grid[0]):
                new_grid[row][col] = player_id
                print(f"[DELTA] Applied change: Player {player_id} -> ({row},{col})")
            else:
                print(f"[ERROR] Invalid coordinates in delta: ({row},{col})")
        except ValueError as e:
            print(f"[ERROR] Invalid delta values: {e}")
    
    return new_grid


# ======================================
# Broadcast Thread
# ======================================
def broadcast_snapshots():
    """Periodically broadcast current game state to all clients."""
    global modifiedFlag
    
    next_tick_time = time.time()
    
    while not gameOver:
        next_tick_time += TICK_INTERVAL
        
        # Only send snapshots if there are connected clients
        if len(clients) > 0:
            # Only increment snapshot ID once per broadcast cycle (represents new state)
            
            for client_addr, info in list(clients.items()):
                # Reliability: Check for 10 consecutive unacked heartbeats (assume client is dead)
                if info['consecutive_unacked_heartbeats'] >= 10:
                    print(f"[TIMEOUT] Client {client_addr} (Player #{info['client number']}) - 10 consecutive unacked heartbeats. Disconnecting.")
                    del clients[client_addr]
                    continue
                
                snapshot_time = int(time.time() * 1000)

                # Reliability: Check if previous snapshot was not ACKed - resend from buffer FIRST
                if len(info['packets_awaiting_ack']) > 0 and len(info['snapshot_buffer']) > 0:
                    # Resend the oldest unacked packet from buffer
                    oldest_unacked = min(info['packets_awaiting_ack'])
                    buffered_packets = [pkt for pkt in info['snapshot_buffer'] if pkt[0] == oldest_unacked]
                    if buffered_packets:
                        pkt_snapshot_id, pkt_seq_num, pkt_payload, pkt_header = buffered_packets[0]
                        # Increment seq_num for retransmit
                        info['seq'] += 1
                        
                        # Reconstruct header with new seq_num for retransmit
                        retransmit_header = struct.pack(
                            HEADER_FORMAT, b'DOMX', 1, 4, pkt_snapshot_id, info['seq'],
                            snapshot_time, len(pkt_payload)
                        )
                        serverSocket.sendto(retransmit_header + pkt_payload, client_addr)
                        
                        # Log retransmit metrics
                        total_packet_size = len(retransmit_header) + len(pkt_payload)
                        log_packet_metrics(
                            info['client number'],
                            msg_type=4,  # DELTA retransmit
                            snapshot_id=pkt_snapshot_id,
                            seq_num=info['seq'],
                            server_timestamp=snapshot_time,
                            packet_size=total_packet_size
                        )
                        print(f"[RETRANSMIT] DELTA snapshot_id={pkt_snapshot_id}, seq={info['seq']} to Player #{info['client number']}")
                        continue  # Skip new packet, retry old one

                # Send delta snapshot if grid was modified (msg_type=4)
                if modifiedFlag:
                    # Increment per-client snapshot_id for DELTA
                    info['snapshot_id'] += 1
                    
                    # Increment seq_num before sending new DELTA
                    info['seq'] += 1
                    
                    # TRUE DELTA ENCODING: Calculate only what changed for this client
                    changes = calculate_delta_changes(info['last_grid_sent'], grid)
                    delta_payload_string = encode_delta_payload(changes)
                    snapshot_payload = delta_payload_string.encode()  # Send only changes, not full grid
                    
                    # Update this client's last known grid state
                    info['last_grid_sent'] = [row[:] for row in grid]  # Deep copy current grid
                    
                    payloadLen = len(snapshot_payload)
                    snapshot_packet = struct.pack(
                        HEADER_FORMAT, b'DOMX', 1, 4, info['snapshot_id'], info['seq'],
                        snapshot_time, payloadLen
                    )
                    serverSocket.sendto(snapshot_packet + snapshot_payload, client_addr)
                    
                    # Reliability: Buffer this packet and track it
                    info['snapshot_buffer'].append((info['snapshot_id'], info['seq'], snapshot_payload, snapshot_packet))
                    if len(info['snapshot_buffer']) > 3:
                        info['snapshot_buffer'].pop(0)  # Keep only last 3
                    info['packets_awaiting_ack'].add(info['snapshot_id'])
                    
                    # Log DELTA metrics
                    total_packet_size = len(snapshot_packet) + payloadLen
                    log_packet_metrics(
                        info['client number'],
                        msg_type=4,  # DELTA
                        snapshot_id=info['snapshot_id'],
                        seq_num=info['seq'],
                        server_timestamp=snapshot_time,
                        packet_size=total_packet_size
                    )
                    print(f"[SENT] DELTA snapshot_id={info['snapshot_id']}, seq={info['seq']} to Player #{info['client number']}, changes: {delta_payload_string}")

                # Send heartbeat if grid not modified (msg_type=5) - NO seq_num increment for heartbeat
                else:
                    
                    info['snapshot_id'] += 1

                    snapshot_packet = struct.pack(
                        HEADER_FORMAT, b'DOMX', 1, 5, info['snapshot_id'], info['seq'],
                        snapshot_time, 0
                    )
                    serverSocket.sendto(snapshot_packet, client_addr)
                    
                    # Reliability: Increment unacked heartbeat counter
                    info['consecutive_unacked_heartbeats'] += 1
                    
                    # Log HEARTBEAT metrics
                    log_packet_metrics(
                        info['client number'],
                        msg_type=5,  # HEARTBEAT
                        snapshot_id=info['snapshot_id'],
                        seq_num=info['seq'],
                        server_timestamp=snapshot_time,
                        packet_size=len(snapshot_packet)
                    )

        # Reset modification flag after broadcasting to all clients
        modifiedFlag = False
        
        # Sleep until next tick (accounting for processing time)
        sleep_time = next_tick_time - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)


# Start broadcasting in a background thread
threading.Thread(target=broadcast_snapshots, daemon=True).start()


# ======================================
# Listen for Client Messages
# ======================================
while True:  # msg_type: INIT=0, ACK=1, EVENT=2, FULL=3, DELTA=4, HEARTBEAT=5, GAME_OVER=6
    try:
        #[TODO] Handle game over state
        if gameOver:
            # Keep server running but stop processing new events
            time.sleep(1)
            continue
        #max 1200 bytes    
        data, clientAddress = serverSocket.recvfrom(1200)

        # Parse header
        header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        #[TODO] snap_id
        protocol_id, version, msg_type, snap_id, seq, timestamp, payload_len = header
        recv_time = int(time.time() * 1000)

        # Handle INIT (client connects)
        if msg_type == 0:
            clientNumber += 1
            clients[clientAddress] = {
                'seq': 0, 
                'snapshot_id': 0,  # Per-client snapshot_id counter
                'client number': clientNumber, 
                'last_ack': False,
                'last_bandwidth_kbps': 0,  # Track bandwidth per client
                # Reliability: Packet buffering and ACK tracking
                'snapshot_buffer': [],  # Store last 3 DELTA/FULL packets: [(snapshot_id, seq_num, payload, header_time), ...]
                'last_acked_snapshot_id': 0,  # Track which snapshot was last ACKed
                'packets_awaiting_ack': set(),  # Set of snapshot_ids sent but not yet ACKed
                'consecutive_unacked_heartbeats': 0,  # Counter for heartbeats without ACK
                # Delta encoding: Track last grid state sent to this client
                'last_grid_sent': [[0 for _ in range(cols)] for _ in range(rows)],  # Previous grid state for delta calculation
            }
            print(f"[INIT] Client connected: {clientAddress}, Player #{clientNumber}")
            
            # Log INIT metrics
            log_packet_metrics(
                clientNumber,
                msg_type=0,  # INIT
                snapshot_id=0,
                seq_num=0,
                server_timestamp=timestamp,
                recv_time=recv_time,
                packet_size=len(data)
            )

            # Send ACK (msg_type=1)
            ack_time = int(time.time() * 1000)
            response = struct.pack(HEADER_FORMAT, b'DOMX', 1, 1, 0, 0, ack_time, 0)
            serverSocket.sendto(response, clientAddress)
            print(f"[SENT] ACK to {clientAddress}")
            
            # Log ACK (sent) metrics
            log_packet_metrics(
                clientNumber,
                msg_type=1,  # ACK
                snapshot_id=0,
                seq_num=0,
                server_timestamp=ack_time,
                packet_size=len(response)
            )

            # Send FULL snapshot (msg_type=3)
            initial_snapshot_payload = json.dumps(grid).encode()
            payloadLen = len(initial_snapshot_payload)

            clients[clientAddress]['snapshot_id'] += 1
            clients[clientAddress]['seq'] += 1
            
            # Update client's last known grid state after sending FULL snapshot
            clients[clientAddress]['last_grid_sent'] = [row[:] for row in grid]  # Deep copy current grid
            
            full_time = int(time.time() * 1000)
            headers = struct.pack(
                HEADER_FORMAT, b'DOMX', 1, 3,
                clients[clientAddress]['snapshot_id'],
                clients[clientAddress]['seq'],
                full_time, payloadLen
            )
            serverSocket.sendto(headers + initial_snapshot_payload, clientAddress)
            print(f"[SENT] FULL snapshot to {clientAddress}, snapshot_id={clients[clientAddress]['snapshot_id']}")
            
            # Log FULL metrics
            total_size = len(headers) + payloadLen
            log_packet_metrics(
                clientNumber,
                msg_type=3,  # FULL
                snapshot_id=clients[clientAddress]['snapshot_id'],
                seq_num=clients[clientAddress]['seq'],
                server_timestamp=full_time,
                packet_size=total_size
            )

        # Handle ACK
        elif msg_type == 1:
            if clientAddress in clients:
                clients[clientAddress]['last_ack'] = True
                # Reliability: Reset heartbeat counter on successful ACK
                clients[clientAddress]['consecutive_unacked_heartbeats'] = 0

                # Update last ACKed snapshot and clean up buffer
                clients[clientAddress]['last_acked_snapshot_id'] = snap_id
                if snap_id in clients[clientAddress]['packets_awaiting_ack']:
                    clients[clientAddress]['packets_awaiting_ack'].discard(snap_id)
                
                # Remove old buffered packets (keep only newer than ACKed snapshot)
                clients[clientAddress]['snapshot_buffer'] = [
                    pkt for pkt in clients[clientAddress]['snapshot_buffer']
                    if pkt[0] > snap_id  # Keep packets with snapshot_id > ACKed snapshot_id
                ]
                
                # Log ACK (received) metrics
                log_packet_metrics(
                    clients[clientAddress]['client number'],
                    msg_type=1,  # ACK
                    snapshot_id=snap_id,
                    seq_num=seq,
                    server_timestamp=timestamp,
                    recv_time=recv_time,
                    packet_size=len(data)
                )

        # Handle EVENT (ACQUIRE_CELL r c)
        elif msg_type == 2:
            modifiedFlag = True
            payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]
            message = payload.decode()
            print(f"[EVENT] From {clientAddress}: {message}")

            parts = message.split()
            if len(parts) == 3 and parts[0] == "ACQUIRE_CELL":
                try:
                    r, c = int(parts[1]), int(parts[2])
                    player_num = clients[clientAddress]['client number']
                    
                    # Validate cell coordinates and availability
                    if 0 <= r < rows and 0 <= c < cols and grid[r][c] == 0:
                        grid[r][c] = player_num
                        numberOfClicks += 1
                        print(f"Cell ({r},{c}) acquired by Player {player_num}")
                        
                        # Log authoritative position for Section 6 position error calculation
                        log_authoritative_position(int(time.time() * 1000), grid)
                        
                        # Check if game is over (grid is full)
                        if numberOfClicks >= (rows * cols):
                            print(f"\n[GAME OVER] Grid is full! Last cell ({r},{c}) captured by Player {player_num}")
                            
                            # Allow one more broadcast cycle to show the final cell capture
                            time.sleep(TICK_INTERVAL * 1.5)  # Give clients time to see final state
                            broadcast_game_over()
                    else:
                        print(f"[INVALID] Cell ({r},{c}) already occupied or out of bounds")
                            
                except Exception as e:
                    print(f"[ERROR] Invalid cell data: {e}")

    except OSError as e:
        # Handle connection errors gracefully (client disconnect, etc.)
        if clientAddress in clients:
            print(f"[DISCONNECT] Client {clientAddress} (Player #{clients[clientAddress]['client number']}) disconnected")
            del clients[clientAddress]
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")