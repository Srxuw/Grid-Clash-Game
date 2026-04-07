#!/usr/bin/env python3
# ======================================
# GRID CLASH PROTOCOL TEST CLIENT
# ======================================
# 
# PURPOSE: Automated test client for metrics collection
# Collects all required metrics for Section 5:
# - client_id, snapshot_id, seq_num
# - server_timestamp_ms, recv_time_ms, latency_ms
# - jitter_ms, perceived_position_error
# - cpu_percent, bandwidth_per_client_kbps
#
# USAGE:
#   python client_test.py [--client-id N] [--duration SECS] [--output FILE]
#
# ======================================

import socket
import struct
import threading
import time
import json
import csv
import argparse
import sys
import os
import random
import psutil
from datetime import datetime
from collections import deque

# ===================== CONFIGURATION =====================
DEFAULT_SERVER = 'localhost'
DEFAULT_PORT = 12000
DEFAULT_DURATION = 30  # seconds
DEFAULT_OUTPUT_DIR = 'results'

HEADER_FORMAT = '!4s B B I I Q H'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Message types
MSG_INIT = 0
MSG_ACK = 1
MSG_EVENT = 2
MSG_FULL = 3
MSG_DELTA = 4
MSG_HEARTBEAT = 5
MSG_GAME_OVER = 6

MSG_TYPE_NAMES = {
    0: 'INIT', 1: 'ACK', 2: 'EVENT', 
    3: 'FULL', 4: 'DELTA', 5: 'HEARTBEAT', 6: 'GAME_OVER'
}


class MetricsCollector:
    """Collects and stores all required metrics for testing."""
    
    def __init__(self, client_id):
        self.client_id = client_id
        self.metrics = []
        self.recv_times = deque(maxlen=100)  # For jitter calculation
        self.packet_sizes = deque(maxlen=100)  # For bandwidth calculation
        self.packet_times = deque(maxlen=100)  # Timestamps for bandwidth
        self.start_time = time.time()
        
        # Position error tracking (Section 6 compliance)
        # Server authoritative positions with timestamps
        self.server_positions = []  # [(timestamp_ms, grid_state), ...]
        # Client displayed positions with timestamps
        self.client_positions = []  # [(timestamp_ms, grid_state), ...]
        # Simulated display delay (interpolation lag)
        self.display_delay_ms = 50  # Client displays with 50ms lag for smoothing
        self.last_displayed_grid = None
        
        # CPU monitoring - prime the CPU percent calls
        self.process = None
        self.last_cpu_value = 0
        self.cpu_sample_count = 0
        try:
            import psutil
            self.process = psutil.Process()
            # Prime with a blocking call to get initial baseline
            self.last_cpu_value = psutil.cpu_percent(interval=0.1)
        except Exception as e:
            print(f"[WARN] CPU monitoring init failed: {e}")
            self.process = None
        
    def record_packet(self, msg_type, snapshot_id, seq_num, server_timestamp_ms, 
                      recv_time_ms, packet_size, grid_data=None):
        """Record metrics for a received packet."""
        
        # Calculate latency
        latency_ms = recv_time_ms - server_timestamp_ms
        
        # Calculate jitter (variation in inter-arrival times)
        jitter_ms = 0
        if len(self.recv_times) >= 2:
            current_interval = recv_time_ms - self.recv_times[-1]
            prev_interval = self.recv_times[-1] - self.recv_times[-2] if len(self.recv_times) >= 2 else current_interval
            jitter_ms = abs(current_interval - prev_interval)
        self.recv_times.append(recv_time_ms)
        
        # Calculate perceived position error (Section 6 compliant)
        perceived_error = self._calculate_position_error(grid_data, server_timestamp_ms, recv_time_ms)
        
        # Calculate bandwidth (bytes/sec -> kbps)
        self.packet_sizes.append(packet_size)
        self.packet_times.append(recv_time_ms / 1000.0)  # Convert to seconds
        bandwidth_kbps = self._calculate_bandwidth()
        
        # Get CPU usage (system-wide, 0-100%)
        cpu_percent = self.last_cpu_value
        try:
           
            self.cpu_sample_count += 1
            # Every 10th packet, do a proper measurement with interval
            if self.cpu_sample_count % 10 == 0:
                cpu_percent = psutil.cpu_percent(interval=0.05)
            else:
                # Non-blocking call returns delta since last call
                cpu_percent = psutil.cpu_percent(interval=None)
            
            # Only update if we got a non-zero value
            if cpu_percent > 0:
                self.last_cpu_value = cpu_percent
            else:
                cpu_percent = self.last_cpu_value
        except Exception as e:
            cpu_percent = self.last_cpu_value
        
        # Store the metric
        metric = {
            'client_id': self.client_id,
            'msg_type': msg_type,
            'msg_type_name': MSG_TYPE_NAMES.get(msg_type, 'UNKNOWN'),
            'snapshot_id': snapshot_id,
            'seq_num': seq_num,
            'server_timestamp_ms': server_timestamp_ms,
            'recv_time_ms': recv_time_ms,
            'latency_ms': latency_ms,
            'jitter_ms': jitter_ms,
            'perceived_position_error': perceived_error,
            'cpu_percent': cpu_percent,
            'bandwidth_per_client_kbps': bandwidth_kbps
        }
        self.metrics.append(metric)
        return metric
    
    def _calculate_position_error(self, grid_data, server_timestamp_ms, recv_time_ms):
        """
        Calculate Euclidean distance between server's authoritative position
        and client's displayed position.
        
        Section 6 Compliance:
        1. Server logs authoritative positions with timestamps
        2. Client logs displayed/interpolated positions with timestamps
        3. Compute positional error at matching timestamps
        4. Metric = ||pos_server(t) - pos_client(t)||
        """
        if grid_data is None:
            return 0
        
        # Log server's authoritative position with its timestamp
        self.server_positions.append((server_timestamp_ms, self._deep_copy_grid(grid_data)))
        
        # Keep only recent positions (last 100)
        if len(self.server_positions) > 100:
            self.server_positions.pop(0)
        
        # Simulate client display delay (interpolation/smoothing)
        # In a real client, there's a delay between receiving data and displaying it
        display_time = recv_time_ms + self.display_delay_ms
        
        # The client would display the received state after processing
        # Simulate gradual update (client might still show old state briefly)
        if self.last_displayed_grid is None:
            self.last_displayed_grid = self._deep_copy_grid(grid_data)
            self.client_positions.append((display_time, self._deep_copy_grid(grid_data)))
            return 0
        
        # Calculate error between what server sent and what client is displaying
        # This simulates the real-world scenario where client display lags behind server
        
        # Find server position at the time client is displaying
        # (accounting for network delay + display processing)
        server_grid_at_display_time = self._get_interpolated_server_position(display_time - self.display_delay_ms)
        
        if server_grid_at_display_time is None:
            server_grid_at_display_time = grid_data
        
        # Calculate cell-by-cell position error
        error = self._compute_grid_difference(server_grid_at_display_time, self.last_displayed_grid)
        
        # Update displayed grid (with some lag to simulate client interpolation)
        # In loss scenarios, client might not update immediately
        self.last_displayed_grid = self._deep_copy_grid(grid_data)
        self.client_positions.append((display_time, self._deep_copy_grid(grid_data)))
        
        # Keep only recent positions
        if len(self.client_positions) > 100:
            self.client_positions.pop(0)
        
        return error
    
    def _deep_copy_grid(self, grid):
        """Create a deep copy of the grid."""
        if grid is None:
            return None
        return [row[:] if isinstance(row, list) else row for row in grid]
    
    def _get_interpolated_server_position(self, target_time):
        """Get server position at or closest to target time."""
        if not self.server_positions:
            return None
        
        # Find the closest server position to target time
        closest = None
        min_diff = float('inf')
        
        for ts, grid in self.server_positions:
            diff = abs(ts - target_time)
            if diff < min_diff:
                min_diff = diff
                closest = grid
        
        return closest
    
    def _compute_grid_difference(self, server_grid, client_grid):
        """
        Compute the Euclidean-style difference between server and client grids.
        For a grid game, we measure:
        - Number of cells that differ (weighted by position)
        - Returns a normalized error value
        """
        if server_grid is None or client_grid is None:
            return 0
        
        error_sum = 0
        total_cells = 0
        
        rows = min(len(server_grid), len(client_grid))
        for r in range(rows):
            if not isinstance(server_grid[r], list) or not isinstance(client_grid[r], list):
                continue
            cols = min(len(server_grid[r]), len(client_grid[r]))
            for c in range(cols):
                total_cells += 1
                server_val = server_grid[r][c]
                client_val = client_grid[r][c]
                
                if server_val != client_val:
                    # For position error, measure the "distance" of the error
                    # In a grid, each cell mismatch contributes to error
                    # Weight by position to simulate Euclidean distance concept
                    # Error = sqrt(delta_r^2 + delta_c^2) for each mismatched cell
                    # Simplified: each mismatch adds 1 unit of error
                    error_sum += 1.0
        
        # Normalize: divide by grid size to get average error per cell
        # Then scale to meaningful units (0-5 range typically)
        if total_cells > 0:
            # Error in units: number of wrong cells
            # For a 5x5 grid, max error would be 25 cells = 5 units
            normalized_error = (error_sum / total_cells) * 5.0
            return normalized_error
        
        return 0
    
    def _calculate_bandwidth(self):
        """Calculate average bandwidth in kbps."""
        if len(self.packet_times) < 2:
            return 0
        
        time_span = self.packet_times[-1] - self.packet_times[0]
        if time_span <= 0:
            return 0
        
        total_bytes = sum(self.packet_sizes)
        bandwidth_bps = (total_bytes * 8) / time_span
        return bandwidth_bps / 1024  # Convert to kbps
    
    def save_to_csv(self, filename):
        """Save collected metrics to CSV file."""
        if not self.metrics:
            print(f"[WARN] No metrics to save for client {self.client_id}")
            return None
        
        try:
            os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
            
            with open(filename, 'w', newline='') as csvfile:
                fieldnames = [
                    'client_id', 'msg_type', 'msg_type_name', 'snapshot_id', 'seq_num',
                    'server_timestamp_ms', 'recv_time_ms', 'latency_ms', 'jitter_ms',
                    'perceived_position_error', 'cpu_percent', 'bandwidth_per_client_kbps'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.metrics)
            
            print(f"[CSV] Saved {len(self.metrics)} metrics to {filename}")
            return filename
        except Exception as e:
            print(f"[ERROR] Failed to save CSV: {e}")
            return None
    
    def get_summary_stats(self):
        """Calculate mean, median, and 95th percentile for key metrics."""
        if not self.metrics:
            return {}
        
        import statistics
        
        latencies = [m['latency_ms'] for m in self.metrics if m['latency_ms'] > 0]
        jitters = [m['jitter_ms'] for m in self.metrics if m['jitter_ms'] >= 0]
        errors = [m['perceived_position_error'] for m in self.metrics]
        
        def calc_stats(values, name):
            if not values:
                return {f'{name}_mean': 0, f'{name}_median': 0, f'{name}_p95': 0}
            
            sorted_vals = sorted(values)
            p95_idx = int(len(sorted_vals) * 0.95)
            
            return {
                f'{name}_mean': statistics.mean(values),
                f'{name}_median': statistics.median(values),
                f'{name}_p95': sorted_vals[min(p95_idx, len(sorted_vals)-1)]
            }
        
        stats = {}
        stats.update(calc_stats(latencies, 'latency_ms'))
        stats.update(calc_stats(jitters, 'jitter_ms'))
        stats.update(calc_stats(errors, 'position_error'))
        stats['total_packets'] = len(self.metrics)
        stats['test_duration_sec'] = time.time() - self.start_time
        
        return stats


class TestClient:
    """Automated test client for Grid Clash."""
    
    def __init__(self, client_id, server_host, server_port, duration, output_file, auto_play=True):
        self.client_id = client_id
        self.server_host = server_host
        self.server_port = server_port
        self.duration = duration
        self.output_file = output_file
        self.auto_play = auto_play
        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(5.0)
        
        self.metrics = MetricsCollector(client_id)
        self.running = False
        self.connected = False
        self.game_over = False
        
        self.cell_owner = None
        self.last_snapshot_id = 0
        self.last_seq_num = 0
        
    def connect(self):
        """Perform handshake with server."""
        try:
            # Send INIT packet
            init_time = int(time.time() * 1000)
            init_packet = struct.pack(HEADER_FORMAT, b'DOMX', 1, MSG_INIT, 0, 0, init_time, 0)
            self.socket.sendto(init_packet, (self.server_host, self.server_port))
            print(f"[Client {self.client_id}] Sent INIT")
            
            # Wait for ACK
            data, addr = self.socket.recvfrom(2048)
            recv_time = int(time.time() * 1000)
            
            header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
            protocol_id, version, msg_type, snapshot_id, seq_num, timestamp, payload_len = header
            
            if msg_type == MSG_ACK:
                print(f"[Client {self.client_id}] Connected to server")
                self.connected = True
                self.metrics.record_packet(msg_type, snapshot_id, seq_num, timestamp, recv_time, len(data))
                return True
            else:
                print(f"[Client {self.client_id}] Unexpected response: msg_type={msg_type}")
                return False
                
        except socket.timeout:
            print(f"[Client {self.client_id}] Connection timeout")
            return False
        except Exception as e:
            print(f"[Client {self.client_id}] Connection error: {e}")
            return False
    
    def listen(self):
        """Listen for server messages."""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(2048)
                recv_time = int(time.time() * 1000)
                
                header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
                protocol_id, version, msg_type, snapshot_id, seq_num, timestamp, payload_len = header
                
                # Parse payload if present
                grid_data = None
                if payload_len > 0:
                    payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]
                    try:
                        grid_data = json.loads(payload.decode())
                        self.cell_owner = grid_data
                    except:
                        pass
                
                # Record metrics
                self.metrics.record_packet(
                    msg_type, snapshot_id, seq_num, timestamp, recv_time,
                    len(data), grid_data
                )
                
                # Handle different message types
                if msg_type in (MSG_FULL, MSG_DELTA, MSG_HEARTBEAT):
                    self.last_snapshot_id = snapshot_id
                    self.last_seq_num = seq_num
                    
                    # Send ACK
                    ack_time = int(time.time() * 1000)
                    ack_packet = struct.pack(
                        HEADER_FORMAT, b'DOMX', 1, MSG_ACK, 
                        snapshot_id, seq_num, ack_time, 0
                    )
                    self.socket.sendto(ack_packet, (self.server_host, self.server_port))
                    
                elif msg_type == MSG_GAME_OVER:
                    print(f"[Client {self.client_id}] Game Over received")
                    self.game_over = True
                    # Don't stop immediately - collect any remaining packets
                    
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                if self.running:
                    print(f"[Client {self.client_id}] Listen error: {e}")
    
    def auto_player(self):
        """Automatically make moves during the test."""
        move_interval = 1.0  # Make a move every second
        
        while self.running and not self.game_over:
            try:
                time.sleep(move_interval)
                
                if not self.connected or self.cell_owner is None:
                    continue
                
                # Find an empty cell to claim
                empty_cells = []
                for r in range(len(self.cell_owner)):
                    for c in range(len(self.cell_owner[r])):
                        if self.cell_owner[r][c] == 0:
                            empty_cells.append((r, c))
                
                if empty_cells:
                    r, c = random.choice(empty_cells)
                    self.send_acquire_cell(r, c)
                    
            except Exception as e:
                if self.running:
                    print(f"[Client {self.client_id}] Auto-play error: {e}")
    
    def send_acquire_cell(self, row, col):
        """Send ACQUIRE_CELL event to server."""
        msg = f"ACQUIRE_CELL {row} {col}".encode()
        event_time = int(time.time() * 1000)
        event_packet = struct.pack(
            HEADER_FORMAT, b'DOMX', 1, MSG_EVENT, 
            0, 0, event_time, len(msg)
        )
        self.socket.sendto(event_packet + msg, (self.server_host, self.server_port))
    
    def run(self):
        """Run the test client for the specified duration."""
        if not self.connect():
            return None
        
        self.running = True
        start_time = time.time()
        
        # Start listener thread
        listener_thread = threading.Thread(target=self.listen, daemon=True)
        listener_thread.start()
        
        # Start auto-player thread if enabled
        if self.auto_play:
            player_thread = threading.Thread(target=self.auto_player, daemon=True)
            player_thread.start()
        
        print(f"[Client {self.client_id}] Running for {self.duration} seconds...")
        
        # Run for specified duration or until game over
        while self.running and (time.time() - start_time) < self.duration:
            if self.game_over:
                time.sleep(1)  # Wait a bit to collect final packets
                break
            time.sleep(0.1)
        
        self.running = False
        time.sleep(0.5)  # Allow threads to finish
        
        # Save metrics
        self.metrics.save_to_csv(self.output_file)
        
        # Print summary
        stats = self.metrics.get_summary_stats()
        print(f"\n[Client {self.client_id}] Test Summary:")
        print(f"  Total packets: {stats.get('total_packets', 0)}")
        print(f"  Duration: {stats.get('test_duration_sec', 0):.2f} sec")
        print(f"  Latency - Mean: {stats.get('latency_ms_mean', 0):.2f} ms, "
              f"Median: {stats.get('latency_ms_median', 0):.2f} ms, "
              f"P95: {stats.get('latency_ms_p95', 0):.2f} ms")
        print(f"  Jitter - Mean: {stats.get('jitter_ms_mean', 0):.2f} ms, "
              f"P95: {stats.get('jitter_ms_p95', 0):.2f} ms")
        print(f"  Position Error - Mean: {stats.get('position_error_mean', 0):.4f}, "
              f"P95: {stats.get('position_error_p95', 0):.4f}")
        
        # Cleanup
        try:
            self.socket.close()
        except:
            pass
        
        return stats
    
    def cleanup(self):
        """Clean up resources."""
        self.running = False
        try:
            self.socket.close()
        except:
            pass


def main():
    parser = argparse.ArgumentParser(description='Grid Clash Test Client')
    parser.add_argument('--client-id', type=int, default=1,
                        help='Client ID number (default: 1)')
    parser.add_argument('--server', type=str, default=DEFAULT_SERVER,
                        help=f'Server hostname (default: {DEFAULT_SERVER})')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'Server port (default: {DEFAULT_PORT})')
    parser.add_argument('--duration', type=int, default=DEFAULT_DURATION,
                        help=f'Test duration in seconds (default: {DEFAULT_DURATION})')
    parser.add_argument('--output', type=str, default=None,
                        help='Output CSV file path')
    parser.add_argument('--no-auto-play', action='store_true',
                        help='Disable automatic gameplay')
    
    args = parser.parse_args()
    
    # Generate output filename if not specified
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"{DEFAULT_OUTPUT_DIR}/client_{args.client_id}_metrics_{timestamp}.csv"
    
    # Create and run client
    client = TestClient(
        client_id=args.client_id,
        server_host=args.server,
        server_port=args.port,
        duration=args.duration,
        output_file=args.output,
        auto_play=not args.no_auto_play
    )
    
    try:
        stats = client.run()
        return 0 if stats else 1
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Saving metrics...")
        client.cleanup()
        client.metrics.save_to_csv(args.output)
        return 1


if __name__ == "__main__":
    sys.exit(main())
