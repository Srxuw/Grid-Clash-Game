#!/bin/bash
# ======================================
# NETEM HELPER SCRIPT - CLEAR NETWORK IMPAIRMENT
# ======================================
#
# Usage: sudo ./netem_clear.sh [interface]
#
# Examples:
#   sudo ./netem_clear.sh          # Clear on all interfaces
#   sudo ./netem_clear.sh lo       # Clear on loopback only
#   sudo ./netem_clear.sh eth0     # Clear on eth0 only
#
# ======================================

set -e

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Please run with sudo"
    exit 1
fi

if [ -n "$1" ]; then
    # Clear specific interface
    INTERFACE="$1"
    echo "[INFO] Clearing netem rules on $INTERFACE..."
    tc qdisc del dev "$INTERFACE" root 2>/dev/null && \
        echo "[INFO] Rules cleared on $INTERFACE" || \
        echo "[INFO] No rules to clear on $INTERFACE"
else
    # Clear all interfaces
    echo "[INFO] Clearing netem rules on all interfaces..."
    for iface in $(ip link show | grep -E "^[0-9]+:" | awk -F': ' '{print $2}' | cut -d'@' -f1); do
        tc qdisc del dev "$iface" root 2>/dev/null && \
            echo "[INFO] Rules cleared on $iface" || true
    done
fi

echo ""
echo "[INFO] Current tc rules:"
tc qdisc show
echo ""
