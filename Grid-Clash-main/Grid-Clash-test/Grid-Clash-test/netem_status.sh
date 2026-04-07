#!/bin/bash
# ======================================
# NETEM HELPER SCRIPT - SHOW CURRENT STATUS
# ======================================
#
# Usage: ./netem_status.sh [interface]
#
# Shows current network impairment rules
#
# ======================================

echo "========================================"
echo "NETWORK IMPAIRMENT STATUS"
echo "========================================"
echo ""

if [ -n "$1" ]; then
    INTERFACE="$1"
    echo "Interface: $INTERFACE"
    echo "------------------------"
    tc qdisc show dev "$INTERFACE"
    echo ""
    
    # Show statistics if available
    tc -s qdisc show dev "$INTERFACE" 2>/dev/null | head -20
else
    echo "All interfaces:"
    echo "------------------------"
    
    for iface in $(ip link show | grep -E "^[0-9]+:" | awk -F': ' '{print $2}' | cut -d'@' -f1); do
        rules=$(tc qdisc show dev "$iface" 2>/dev/null | grep netem)
        if [ -n "$rules" ]; then
            echo ""
            echo "$iface:"
            echo "  $rules"
        fi
    done
    
    echo ""
    echo "Raw tc output:"
    echo "------------------------"
    tc qdisc show
fi

echo ""
echo "========================================"
