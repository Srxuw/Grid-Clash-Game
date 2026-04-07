# Grid Clash - Test Automation & Metrics Collection

## Overview

This document describes the test automation system for Grid Clash, implementing **Sections 4 and 5** of the project requirements.

## Quick Start

```bash
# Make scripts executable
chmod +x run_all_tests.sh netem_apply.sh netem_clear.sh netem_status.sh cleanup.sh

# Run all tests (requires sudo for netem)
sudo ./run_all_tests.sh lo 2 30

# Analyze results and generate plots
python3 analyze_metrics.py --results-dir results --plots-dir plots

# Clean all test artifacts (logs, pcaps, results, plots, server_metrics)
./cleanup.sh

# Preview what would be deleted without actually deleting
./cleanup.sh --dry-run
```

## Test Scenarios (Section 4.1)

| Scenario | netem Command | Acceptance Criteria |
|----------|---------------|---------------------|
| Baseline | None | Avg latency ≤ 50 ms; Avg CPU < 60%; Update rate ≥ 20 Hz |
| Loss 2% (LAN-like) | `netem loss 2%` | Mean position error ≤ 0.5 units; P95 ≤ 1.5 units |
| Loss 5% (WAN-like) | `netem loss 5%` | Critical events ≥99% delivered within 200 ms; System stable |
| Delay 100ms | `netem delay 100ms` | Clients continue functioning |

## Files Created

### Test Client
- **`client_test.py`** - Automated test client with comprehensive metrics collection

### Test Automation
- **`run_all_tests.sh`** - Main test runner script
  - Runs all 4 test scenarios automatically
  - Applies network impairments using netem
  - Collects metrics from multiple clients
  - Merges results into consolidated CSV files

### Network Impairment Helpers
- **`netem_apply.sh`** - Apply network impairment rules
- **`netem_clear.sh`** - Clear all netem rules
- **`netem_status.sh`** - Show current netem status

### Analysis
- **`analyze_metrics.py`** - Metrics analysis and visualization
  - Calculates mean, median, 95th percentile
  - Checks acceptance criteria
  - Generates comparison plots

## Metrics Collected (Section 5)

Each test produces a CSV with the following columns:

| Metric | Description |
|--------|-------------|
| `client_id` | Numeric ID of the client |
| `snapshot_id` | Snapshot identifier |
| `seq_num` | Packet sequence number |
| `server_timestamp_ms` | Timestamp at server send |
| `recv_time_ms` | Timestamp at client receive |
| `latency_ms` | recv_time - server_timestamp |
| `jitter_ms` | Variation in inter-arrival times |
| `perceived_position_error` | Distance between server's authoritative position and client's displayed position |
| `cpu_percent` | CPU utilization |
| `bandwidth_per_client_kbps` | Average measured bandwidth per client |

## Usage Examples

### Running Individual Scenarios

```bash
# Apply network impairment manually
sudo ./netem_apply.sh lo loss_2

# Start server in one terminal
python3 server.py

# Start test clients in another terminal
python3 client_test.py --client-id 1 --duration 30 --output results/test1.csv &
python3 client_test.py --client-id 2 --duration 30 --output results/test2.csv &

# Clear impairment when done
sudo ./netem_clear.sh lo
```

### Running Full Test Suite

```bash
# Run all scenarios (loopback, 2 clients, 30 seconds each)
sudo ./run_all_tests.sh lo 2 30

# Run on a real network interface (use 'ip link show' to find yours)
# Common names: enp0s3, enp0s8, eth0, ens33
sudo ./run_all_tests.sh enp0s3 4 60
```

### Analyzing Results

```bash
# Analyze all results in the results directory
python3 analyze_metrics.py

# Analyze specific test run (by timestamp)
python3 analyze_metrics.py --timestamp 20241213_143000

# Custom output directory
python3 analyze_metrics.py --plots-dir my_plots --results-dir my_results
```

## Output Structure

```
Grid-Clash/
├── results/
│   ├── YYYYMMDD_HHMMSS_baseline_client1.csv
│   ├── YYYYMMDD_HHMMSS_baseline_client2.csv
│   ├── YYYYMMDD_HHMMSS_baseline_merged.csv
│   ├── YYYYMMDD_HHMMSS_loss_2pct_merged.csv
│   ├── YYYYMMDD_HHMMSS_loss_5pct_merged.csv
│   ├── YYYYMMDD_HHMMSS_delay_100ms_merged.csv
│   ├── scenario_comparison.csv
│   ├── analysis_report.txt
│   └── test_summary.txt
├── server_metrics/
│   ├── game_metrics_YYYYMMDD_HHMMSS.csv
│   ├── authoritative_positions_YYYYMMDD_HHMMSS.csv
│   └── ...
├── pcaps/
│   ├── YYYYMMDD_HHMMSS_baseline.pcap
│   ├── YYYYMMDD_HHMMSS_loss_2pct.pcap
│   ├── YYYYMMDD_HHMMSS_loss_5pct.pcap
│   └── YYYYMMDD_HHMMSS_delay_100ms.pcap
├── logs/
│   ├── YYYYMMDD_HHMMSS_baseline_server.log
│   ├── YYYYMMDD_HHMMSS_baseline_client1.log
│   └── ...
└── plots/
    ├── latency_comparison.png
    ├── jitter_comparison.png
    ├── position_error_comparison.png
    ├── cpu_comparison.png
    ├── bandwidth_comparison.png
    └── latency_timeline_*.png
```

**Note:** The test runner automatically cleans up all previous test artifacts (logs, pcaps, results, server_metrics, plots) before starting a new test run.

## Packet Capture (pcaps)

The test runner automatically captures packet traces for each scenario using tcpdump. These pcap files can be analyzed with Wireshark or tshark:

```bash
# View pcap summary
tshark -r pcaps/YYYYMMDD_HHMMSS_baseline.pcap -q -z io,stat,1

# Filter by port 12000 (server port)
tshark -r pcaps/YYYYMMDD_HHMMSS_loss_2pct.pcap -Y "udp.port == 12000"

# Open in Wireshark
wireshark pcaps/YYYYMMDD_HHMMSS_delay_100ms.pcap
```

Note: tcpdump requires root privileges. The test runner runs with sudo.

## Analysis Report Format

The analysis report includes:

1. **Per-Scenario Statistics**
   - Total packets received
   - Latency (mean, median, P95, min, max)
   - Jitter (mean, median, P95)
   - Position error (mean, median, P95)
   - CPU usage (mean, max)
   - Bandwidth (mean)

2. **Acceptance Criteria Check**
   - ✓ PASS / ✗ FAIL for each criterion

3. **Scenario Comparison CSV**
   - All metrics side-by-side for easy comparison

## Requirements

### System Requirements
- Linux (for netem commands)
- Root/sudo access (for network impairment)
- Python 3.6+

### Python Dependencies
```bash
pip install psutil matplotlib numpy
```

### Network Tools
```bash
# Ubuntu/Debian
sudo apt-get install iproute2

# The tc command should be available
which tc
```

## Troubleshooting

### Permission Denied
```bash
# Scripts need sudo for netem
sudo ./run_all_tests.sh
```

### Interface Not Found
```bash
# List available interfaces
ip link show

# Use loopback for local testing
sudo ./run_all_tests.sh lo 2 30
```

### No Results Generated
- Check logs in `logs/` directory
- Ensure server is running and accessible
- Verify network interface is correct

### matplotlib Not Installed
```bash
pip install matplotlib
# Plots will be skipped if matplotlib is not available
```

## Manual netem Commands Reference

```bash
# 2% packet loss (LAN-like)
sudo tc qdisc add dev lo root netem loss 2%

# 5% packet loss (WAN-like)
sudo tc qdisc add dev lo root netem loss 5%

# 100ms delay
sudo tc qdisc add dev lo root netem delay 100ms

# Combined: 2% loss + 50ms delay with 10ms jitter
sudo tc qdisc add dev lo root netem loss 2% delay 50ms 10ms

# Clear all rules
sudo tc qdisc del dev lo root

# Show current rules
tc qdisc show dev lo
```
