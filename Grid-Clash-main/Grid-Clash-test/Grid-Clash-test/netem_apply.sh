#!/bin/bash
# ======================================
# NETEM HELPER SCRIPT - APPLY NETWORK IMPAIRMENT
# ======================================
#
# Usage: sudo ./netem_apply.sh <interface> <scenario>
#
# Scenarios:
#   baseline    - No impairment
#   loss_2      - 2% packet loss (LAN-like)
#   loss_5      - 5% packet loss (WAN-like)
#   delay_100   - 100ms delay (WAN delay)
#   custom      - Custom (prompts for parameters)
#
# Examples:
#   sudo ./netem_apply.sh lo baseline
#   sudo ./netem_apply.sh eth0 loss_2
#   sudo ./netem_apply.sh eth0 custom
#
# ======================================

set -e

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Please run with sudo"
    exit 1
fi

INTERFACE="${1:-lo}"
SCENARIO="${2:-baseline}"

# Verify interface exists
if ! ip link show "$INTERFACE" &> /dev/null; then
    echo "[ERROR] Interface $INTERFACE does not exist"
    echo "Available interfaces:"
    ip link show | grep -E "^[0-9]+:" | awk -F': ' '{print "  - " $2}'
    exit 1
fi

# Clear existing rules
echo "[INFO] Clearing existing rules on $INTERFACE..."
tc qdisc del dev "$INTERFACE" root 2>/dev/null || true

case "$SCENARIO" in
    baseline)
        echo "[INFO] Baseline - No impairment applied"
        ;;
    loss_2|loss_2pct)
        echo "[INFO] Applying 2% packet loss (LAN-like)..."
        tc qdisc add dev "$INTERFACE" root netem loss 2%
        ;;
    loss_5|loss_5pct)
        echo "[INFO] Applying 5% packet loss (WAN-like)..."
        tc qdisc add dev "$INTERFACE" root netem loss 5%
        ;;
    delay_100|delay_100ms)
        echo "[INFO] Applying 100ms delay (WAN delay)..."
        tc qdisc add dev "$INTERFACE" root netem delay 100ms
        ;;
    loss_delay)
        echo "[INFO] Applying combined: 2% loss + 50ms delay..."
        tc qdisc add dev "$INTERFACE" root netem loss 2% delay 50ms
        ;;
    jitter)
        echo "[INFO] Applying 50ms delay with 10ms jitter..."
        tc qdisc add dev "$INTERFACE" root netem delay 50ms 10ms
        ;;
    custom)
        echo "Enter netem parameters (e.g., 'loss 3% delay 50ms'):"
        read -r PARAMS
        tc qdisc add dev "$INTERFACE" root netem $PARAMS
        echo "[INFO] Applied: netem $PARAMS"
        ;;
    *)
        echo "[ERROR] Unknown scenario: $SCENARIO"
        echo "Available scenarios: baseline, loss_2, loss_5, delay_100, loss_delay, jitter, custom"
        exit 1
        ;;
esac

# Show current rules
echo ""
echo "[INFO] Current tc rules on $INTERFACE:"
tc qdisc show dev "$INTERFACE"
echo ""
