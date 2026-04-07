#!/bin/bash
# ======================================
# GRID CLASH - AUTOMATED TEST RUNNER
# ======================================
#
# PURPOSE: Automates all test scenarios for Section 4
# - Baseline (no impairment)
# - Loss 2% (LAN-like)
# - Loss 5% (WAN-like)  
# - Delay 100ms (WAN delay)
#
# USAGE:
#   sudo ./run_all_tests.sh [INTERFACE] [NUM_CLIENTS] [DURATION]
#
# EXAMPLES:
#   sudo ./run_all_tests.sh                    # Auto-detect interface, 2 clients, 30 sec
#   sudo ./run_all_tests.sh lo 4 60            # Loopback, 4 clients, 60 sec
#   sudo ./run_all_tests.sh eth0 2 30          # eth0, 2 clients, 30 sec
#
# REQUIREMENTS:
#   - Root privileges (for netem commands)
#   - Python 3 with required packages
#   - tc (traffic control) installed
#
# ======================================

set -e

# ===================== CONFIGURATION =====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"
LOGS_DIR="${SCRIPT_DIR}/logs"
PLOTS_DIR="${SCRIPT_DIR}/plots"
PCAPS_DIR="${SCRIPT_DIR}/pcaps"
SERVER_METRICS_DIR="${SCRIPT_DIR}/server_metrics"

# Default values
DEFAULT_INTERFACE="lo"
DEFAULT_NUM_CLIENTS=2
DEFAULT_DURATION=30
SERVER_PORT=12000
SERVER_STARTUP_DELAY=2
CLIENT_STARTUP_DELAY=1

# Parse arguments
INTERFACE="${1:-$DEFAULT_INTERFACE}"
NUM_CLIENTS="${2:-$DEFAULT_NUM_CLIENTS}"
DURATION="${3:-$DEFAULT_DURATION}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ===================== HELPER FUNCTIONS =====================

print_header() {
    echo ""
    echo -e "${BLUE}======================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}======================================${NC}"
}

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script requires root privileges for network impairment simulation"
        print_info "Please run with: sudo $0"
        exit 1
    fi
}

check_dependencies() {
    print_info "Checking dependencies..."
    
    # Check for tc
    if ! command -v tc &> /dev/null; then
        print_error "tc (traffic control) is not installed"
        print_info "Install with: sudo apt-get install iproute2"
        exit 1
    fi
    
    # Check for Python 3
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        exit 1
    fi
    
    # Check for required Python packages
    python3 -c "import psutil" 2>/dev/null || {
        print_warn "psutil not installed. Installing..."
        pip3 install psutil
    }
    
    print_info "All dependencies satisfied"
}

detect_interface() {
    # Try to auto-detect the network interface
    if [ "$INTERFACE" = "auto" ]; then
        # Get the default interface
        INTERFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
        if [ -z "$INTERFACE" ]; then
            INTERFACE="lo"  # Fall back to loopback
        fi
        print_info "Auto-detected interface: $INTERFACE"
    fi
    
    # Verify interface exists
    if ! ip link show "$INTERFACE" &> /dev/null; then
        print_error "Interface $INTERFACE does not exist"
        print_info "Available interfaces:"
        ip link show | grep -E "^[0-9]+:" | awk -F': ' '{print "  - " $2}'
        exit 1
    fi
}

setup_directories() {
    print_info "Setting up directories..."
    mkdir -p "$RESULTS_DIR" 2>/dev/null || true
    mkdir -p "$LOGS_DIR" 2>/dev/null || true
    mkdir -p "$PLOTS_DIR" 2>/dev/null || true
    mkdir -p "$PCAPS_DIR" 2>/dev/null || true
    mkdir -p "$SERVER_METRICS_DIR" 2>/dev/null || true
}

cleanup_previous_test() {
    print_info "Cleaning up previous test artifacts..."
    
    # Clear logs
    if [ -d "$LOGS_DIR" ] && [ "$(ls -A $LOGS_DIR 2>/dev/null)" ]; then
        rm -f "${LOGS_DIR}"/* 2>/dev/null || true
        print_info "  Cleared logs/"
    fi
    
    # Clear pcaps
    if [ -d "$PCAPS_DIR" ] && [ "$(ls -A $PCAPS_DIR 2>/dev/null)" ]; then
        rm -f "${PCAPS_DIR}"/* 2>/dev/null || true
        print_info "  Cleared pcaps/"
    fi
    
    # Clear results
    if [ -d "$RESULTS_DIR" ] && [ "$(ls -A $RESULTS_DIR 2>/dev/null)" ]; then
        rm -f "${RESULTS_DIR}"/* 2>/dev/null || true
        print_info "  Cleared results/"
    fi
    
    # Clear server_metrics
    if [ -d "$SERVER_METRICS_DIR" ] && [ "$(ls -A $SERVER_METRICS_DIR 2>/dev/null)" ]; then
        rm -f "${SERVER_METRICS_DIR}"/* 2>/dev/null || true
        print_info "  Cleared server_metrics/"
    fi
    
    # Clear plots
    if [ -d "$PLOTS_DIR" ] && [ "$(ls -A $PLOTS_DIR 2>/dev/null)" ]; then
        rm -f "${PLOTS_DIR}"/* 2>/dev/null || true
        print_info "  Cleared plots/"
    fi
    
    # Clear any stray game_metrics*.csv and authoritative_positions*.csv in root
    rm -f "${SCRIPT_DIR}"/game_metrics_*.csv 2>/dev/null || true
    rm -f "${SCRIPT_DIR}"/authoritative_positions_*.csv 2>/dev/null || true
}

# ===================== PCAP CAPTURE =====================
TCPDUMP_PID=""

start_pcap_capture() {
    local pcap_file="$1"
    
    # Check if tcpdump is available
    if ! command -v tcpdump &> /dev/null; then
        print_warn "tcpdump not installed. Skipping pcap capture."
        print_info "Install with: sudo apt-get install tcpdump"
        return 1
    fi
    
    print_info "Starting packet capture to $pcap_file"
    tcpdump -i "$INTERFACE" -w "$pcap_file" port $SERVER_PORT 2>/dev/null &
    TCPDUMP_PID=$!
    sleep 1
    
    if kill -0 $TCPDUMP_PID 2>/dev/null; then
        print_info "Packet capture started (PID: $TCPDUMP_PID)"
        return 0
    else
        print_warn "Failed to start packet capture"
        TCPDUMP_PID=""
        return 1
    fi
}

stop_pcap_capture() {
    if [ -n "$TCPDUMP_PID" ]; then
        print_info "Stopping packet capture..."
        kill -TERM $TCPDUMP_PID 2>/dev/null || true
        # Give it 2 seconds to exit gracefully
        sleep 2
        # Force kill if still running
        if kill -0 $TCPDUMP_PID 2>/dev/null; then
            kill -KILL $TCPDUMP_PID 2>/dev/null || true
        fi
        TCPDUMP_PID=""
    fi
}

cleanup_netem() {
    print_info "Cleaning up any existing netem rules on $INTERFACE..."
    tc qdisc del dev "$INTERFACE" root 2>/dev/null || true
}

apply_netem() {
    local rule="$1"
    local description="$2"
    
    cleanup_netem
    
    if [ -n "$rule" ]; then
        print_info "Applying netem rule: $description"
        eval "tc qdisc add dev $INTERFACE root netem $rule"
        
        # Verify the rule was applied
        tc qdisc show dev "$INTERFACE" | grep -q netem && \
            print_info "Rule applied successfully" || \
            print_error "Failed to apply rule"
    else
        print_info "No netem rule (baseline scenario)"
    fi
}

start_server() {
    local log_file="$1"
    
    print_info "Starting server..."
    
    # Kill any existing server
    pkill -f "python3.*server.py" 2>/dev/null || true
    sleep 1
    
    # Start server in background with metrics output directory
    cd "$SCRIPT_DIR"
    METRICS_OUTPUT_DIR="$SERVER_METRICS_DIR" python3 server.py > "$log_file" 2>&1 &
    SERVER_PID=$!
    
    print_info "Server started (PID: $SERVER_PID)"
    sleep "$SERVER_STARTUP_DELAY"
    
    # Verify server is running
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        print_error "Server failed to start. Check $log_file"
        return 1
    fi
}

stop_server() {
    print_info "Stopping server..."
    
    if [ -n "$SERVER_PID" ]; then
        kill -TERM $SERVER_PID 2>/dev/null || true
        # Give it 2 seconds to exit gracefully
        sleep 2
        # Force kill if still running
        if kill -0 $SERVER_PID 2>/dev/null; then
            kill -KILL $SERVER_PID 2>/dev/null || true
        fi
        SERVER_PID=""
    fi
    
    # Ensure all server processes are stopped
    pkill -f "python3.*server.py" 2>/dev/null || true
    sleep 1
}

run_clients() {
    local scenario_name="$1"
    local output_prefix="$2"
    
    print_info "Starting $NUM_CLIENTS test client(s) for $DURATION seconds..."
    
    CLIENT_PIDS=()
    
    for i in $(seq 1 "$NUM_CLIENTS"); do
        local output_file="${RESULTS_DIR}/${output_prefix}_client${i}.csv"
        local log_file="${LOGS_DIR}/${output_prefix}_client${i}.log"
        
        python3 "${SCRIPT_DIR}/client_test.py" \
            --client-id "$i" \
            --duration "$DURATION" \
            --output "$output_file" \
            > "$log_file" 2>&1 &
        
        CLIENT_PIDS+=($!)
        print_info "  Client $i started (PID: ${CLIENT_PIDS[-1]})"
        sleep "$CLIENT_STARTUP_DELAY"
    done
    
    # Wait for all clients to finish
    print_info "Waiting for clients to complete..."
    for pid in "${CLIENT_PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
    
    print_info "All clients completed"
}

merge_results() {
    local scenario_name="$1"
    local output_prefix="$2"
    local merged_file="${RESULTS_DIR}/${output_prefix}_merged.csv"
    
    print_info "Merging results for $scenario_name..."
    
    # Get header from first file
    local first_file="${RESULTS_DIR}/${output_prefix}_client1.csv"
    if [ -f "$first_file" ]; then
        head -n1 "$first_file" > "$merged_file"
        
        # Append data from all client files (without headers)
        for i in $(seq 1 "$NUM_CLIENTS"); do
            local client_file="${RESULTS_DIR}/${output_prefix}_client${i}.csv"
            if [ -f "$client_file" ]; then
                tail -n+2 "$client_file" >> "$merged_file"
            fi
        done
        
        print_info "Merged results saved to $merged_file"
    else
        print_warn "No results found for $scenario_name"
    fi
}

run_scenario() {
    local scenario_name="$1"
    local netem_rule="$2"
    local output_prefix="$3"
    
    print_header "SCENARIO: $scenario_name"
    
    local server_log="${LOGS_DIR}/${output_prefix}_server.log"
    local pcap_file="${PCAPS_DIR}/${output_prefix}.pcap"
    
    # Apply network impairment
    apply_netem "$netem_rule" "$scenario_name"
    
    # Start packet capture
    start_pcap_capture "$pcap_file"
    
    # Start server
    start_server "$server_log"
    
    # Run clients
    run_clients "$scenario_name" "$output_prefix"
    
    # Wait a bit for final metrics collection
    sleep 2
    
    # Stop server
    stop_server
    
    # Stop packet capture
    stop_pcap_capture
    
    # Merge results
    merge_results "$scenario_name" "$output_prefix"
    
    # Clean up netem
    cleanup_netem
    
    print_info "Scenario $scenario_name completed"
    echo ""
}

generate_summary() {
    local summary_file="${RESULTS_DIR}/test_summary.txt"
    
    print_header "GENERATING TEST SUMMARY"
    
    {
        echo "========================================"
        echo "GRID CLASH TEST SUMMARY"
        echo "========================================"
        echo ""
        echo "Test Configuration:"
        echo "  Interface: $INTERFACE"
        echo "  Clients: $NUM_CLIENTS"
        echo "  Duration per scenario: ${DURATION}s"
        echo "  Timestamp: $(date)"
        echo ""
        echo "Scenarios Tested:"
        echo "  1. Baseline (no impairment)"
        echo "  2. Loss 2% (LAN-like)"
        echo "  3. Loss 5% (WAN-like)"
        echo "  4. Delay 100ms (WAN delay)"
        echo ""
        echo "Results Files:"
        
        for f in "${RESULTS_DIR}"/*_merged.csv; do
            if [ -f "$f" ]; then
                local lines=$(wc -l < "$f")
                echo "  - $(basename "$f"): $((lines - 1)) records"
            fi
        done
        
        echo ""
        echo "========================================"
    } > "$summary_file"
    
    cat "$summary_file"
    print_info "Summary saved to $summary_file"
}

# ===================== MAIN EXECUTION =====================

main() {
    print_header "GRID CLASH AUTOMATED TEST RUNNER"
    
    echo "Configuration:"
    echo "  Interface: $INTERFACE"
    echo "  Clients: $NUM_CLIENTS"
    echo "  Duration per scenario: ${DURATION}s"
    echo ""
    
    # Pre-flight checks
    check_root
    check_dependencies
    detect_interface
    setup_directories
    
    # Clean up artifacts from previous test runs
    cleanup_previous_test
    
    # Clean up any leftover processes
    cleanup_netem
    pkill -f "python3.*server.py" 2>/dev/null || true
    pkill -f "python3.*client_test.py" 2>/dev/null || true
    sleep 1
    
    # Timestamp for this test run
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    
    # Run all test scenarios
    print_header "RUNNING TEST SCENARIOS"
    
    # Scenario 1: Baseline (no impairment)
    run_scenario \
        "Baseline (no impairment)" \
        "" \
        "${TIMESTAMP}_baseline"
    
    # Scenario 2: Loss 2% (LAN-like)
    run_scenario \
        "Loss 2% (LAN-like)" \
        "loss 2%" \
        "${TIMESTAMP}_loss_2pct"
    
    # Scenario 3: Loss 5% (WAN-like)
    run_scenario \
        "Loss 5% (WAN-like)" \
        "loss 5%" \
        "${TIMESTAMP}_loss_5pct"
    
    # Scenario 4: Delay 100ms (WAN delay)
    run_scenario \
        "Delay 100ms (WAN delay)" \
        "delay 100ms" \
        "${TIMESTAMP}_delay_100ms"
    
    # Generate summary
    generate_summary
    
    # Generate plots if the analysis script exists
    if [ -f "${SCRIPT_DIR}/analyze_metrics.py" ]; then
        print_header "GENERATING ANALYSIS AND PLOTS"
        python3 "${SCRIPT_DIR}/analyze_metrics.py" \
            --results-dir "$RESULTS_DIR" \
            --plots-dir "$PLOTS_DIR" \
            --timestamp "$TIMESTAMP"
    fi
    
    # Fix permissions so non-root user can access results
    if [ -n "$SUDO_USER" ]; then
        print_info "Fixing file permissions for user $SUDO_USER..."
        chown -R "$SUDO_USER:$SUDO_USER" "$RESULTS_DIR" "$LOGS_DIR" "$PLOTS_DIR" "$PCAPS_DIR" "$SERVER_METRICS_DIR" 2>/dev/null || true
    fi
    
    print_header "ALL TESTS COMPLETED"
    print_info "Results: $RESULTS_DIR"
    print_info "Logs: $LOGS_DIR"
    print_info "Plots: $PLOTS_DIR"
    
    # Final cleanup
    cleanup_netem
}

# Trap to ensure cleanup on exit
trap 'cleanup_netem; pkill -f "python3.*server.py" 2>/dev/null || true; pkill -f "python3.*client_test.py" 2>/dev/null || true' EXIT

# Run main
main "$@"
