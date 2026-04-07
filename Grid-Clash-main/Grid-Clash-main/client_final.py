import socket
import struct
import threading
import time
import json
import pygame
import sys

# ===================== CONFIGURATION =====================
serverName = 'localhost'
serverPort = 12000
COUNTER = 0
clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

HEADER_FORMAT = '!4s B B I I Q H'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
running = True

# ===================== PYGAME SETUP =====================
pygame.init()
WAIT_TIMEOUT= 5
GRID_SIZE = 5
CELL_SIZE = 40
GRID_PADDING = 50
WINDOW_WIDTH = CELL_SIZE * GRID_SIZE + 2 * GRID_PADDING
WINDOW_HEIGHT = CELL_SIZE * GRID_SIZE + 2 * GRID_PADDING + 80

screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
pygame.display.set_caption("Grid Clash Client")
clock = pygame.time.Clock()
font_large = pygame.font.Font(None, 28)
font_small = pygame.font.Font(None, 20)

# Color mappings
COLOR_EMPTY = (200, 200, 200)      # Light gray
COLOR_PLAYER1 = (173, 216, 230)    # Light blue
COLOR_PLAYER2 = (144, 238, 144)    # Light green
COLOR_PLAYER3 = (250, 128, 114)    # Salmon
COLOR_PLAYER4 = (221, 160, 221)    # Plum
COLOR_GRID_LINE = (100, 100, 100)
COLOR_TEXT = (0, 0, 0)
COLOR_BG = (240, 240, 240)

color_map = {
    0: COLOR_EMPTY,
    1: COLOR_PLAYER1,
    2: COLOR_PLAYER2,
    3: COLOR_PLAYER3,
    4: COLOR_PLAYER4,
}

# Game state
cell_owner = [[0 for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
previous_cell_owner = [[0 for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
player_id = None
status_message = "Connecting to server..."
connected = False
game_over = False
leaderboard_data = None

# Animation state
cell_animations = {}  # {(r, c): {'progress': 0.0, 'from_color': ..., 'to_color': ...}}
pulse_effect = {}     # {(r, c): pulse_frame} for newly captured cells
hover_cell = (None, None)
ANIMATION_DURATION = 0.5  # seconds for color transition (slower for smoother recovery)
PULSE_DURATION = 0.5      # seconds for pulse effect

# Packet loss recovery state
snapshot_buffer = []  # Store recent snapshots for interpolation
last_received_time = time.time()
expected_interval = 0.05  # 50ms between snapshots (20Hz)

# ===================== NETWORKING =====================

def grid_to_screen(grid_row, grid_col):
    """Convert grid coordinates to screen coordinates."""
    x = GRID_PADDING + grid_col * CELL_SIZE
    y = GRID_PADDING + grid_row * CELL_SIZE
    return x, y


def screen_to_grid(mouse_x, mouse_y):
    """Convert screen coordinates to grid coordinates."""
    grid_col = (mouse_x - GRID_PADDING) // CELL_SIZE
    grid_row = (mouse_y - GRID_PADDING) // CELL_SIZE
    
    if 0 <= grid_row < GRID_SIZE and 0 <= grid_col < GRID_SIZE:
        return grid_row, grid_col
    return None, None


def lerp_color(color1, color2, t):
    """Linearly interpolate between two colors (0 <= t <= 1)."""
    t = max(0, min(1, t))  # Clamp t
    return tuple(int(c1 + (c2 - c1) * t) for c1, c2 in zip(color1, color2))


def get_cell_color(r, c, current_time):
    """Get the current color of a cell, accounting for animations."""
    base_owner = cell_owner[r][c]
    base_color = color_map.get(base_owner, COLOR_EMPTY)
    
    # Check if cell is animating (color transition)
    if (r, c) in cell_animations:
        anim = cell_animations[(r, c)]
        progress = anim['progress']
        
        if progress >= 1.0:
            del cell_animations[(r, c)]
        else:
            return lerp_color(anim['from_color'], anim['to_color'], progress)
    
    # Check if cell has pulse effect (newly captured)
    if (r, c) in pulse_effect:
        frame = pulse_effect[(r, c)]
        if frame >= PULSE_DURATION:
            del pulse_effect[(r, c)]
        else:
            # Pulse effect: brighten and dim cyclically
            pulse_cycle = (frame % (PULSE_DURATION * 0.5)) / (PULSE_DURATION * 0.5)
            pulse_intensity = 0.3 * (1 - abs(pulse_cycle - 0.5) * 2)  # Triangle wave
            brightened = tuple(min(255, int(c + 50 * pulse_intensity)) for c in base_color)
            return brightened
    
    # Check if cell is hovered
    if (r, c) == hover_cell and base_owner == 0:
        return tuple(min(255, int(c + 30)) for c in base_color)
    
    return base_color


# ===================== NETWORKING =====================

def on_cell_click(r, c):
    """Send ACQUIRE_CELL event to server."""
    msg = f"ACQUIRE_CELL {r} {c}".encode()
    data_packet = struct.pack(HEADER_FORMAT, b'DOMX', 1, 2, 0, 0, int(time.time() * 1000), len(msg))
    clientSocket.sendto(data_packet + msg, (serverName, serverPort))
    print(f"[EVENT] Sent ACQUIRE_CELL ({r}, {c})")


def listen_for_snapshots():
    """Continuously listens for incoming snapshots and updates grid."""
    global cell_owner, previous_cell_owner, status_message, connected, game_over, leaderboard_data
    
    while running:
        try:
            data, serverAddress = clientSocket.recvfrom(1200)
            header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
            protocol_id, version, msg_type, snapshot_id, seq_num, timestamp, payload_len = header
            
            # # Handle packet loss simulation for DELTA snapshots
            # if msg_type == 4:
            #     global COUNTER
            #     COUNTER += 1
            #     loss_cycle = COUNTER % 10
            #     if 1 <= loss_cycle <= 3:  # Drop 3 consecutive deltas
            #         print(f"[SIMULATED LOSS] Dropped DELTA snapshot ({loss_cycle}/3)")
            #         continue
            
            # Handle game snapshots (FULL / DELTA / HEARTBEAT)
            if msg_type in (3, 4, 5):
                # Update last received time for packet loss detection
                global last_received_time
                current_time = time.time()
                time_since_last = current_time - last_received_time
                last_received_time = current_time
                
                # Handle FULL snapshots (complete grid)
                if msg_type == 3:
                    snapshot_data = data[HEADER_SIZE:HEADER_SIZE + payload_len]
                    try:
                        grid = json.loads(snapshot_data.decode()) if payload_len > 0 else []
                    except Exception:
                        grid = []
                        
                # Handle DELTA snapshots (only changes)
                elif msg_type == 4:
                    snapshot_data = data[HEADER_SIZE:HEADER_SIZE + payload_len]
                    try:
                        delta_string = snapshot_data.decode() if payload_len > 0 else ""
                        print(f"[DELTA] Received changes: {delta_string}")
                        
                        # Apply delta changes to current grid
                        if delta_string.strip():
                            parts = delta_string.split()
                            if len(parts) % 3 == 0:
                                for i in range(0, len(parts), 3):
                                    player_id = int(parts[i])
                                    row = int(parts[i + 1])
                                    col = int(parts[i + 2])
                                    
                                    if 0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE:
                                        cell_owner[row][col] = player_id
                                        print(f"[DELTA] Applied: Player {player_id} -> ({row},{col})")
                        
                        # Set grid to current cell_owner state for animation processing
                        grid = cell_owner
                        
                    except Exception as e:
                        print(f"[ERROR] Failed to process delta: {e}")
                        grid = []
                
                # Handle HEARTBEAT (no payload)
                elif msg_type == 5:
                    grid = []  # No grid data in heartbeats
                
                if grid:
                    # Add to snapshot buffer for interpolation
                    snapshot_buffer.append({
                        'timestamp': current_time,
                        'grid': [row[:] for row in grid],  # Deep copy
                        'snapshot_id': snapshot_id
                    })
                    
                    # Keep only last 3 snapshots
                    if len(snapshot_buffer) > 3:
                        snapshot_buffer.pop(0)
                    
                    # Detect if we missed packets (gap > 1.5x expected interval)
                    missed_packets = time_since_last > (expected_interval * 1.5)
                    
                    # Detect cell changes and trigger smooth animations
                    for r in range(len(grid)):
                        for c in range(len(grid[r])):
                            if grid[r][c] != previous_cell_owner[r][c]:
                                # Cell owner changed - start animation
                                old_color = color_map.get(previous_cell_owner[r][c], COLOR_EMPTY)
                                new_color = color_map.get(grid[r][c], COLOR_EMPTY)
                                
                                # Adjust animation speed based on packet loss
                                animation_speed = ANIMATION_DURATION
                                if missed_packets:
                                    # Slower animation for smoother recovery from packet loss
                                    animation_speed = ANIMATION_DURATION * 1.5
                                    print(f"[RECOVERY] Smooth recovery animation for cell ({r},{c})")
                                
                                cell_animations[(r, c)] = {
                                    'progress': 0.0,
                                    'from_color': old_color,
                                    'to_color': new_color,
                                    'start_time': current_time,
                                    'duration': animation_speed
                                }
                                
                                # Trigger pulse effect on newly captured cells
                                if grid[r][c] != 0:
                                    pulse_effect[(r, c)] = 0.0
                    
                    # Update game states
                    previous_cell_owner = [row[:] for row in grid]  # Deep copy
                    cell_owner = grid
                    status_message = "Connected! Playing..."
                    connected = True
                
                # Send ACK for all snapshot types
                response = struct.pack(HEADER_FORMAT, b'DOMX', 1, 1, snapshot_id, seq_num, int(time.time() * 1000), 0)
                clientSocket.sendto(response, serverAddress)
            
            # Handle GAME_OVER message
            elif msg_type == 6:
                game_over_data = data[HEADER_SIZE:HEADER_SIZE + payload_len]
                try:
                    leaderboard_data = json.loads(game_over_data.decode())
                    game_over = True
                    status_message = "GAME OVER! Check leaderboard below."
                    print("[GAME OVER] Received final leaderboard")
                except Exception as e:
                    print(f"[ERROR] Failed to parse game over data: {e}")
         
        except OSError:
            break
        except Exception as e:
            if running:
                print(f"[Listener Error]: {e}")
            break


def init_connection():
    """Perform handshake with server."""
    global status_message, connected
    try:
        # Send INIT packet
        init_packet = struct.pack(HEADER_FORMAT, b'DOMX', 1, 0, 0, 0, int(time.time() * 1000), 0)
        clientSocket.sendto(init_packet, (serverName, serverPort))
        status_message = "Sent INIT message..."
        print("Sent INIT message")

        # Wait for ACK
        clientSocket.settimeout(WAIT_TIMEOUT)
        data, serverAddress = clientSocket.recvfrom(1200)
       # clientSocket.settimeout(None)
        
        header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        print(f"Received ACK: msg_type={header[2]}")
        status_message = "Connected! Waiting for snapshots..."
        
        # Start snapshot listener thread
        threading.Thread(target=listen_for_snapshots, daemon=True).start()
    except socket.timeout:
        status_message = "Connection timeout. Server not responding."
        print("[ERROR] Connection timeout")
    except Exception as e:
        status_message = f"Connection failed: {e}"
        print(f"[ERROR] {e}")


def draw_grid():
    """Draw the game grid with animations."""
    current_time = time.time()
    
    # Update animation progress with variable duration
    for (r, c), anim in list(cell_animations.items()):
        elapsed = current_time - anim['start_time']
        duration = anim.get('duration', ANIMATION_DURATION)
        anim['progress'] = elapsed / duration
    
    # Update pulse effects
    for (r, c), frame in list(pulse_effect.items()):
        pulse_effect[(r, c)] = frame + 1/60.0  # Assuming 60 FPS
    
    # Draw all cells
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            x, y = grid_to_screen(r, c)
            color = get_cell_color(r, c, current_time)
            pygame.draw.rect(screen, color, (x, y, CELL_SIZE, CELL_SIZE))
            pygame.draw.rect(screen, COLOR_GRID_LINE, (x, y, CELL_SIZE, CELL_SIZE), 1)


def draw_status_bar():
    """Draw the status bar at the top with connection indicator."""
    # Connection indicator dot
    indicator_x = GRID_PADDING + 20
    indicator_y = 20
    indicator_color = (0, 200, 0) if connected else (200, 0, 0)
    pygame.draw.circle(screen, indicator_color, (indicator_x, indicator_y), 6)
    
    # Status text
    status_text = font_small.render(status_message, True, COLOR_TEXT)
    screen.blit(status_text, (indicator_x + 20, 10))


def draw_legend():
    """Draw legend at the bottom."""
    legend_y = GRID_PADDING + CELL_SIZE * GRID_SIZE + 10
    legend_text = "Player 1: Blue |  Player 2: Green | Player 3: Salmon | Player 4: Purple"
    text_surface = font_small.render(legend_text, True, COLOR_TEXT)
    screen.blit(text_surface, (GRID_PADDING, legend_y))


def draw_game_over_screen():
    """Draw game over screen with leaderboard."""
    if not leaderboard_data or not game_over:
        return
    
    # Semi-transparent overlay
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
    overlay.set_alpha(200)
    overlay.fill((0, 0, 0))
    screen.blit(overlay, (0, 0))
    
    # Game Over title
    title_text = font_large.render("GAME OVER", True, (255, 255, 255))
    title_rect = title_text.get_rect(center=(WINDOW_WIDTH // 2, 100))
    screen.blit(title_text, title_rect)
    
    # Leaderboard
    leaderboard_title = font_small.render("Final Leaderboard:", True, (255, 255, 255))
    leaderboard_rect = leaderboard_title.get_rect(center=(WINDOW_WIDTH // 2, 140))
    screen.blit(leaderboard_title, leaderboard_rect)
    
    # Display each player's ranking
    y_offset = 170
    for entry in leaderboard_data.get("leaderboard", []):
        rank = entry.get("rank", "?")
        player_id = entry.get("player_id", "?")
        color_name = entry.get("color", "Unknown")
        score = entry.get("score", 0)
        
        rank_text = f"{rank}. Player #{player_id} ({color_name}): {score} cells"
        rank_surface = font_small.render(rank_text, True, (255, 255, 255))
        rank_rect = rank_surface.get_rect(center=(WINDOW_WIDTH // 2, y_offset))
        screen.blit(rank_surface, rank_rect)
        y_offset += 25
    
    # Instructions
    instruction_text = font_small.render("Press ESC to close", True, (200, 200, 200))
    instruction_rect = instruction_text.get_rect(center=(WINDOW_WIDTH // 2, y_offset + 30))
    screen.blit(instruction_text, instruction_rect)


# ===================== MAIN LOOP =====================

def main():
    global running, hover_cell
    
    # Initialize connection
    init_connection()
    
    while running:
        clock.tick(60)  # 60 FPS
        
        # Update hover effect
        mouse_x, mouse_y = pygame.mouse.get_pos()
        hover_row, hover_col = screen_to_grid(mouse_x, mouse_y)
        hover_cell = (hover_row, hover_col) if hover_row is not None else (None, None)
        
        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE and game_over:
                    running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and not game_over:
                if event.button == 1:  # Left click (only when game is active)
                    mouse_x, mouse_y = event.pos
                    grid_row, grid_col = screen_to_grid(mouse_x, mouse_y)
                    if grid_row is not None and grid_col is not None:
                        on_cell_click(grid_row, grid_col)
        
        # Draw everything
        screen.fill(COLOR_BG)
        draw_grid()
        draw_status_bar()
        draw_legend()
        
        # Draw game over screen if game has ended
        if game_over:
            draw_game_over_screen()
        
        pygame.display.flip()
    
    # Cleanup
    try:
        clientSocket.close()
    except:
        pass
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()