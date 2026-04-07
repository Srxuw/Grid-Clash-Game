# Grid-Clash

Grid-Clash is a networked multiplayer game project. It features a client-server architecture with specialized testing environments for evaluating network performance under various conditions (such as packet loss and latency).

## Project Structure

The repository is divided into two main components: the core game implementation and the testing suite.

### `Grid-Clash-main/` (Core Game)
Contains the primary source code for the game's client and server.
* `server.py` / `server_final.py`: The main game server handling client connections and game state.
* `client.py` / `client_final.py`: The standard text/console-based client.
* `client_pygame.py`: A graphical client implementation using Pygame.
* `client_loss.py`: A client designed to simulate or handle packet loss.
* `run_baseline.bat`: Windows batch script to run a baseline test or launch the server/clients.

### `Grid-Clash-test/` (Testing Suite)
Contains scripts and tools for network emulation, testing, and performance metrics analysis.
* **Network Emulation (Linux/tc netem)**: 
  * `netem_apply.sh`: Applies network constraints (delay, loss, duplication) to test network resilience.
  * `netem_status.sh`: Checks current network emulation rules.
  * `netem_clear.sh`: Removes all network emulation rules.
* **Testing Scripts**:
  * `run_all_tests.sh`: Automates the execution of multiple test scenarios.
  * `client_test.py`: A specialized client for automated testing.
  * `analyze_metrics.py`: Analyzes the output data and generates performance metrics.
* **Documentation**: Detailed testing documentation can be found in `TESTING.md`.

## Setup and Installation

1. Ensure you have Python 3.x installed.
2. If using the graphical client, install Pygame:
   ```bash
   pip install pygame
   ```

## Running the Game

1. **Start the Server:**
   Navigate to the `Grid-Clash-main` directory and start the game server.
   ```bash
   python server.py
   ```
   *(Alternatively, use `server_final.py` for the finalized version)*

2. **Start the Client:**
   Open a new terminal window, navigate to the `Grid-Clash-main` directory, and start a client.
   ```bash
   python client_pygame.py
   ```
   *(Run multiple clients to test multiplayer functionality)*

## Testing and Network Emulation

To evaluate the game's performance under restricted network conditions, navigate to the `Grid-Clash-test` directory.

1. **Run Automated Tests:**
   ```bash
   ./run_all_tests.sh
   ```
2. **Analyze Results:**
   After tests complete, analyze the metrics:
   ```bash
   python analyze_metrics.py
   ```
*(Note: `.sh` scripts requiring `tc netem` are designed for Linux environments.)*
