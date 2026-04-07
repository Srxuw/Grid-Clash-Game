#!/bin/bash
# ======================================
# GRID CLASH - CLEANUP SCRIPT
# ======================================
# Clears all test artifacts without running tests
#
# USAGE:
#   ./cleanup.sh          # Clean all directories
#   ./cleanup.sh --dry-run  # Show what would be deleted
#
# ======================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"
LOGS_DIR="${SCRIPT_DIR}/logs"
PLOTS_DIR="${SCRIPT_DIR}/plots"
PCAPS_DIR="${SCRIPT_DIR}/pcaps"
SERVER_METRICS_DIR="${SCRIPT_DIR}/server_metrics"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=false

if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    echo -e "${YELLOW}[DRY RUN] Showing what would be deleted...${NC}"
fi

cleanup_dir() {
    local dir="$1"
    local name="$2"
    
    if [ -d "$dir" ] && [ "$(ls -A "$dir" 2>/dev/null)" ]; then
        local count=$(ls -1 "$dir" 2>/dev/null | wc -l)
        if [ "$DRY_RUN" = true ]; then
            echo -e "  Would delete ${count} file(s) from ${name}/"
        else
            rm -f "${dir}"/* 2>/dev/null || true
            echo -e "${GREEN}[CLEANED]${NC} ${name}/ (${count} files)"
        fi
    else
        if [ "$DRY_RUN" = false ]; then
            echo -e "${YELLOW}[SKIP]${NC} ${name}/ (already empty or doesn't exist)"
        fi
    fi
}

echo ""
echo "========================================"
echo "GRID CLASH - CLEANUP"
echo "========================================"
echo ""

cleanup_dir "$LOGS_DIR" "logs"
cleanup_dir "$PCAPS_DIR" "pcaps"
cleanup_dir "$RESULTS_DIR" "results"
cleanup_dir "$SERVER_METRICS_DIR" "server_metrics"
cleanup_dir "$PLOTS_DIR" "plots"

# Clean stray files in root
stray_count=$(ls -1 "${SCRIPT_DIR}"/game_metrics_*.csv "${SCRIPT_DIR}"/authoritative_positions_*.csv 2>/dev/null | wc -l)
if [ "$stray_count" -gt 0 ]; then
    if [ "$DRY_RUN" = true ]; then
        echo -e "  Would delete ${stray_count} stray CSV file(s) from root"
    else
        rm -f "${SCRIPT_DIR}"/game_metrics_*.csv 2>/dev/null || true
        rm -f "${SCRIPT_DIR}"/authoritative_positions_*.csv 2>/dev/null || true
        echo -e "${GREEN}[CLEANED]${NC} Stray CSV files (${stray_count} files)"
    fi
fi

echo ""
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}Run without --dry-run to actually delete files${NC}"
else
    echo -e "${GREEN}Cleanup complete!${NC}"
fi
echo ""
