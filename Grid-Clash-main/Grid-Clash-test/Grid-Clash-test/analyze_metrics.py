#!/usr/bin/env python3
# ======================================
# GRID CLASH - METRICS ANALYSIS & VISUALIZATION
# ======================================
#
# PURPOSE: Analyze collected metrics and generate plots
# Produces:
#   - Summary statistics (mean, median, 95th percentile)
#   - Comparison across test scenarios
#   - Visualizations (latency, jitter, position error, bandwidth)
#
# USAGE:
#   python analyze_metrics.py --results-dir results --plots-dir plots
#
# ======================================

import os
import sys
import csv
import argparse
import statistics
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Try to import plotting libraries
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("[WARN] matplotlib not installed. Plots will not be generated.")
    print("       Install with: pip install matplotlib")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def load_csv(filepath):
    """Load metrics from a CSV file."""
    metrics = []
    try:
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert numeric fields
                for key in ['client_id', 'msg_type', 'snapshot_id', 'seq_num',
                           'server_timestamp_ms', 'recv_time_ms', 'latency_ms',
                           'jitter_ms', 'perceived_position_error', 'cpu_percent',
                           'bandwidth_per_client_kbps']:
                    if key in row and row[key]:
                        try:
                            row[key] = float(row[key])
                        except ValueError:
                            pass
                metrics.append(row)
    except Exception as e:
        print(f"[ERROR] Failed to load {filepath}: {e}")
    return metrics


def get_scenario_order(name):
    """Return a sort key to order scenarios: baseline, loss_2, loss_5, delay."""
    name_lower = name.lower()
    if 'baseline' in name_lower:
        return 0
    elif 'loss_2' in name_lower or '2pct' in name_lower:
        return 1
    elif 'loss_5' in name_lower or '5pct' in name_lower:
        return 2
    elif 'delay' in name_lower:
        return 3
    else:
        return 4


def sort_scenarios(scenario_names):
    """Sort scenario names in the correct order: baseline, 2% loss, 5% loss, 100ms delay."""
    return sorted(scenario_names, key=get_scenario_order)


def calculate_statistics(values):
    """Calculate mean, median, and 95th percentile."""
    if not values:
        return {'mean': 0, 'median': 0, 'p95': 0, 'min': 0, 'max': 0, 'count': 0}
    
    sorted_vals = sorted(values)
    p95_idx = int(len(sorted_vals) * 0.95)
    
    return {
        'mean': statistics.mean(values),
        'median': statistics.median(values),
        'p95': sorted_vals[min(p95_idx, len(sorted_vals)-1)],
        'min': min(values),
        'max': max(values),
        'count': len(values)
    }


def analyze_scenario(metrics):
    """Analyze metrics for a single scenario."""
    if not metrics:
        return {}
    
    # Extract values for analysis
    latencies = [m['latency_ms'] for m in metrics 
                 if isinstance(m.get('latency_ms'), (int, float)) and m['latency_ms'] > 0]
    jitters = [m['jitter_ms'] for m in metrics 
               if isinstance(m.get('jitter_ms'), (int, float)) and m['jitter_ms'] >= 0]
    errors = [m['perceived_position_error'] for m in metrics 
              if isinstance(m.get('perceived_position_error'), (int, float))]
    cpu = [m['cpu_percent'] for m in metrics 
           if isinstance(m.get('cpu_percent'), (int, float))]
    bandwidth = [m['bandwidth_per_client_kbps'] for m in metrics 
                 if isinstance(m.get('bandwidth_per_client_kbps'), (int, float))]
    
    # Count message types
    msg_types = defaultdict(int)
    for m in metrics:
        msg_types[m.get('msg_type_name', 'UNKNOWN')] += 1
    
    # Calculate update rate (updates per second per client)
    # Method: Use inter-packet timing for each client, then average
    # This gives the actual server tick rate as experienced by clients
    update_rate = 0
    unique_clients = set(m.get('client_id', 0) for m in metrics)
    client_rates = []
    
    for client_id in unique_clients:
        # Get update packets for this client (HEARTBEAT, DELTA, FULL)
        client_updates = [m for m in metrics 
                         if m.get('client_id') == client_id 
                         and m.get('msg_type_name') in ('HEARTBEAT', 'DELTA', 'FULL')]
        
        if len(client_updates) >= 10:  # Need enough packets
            # Sort by receive time
            sorted_updates = sorted(client_updates, key=lambda x: x.get('recv_time_ms', 0))
            
            # Skip first 10% to exclude connection setup
            skip_count = max(1, len(sorted_updates) // 10)
            sorted_updates = sorted_updates[skip_count:]
            
            if len(sorted_updates) >= 2:
                # Calculate inter-packet times
                times = [m.get('recv_time_ms', 0) for m in sorted_updates]
                diffs = [times[i+1] - times[i] for i in range(len(times)-1)]
                
                # Filter out outliers (gaps > 500ms indicate game pause or issue)
                valid_diffs = [d for d in diffs if 0 < d < 500]
                
                if valid_diffs:
                    avg_interval_ms = sum(valid_diffs) / len(valid_diffs)
                    if avg_interval_ms > 0:
                        client_rate = 1000.0 / avg_interval_ms
                        client_rates.append(client_rate)
    
    if client_rates:
        update_rate = sum(client_rates) / len(client_rates)
    
    # Calculate critical event delivery rate (packets delivered within 200ms)
    # Critical events are DELTA and FULL messages (game state changes)
    critical_events = [m for m in metrics 
                       if m.get('msg_type_name') in ('DELTA', 'FULL')]
    critical_within_200ms = [m for m in critical_events 
                             if isinstance(m.get('latency_ms'), (int, float)) 
                             and m['latency_ms'] <= 200]
    
    if critical_events:
        critical_delivery_rate = (len(critical_within_200ms) / len(critical_events)) * 100
    else:
        critical_delivery_rate = 100.0  # No critical events = 100% delivered
    
    return {
        'latency': calculate_statistics(latencies),
        'jitter': calculate_statistics(jitters),
        'position_error': calculate_statistics(errors),
        'cpu': calculate_statistics(cpu),
        'bandwidth': calculate_statistics(bandwidth),
        'total_packets': len(metrics),
        'message_types': dict(msg_types),
        'unique_clients': len(unique_clients),
        'update_rate': update_rate,
        'critical_events_total': len(critical_events),
        'critical_events_within_200ms': len(critical_within_200ms),
        'critical_delivery_rate': critical_delivery_rate
    }


def check_acceptance_criteria(scenario_name, analysis):
    """Check if scenario meets acceptance criteria from Section 4.1."""
    results = []
    
    if 'baseline' in scenario_name.lower():
        # Baseline: avg latency ≤ 50 ms; avg CPU < 60%; update rate ≥ 20 Hz
        latency_ok = analysis['latency']['mean'] <= 50
        cpu_ok = analysis['cpu']['mean'] < 60
        update_rate_ok = analysis.get('update_rate', 0) >= 20
        results.append(('Avg Latency ≤ 50ms', latency_ok, 
                       f"{analysis['latency']['mean']:.2f}ms"))
        results.append(('Avg CPU < 60%', cpu_ok, 
                       f"{analysis['cpu']['mean']:.2f}%"))
        results.append(('Update Rate ≥ 20 Hz', update_rate_ok,
                       f"{analysis.get('update_rate', 0):.1f} Hz"))
        
    elif 'loss_2' in scenario_name.lower() or '2%' in scenario_name:
        # Loss 2%: Mean position error ≤ 0.5 units; 95th ≤ 1.5 units
        error_mean_ok = analysis['position_error']['mean'] <= 0.5
        error_p95_ok = analysis['position_error']['p95'] <= 1.5
        results.append(('Mean Position Error ≤ 0.5', error_mean_ok,
                       f"{analysis['position_error']['mean']:.4f}"))
        results.append(('P95 Position Error ≤ 1.5', error_p95_ok,
                       f"{analysis['position_error']['p95']:.4f}"))
        
    elif 'loss_5' in scenario_name.lower() or '5%' in scenario_name:
        # Loss 5%: Critical events ≥99% delivered within 200ms; system remains stable
        critical_rate = analysis.get('critical_delivery_rate', 0)
        critical_ok = critical_rate >= 99.0
        stable = analysis['total_packets'] > 0 and analysis['latency']['mean'] < 500
        
        results.append(('Critical Events ≥99% within 200ms', critical_ok,
                       f"{critical_rate:.1f}% ({analysis.get('critical_events_within_200ms', 0)}/{analysis.get('critical_events_total', 0)})"))
        results.append(('System Stable', stable,
                       f"{analysis['total_packets']} packets, {analysis['latency']['mean']:.1f}ms avg latency"))
        
    elif 'delay' in scenario_name.lower():
        # Delay 100ms: Clients continue functioning
        functioning = analysis['total_packets'] > 0
        results.append(('Clients Functioning', functioning,
                       f"{analysis['total_packets']} packets"))
    
    return results


def generate_report(scenarios, output_file):
    """Generate a text report of the analysis."""
    lines = []
    lines.append("=" * 70)
    lines.append("GRID CLASH - METRICS ANALYSIS REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # Sort scenarios in correct order
    sorted_names = sort_scenarios(scenarios.keys())
    
    for name in sorted_names:
        analysis = scenarios[name]
        lines.append("-" * 70)
        lines.append(f"SCENARIO: {name}")
        lines.append("-" * 70)
        lines.append("")
        
        lines.append(f"Total Packets: {analysis['total_packets']}")
        lines.append(f"Unique Clients: {analysis['unique_clients']}")
        lines.append("")
        
        lines.append("Message Types:")
        for msg_type, count in analysis['message_types'].items():
            lines.append(f"  {msg_type}: {count}")
        lines.append("")
        
        lines.append("LATENCY (ms):")
        lines.append(f"  Mean:   {analysis['latency']['mean']:.2f}")
        lines.append(f"  Median: {analysis['latency']['median']:.2f}")
        lines.append(f"  P95:    {analysis['latency']['p95']:.2f}")
        lines.append(f"  Min:    {analysis['latency']['min']:.2f}")
        lines.append(f"  Max:    {analysis['latency']['max']:.2f}")
        lines.append("")
        
        lines.append("JITTER (ms):")
        lines.append(f"  Mean:   {analysis['jitter']['mean']:.2f}")
        lines.append(f"  Median: {analysis['jitter']['median']:.2f}")
        lines.append(f"  P95:    {analysis['jitter']['p95']:.2f}")
        lines.append("")
        
        lines.append("POSITION ERROR (units):")
        lines.append(f"  Mean:   {analysis['position_error']['mean']:.4f}")
        lines.append(f"  Median: {analysis['position_error']['median']:.4f}")
        lines.append(f"  P95:    {analysis['position_error']['p95']:.4f}")
        lines.append("")
        
        lines.append("CPU USAGE (%):")
        lines.append(f"  Mean:   {analysis['cpu']['mean']:.2f}")
        lines.append(f"  Max:    {analysis['cpu']['max']:.2f}")
        lines.append("")
        
        lines.append("BANDWIDTH (kbps per client):")
        lines.append(f"  Mean:   {analysis['bandwidth']['mean']:.2f}")
        lines.append("")
        
        lines.append("UPDATE RATE (Hz per client):")
        lines.append(f"  Rate:   {analysis.get('update_rate', 0):.1f}")
        lines.append("")
        
        lines.append("CRITICAL EVENT DELIVERY:")
        lines.append(f"  Total Critical Events:  {analysis.get('critical_events_total', 0)}")
        lines.append(f"  Delivered ≤200ms:       {analysis.get('critical_events_within_200ms', 0)}")
        lines.append(f"  Delivery Rate:          {analysis.get('critical_delivery_rate', 0):.1f}%")
        lines.append("")
        
        # Acceptance criteria check
        criteria = check_acceptance_criteria(name, analysis)
        if criteria:
            lines.append("ACCEPTANCE CRITERIA:")
            for criterion, passed, value in criteria:
                status = "✓ PASS" if passed else "✗ FAIL"
                lines.append(f"  [{status}] {criterion}: {value}")
            lines.append("")
    
    lines.append("=" * 70)
    
    report_text = "\n".join(lines)
    
    # Save to file
    with open(output_file, 'w') as f:
        f.write(report_text)
    
    print(report_text)
    return report_text


def generate_comparison_csv(scenarios, output_file):
    """Generate a CSV comparing all scenarios."""
    rows = []
    
    # Sort scenarios in correct order
    sorted_names = sort_scenarios(scenarios.keys())
    
    for name in sorted_names:
        analysis = scenarios[name]
        row = {
            'scenario': name,
            'total_packets': analysis['total_packets'],
            'unique_clients': analysis['unique_clients'],
            'latency_mean': analysis['latency']['mean'],
            'latency_median': analysis['latency']['median'],
            'latency_p95': analysis['latency']['p95'],
            'jitter_mean': analysis['jitter']['mean'],
            'jitter_median': analysis['jitter']['median'],
            'jitter_p95': analysis['jitter']['p95'],
            'position_error_mean': analysis['position_error']['mean'],
            'position_error_median': analysis['position_error']['median'],
            'position_error_p95': analysis['position_error']['p95'],
            'cpu_mean': analysis['cpu']['mean'],
            'cpu_max': analysis['cpu']['max'],
            'bandwidth_mean': analysis['bandwidth']['mean'],
            'update_rate_hz': analysis.get('update_rate', 0),
            'critical_delivery_rate_pct': analysis.get('critical_delivery_rate', 0)
        }
        rows.append(row)
    
    if rows:
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        
        print(f"[INFO] Comparison CSV saved to {output_file}")


def generate_plots(scenarios, raw_metrics, plots_dir):
    """Generate visualization plots."""
    if not HAS_MATPLOTLIB:
        print("[WARN] Skipping plot generation (matplotlib not installed)")
        return
    
    os.makedirs(plots_dir, exist_ok=True)
    
    scenario_names = sort_scenarios(scenarios.keys())
    
    # 1. Latency Comparison Bar Chart
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(scenario_names))
    means = [scenarios[s]['latency']['mean'] for s in scenario_names]
    medians = [scenarios[s]['latency']['median'] for s in scenario_names]
    p95s = [scenarios[s]['latency']['p95'] for s in scenario_names]
    
    width = 0.25
    ax.bar([i - width for i in x], means, width, label='Mean', color='steelblue')
    ax.bar(x, medians, width, label='Median', color='lightsteelblue')
    ax.bar([i + width for i in x], p95s, width, label='P95', color='darkblue')
    
    ax.set_xlabel('Scenario')
    ax.set_ylabel('Latency (ms)')
    ax.set_title('Latency Comparison Across Scenarios')
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace('_', '\n') for s in scenario_names], fontsize=8)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(plots_dir, 'latency_comparison.png'), dpi=150)
    plt.close()
    
    # 2. Jitter Comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    means = [scenarios[s]['jitter']['mean'] for s in scenario_names]
    p95s = [scenarios[s]['jitter']['p95'] for s in scenario_names]
    
    width = 0.35
    ax.bar([i - width/2 for i in x], means, width, label='Mean', color='coral')
    ax.bar([i + width/2 for i in x], p95s, width, label='P95', color='darkorange')
    
    ax.set_xlabel('Scenario')
    ax.set_ylabel('Jitter (ms)')
    ax.set_title('Jitter Comparison Across Scenarios')
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace('_', '\n') for s in scenario_names], fontsize=8)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(plots_dir, 'jitter_comparison.png'), dpi=150)
    plt.close()
    
    # 3. Position Error Comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    means = [scenarios[s]['position_error']['mean'] for s in scenario_names]
    p95s = [scenarios[s]['position_error']['p95'] for s in scenario_names]
    
    width = 0.35
    ax.bar([i - width/2 for i in x], means, width, label='Mean', color='seagreen')
    ax.bar([i + width/2 for i in x], p95s, width, label='P95', color='darkgreen')
    
    ax.set_xlabel('Scenario')
    ax.set_ylabel('Position Error (units)')
    ax.set_title('Perceived Position Error Across Scenarios')
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace('_', '\n') for s in scenario_names], fontsize=8)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Add acceptance criteria line for loss scenarios
    ax.axhline(y=0.5, color='red', linestyle='--', alpha=0.5, label='Mean Threshold (0.5)')
    ax.axhline(y=1.5, color='darkred', linestyle='--', alpha=0.5, label='P95 Threshold (1.5)')
    
    plt.tight_layout()
    plt.savefig(os.path.join(plots_dir, 'position_error_comparison.png'), dpi=150)
    plt.close()
    
    # 4. CPU Usage Comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    means = [scenarios[s]['cpu']['mean'] for s in scenario_names]
    maxes = [scenarios[s]['cpu']['max'] for s in scenario_names]
    
    width = 0.35
    ax.bar([i - width/2 for i in x], means, width, label='Mean', color='mediumpurple')
    ax.bar([i + width/2 for i in x], maxes, width, label='Max', color='darkviolet')
    
    ax.set_xlabel('Scenario')
    ax.set_ylabel('CPU Usage (%)')
    ax.set_title('CPU Usage Across Scenarios')
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace('_', '\n') for s in scenario_names], fontsize=8)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.axhline(y=60, color='red', linestyle='--', alpha=0.5, label='Threshold (60%)')
    
    plt.tight_layout()
    plt.savefig(os.path.join(plots_dir, 'cpu_comparison.png'), dpi=150)
    plt.close()
    
    # 5. Bandwidth Comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    means = [scenarios[s]['bandwidth']['mean'] for s in scenario_names]
    
    ax.bar(x, means, color='goldenrod')
    ax.set_xlabel('Scenario')
    ax.set_ylabel('Bandwidth (kbps per client)')
    ax.set_title('Average Bandwidth Per Client')
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace('_', '\n') for s in scenario_names], fontsize=8)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(plots_dir, 'bandwidth_comparison.png'), dpi=150)
    plt.close()
    
    # 6. Time series plots for each scenario (latency over time)
    for name, metrics in raw_metrics.items():
        if not metrics:
            continue
        
        # Sort by recv_time
        sorted_metrics = sorted(metrics, key=lambda m: m.get('recv_time_ms', 0))
        
        times = []
        latencies = []
        start_time = sorted_metrics[0].get('recv_time_ms', 0) if sorted_metrics else 0
        
        for m in sorted_metrics:
            if isinstance(m.get('latency_ms'), (int, float)) and m['latency_ms'] > 0:
                times.append((m['recv_time_ms'] - start_time) / 1000.0)  # Convert to seconds
                latencies.append(m['latency_ms'])
        
        if times and latencies:
            fig, ax = plt.subplots(figsize=(12, 4))
            ax.plot(times, latencies, 'b-', alpha=0.7, linewidth=0.5)
            ax.set_xlabel('Time (seconds)')
            ax.set_ylabel('Latency (ms)')
            ax.set_title(f'Latency Over Time - {name}')
            ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            safe_name = name.replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'pct')
            plt.savefig(os.path.join(plots_dir, f'latency_timeline_{safe_name}.png'), dpi=150)
            plt.close()
    
    print(f"[INFO] Plots saved to {plots_dir}")


def generate_acceptance_criteria_summary(scenarios, plots_dir):
    """Generate a summary plot showing all scenarios with their acceptance criteria status."""
    if not HAS_MATPLOTLIB:
        print("[WARN] Skipping acceptance criteria summary (matplotlib not installed)")
        return
    
    os.makedirs(plots_dir, exist_ok=True)
    
    # Collect all criteria results
    all_criteria = []
    for name, analysis in scenarios.items():
        criteria = check_acceptance_criteria(name, analysis)
        for criterion, passed, value in criteria:
            all_criteria.append({
                'scenario': name,
                'criterion': criterion,
                'passed': passed,
                'value': value,
                'analysis': analysis
            })
    
    if not all_criteria:
        print("[WARN] No acceptance criteria to display")
        return
    
    # Create the summary figure with multiple subplots
    fig = plt.figure(figsize=(16, 12))
    
    # ==================== SUBPLOT 1: Criteria Pass/Fail Matrix ====================
    ax1 = fig.add_subplot(2, 2, 1)
    
    scenario_names = sort_scenarios(scenarios.keys())
    criteria_by_scenario = {}
    
    for name in scenario_names:
        criteria_by_scenario[name] = check_acceptance_criteria(name, scenarios[name])
    
    # Create matrix data
    rows = []
    row_labels = []
    
    for name in scenario_names:
        criteria = criteria_by_scenario[name]
        short_name = name.split('_')[-1] if '_' in name else name
        short_name = short_name.replace('baseline', 'Baseline').replace('loss', 'Loss ').replace('pct', '%').replace('delay', 'Delay ')
        
        for crit_name, passed, value in criteria:
            rows.append([1 if passed else 0])
            row_labels.append(f"{short_name}\n{crit_name}")
    
    if rows:
        colors = ['#ff6b6b' if r[0] == 0 else '#51cf66' for r in rows]
        y_pos = range(len(rows))
        bars = ax1.barh(y_pos, [1] * len(rows), color=colors, edgecolor='black', linewidth=0.5)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(row_labels, fontsize=8)
        ax1.set_xlim(0, 1.5)
        ax1.set_xlabel('')
        ax1.set_title('Acceptance Criteria Results', fontsize=12, fontweight='bold')
        ax1.set_xticks([])
        
        # Add pass/fail labels
        for i, (r, label) in enumerate(zip(rows, row_labels)):
            status = 'PASS ✓' if r[0] == 1 else 'FAIL ✗'
            ax1.text(1.1, i, status, va='center', fontsize=9, 
                    color='green' if r[0] == 1 else 'red', fontweight='bold')
    
    ax1.invert_yaxis()
    
    # ==================== SUBPLOT 2: Key Metrics Bar Chart ====================
    ax2 = fig.add_subplot(2, 2, 2)
    
    # Short scenario names
    short_names = []
    for name in scenario_names:
        if 'baseline' in name.lower():
            short_names.append('Baseline')
        elif 'loss_2' in name.lower():
            short_names.append('Loss 2%')
        elif 'loss_5' in name.lower():
            short_names.append('Loss 5%')
        elif 'delay' in name.lower():
            short_names.append('Delay 100ms')
        else:
            short_names.append(name.split('_')[-1])
    
    x = range(len(scenario_names))
    width = 0.2
    
    latencies = [scenarios[s]['latency']['mean'] for s in scenario_names]
    jitters = [scenarios[s]['jitter']['mean'] for s in scenario_names]
    cpu = [scenarios[s]['cpu']['mean'] for s in scenario_names]
    
    ax2.bar([i - width for i in x], latencies, width, label='Latency (ms)', color='steelblue')
    ax2.bar(x, jitters, width, label='Jitter (ms)', color='coral')
    ax2.bar([i + width for i in x], cpu, width, label='CPU (%)', color='mediumpurple')
    
    ax2.set_xlabel('Scenario')
    ax2.set_ylabel('Value')
    ax2.set_title('Key Metrics Summary', fontsize=12, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(short_names, fontsize=9)
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # Add threshold lines
    ax2.axhline(y=50, color='steelblue', linestyle='--', alpha=0.5, linewidth=1)
    ax2.axhline(y=60, color='mediumpurple', linestyle='--', alpha=0.5, linewidth=1)
    
    # ==================== SUBPLOT 3: Position Error with Thresholds ====================
    ax3 = fig.add_subplot(2, 2, 3)
    
    means = [scenarios[s]['position_error']['mean'] for s in scenario_names]
    p95s = [scenarios[s]['position_error']['p95'] for s in scenario_names]
    
    width = 0.35
    ax3.bar([i - width/2 for i in x], means, width, label='Mean', color='seagreen')
    ax3.bar([i + width/2 for i in x], p95s, width, label='P95', color='darkgreen')
    
    ax3.axhline(y=0.5, color='red', linestyle='--', linewidth=2, label='Mean Threshold (0.5)')
    ax3.axhline(y=1.5, color='darkred', linestyle='--', linewidth=2, label='P95 Threshold (1.5)')
    
    ax3.set_xlabel('Scenario')
    ax3.set_ylabel('Position Error (units)')
    ax3.set_title('Position Error vs Thresholds', fontsize=12, fontweight='bold')
    ax3.set_xticks(x)
    ax3.set_xticklabels(short_names, fontsize=9)
    ax3.legend(loc='upper right', fontsize=8)
    ax3.grid(True, alpha=0.3)
    
    # ==================== SUBPLOT 4: Summary Statistics Table ====================
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis('off')
    
    # Create summary table
    table_data = []
    headers = ['Scenario', 'Packets', 'Latency\n(mean)', 'Jitter\n(mean)', 'Pos Error\n(mean)', 'CPU\n(mean)', 'Status']
    
    for name in scenario_names:
        analysis = scenarios[name]
        criteria = check_acceptance_criteria(name, analysis)
        all_passed = all(passed for _, passed, _ in criteria) if criteria else True
        status = '✓ PASS' if all_passed else '✗ FAIL'
        
        if 'baseline' in name.lower():
            short = 'Baseline'
        elif 'loss_2' in name.lower():
            short = 'Loss 2%'
        elif 'loss_5' in name.lower():
            short = 'Loss 5%'
        elif 'delay' in name.lower():
            short = 'Delay 100ms'
        else:
            short = name.split('_')[-1]
        
        table_data.append([
            short,
            f"{analysis['total_packets']}",
            f"{analysis['latency']['mean']:.1f}",
            f"{analysis['jitter']['mean']:.2f}",
            f"{analysis['position_error']['mean']:.4f}",
            f"{analysis['cpu']['mean']:.1f}%",
            status
        ])
    
    table = ax4.table(
        cellText=table_data,
        colLabels=headers,
        loc='center',
        cellLoc='center',
        colWidths=[0.15, 0.1, 0.12, 0.12, 0.14, 0.1, 0.12]
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)
    
    # Color the status column
    for i, row in enumerate(table_data):
        cell = table[(i + 1, 6)]  # +1 for header row
        if '✓' in row[6]:
            cell.set_facecolor('#d4edda')
        else:
            cell.set_facecolor('#f8d7da')
    
    # Header styling
    for j, header in enumerate(headers):
        table[(0, j)].set_facecolor('#4a90d9')
        table[(0, j)].set_text_props(color='white', fontweight='bold')
    
    ax4.set_title('Test Results Summary', fontsize=12, fontweight='bold', pad=20)
    
    # Overall title
    fig.suptitle('Grid Clash - Test Scenarios Summary', fontsize=14, fontweight='bold', y=0.98)
    
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(os.path.join(plots_dir, 'test_summary.png'), dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"[INFO] Test summary plot saved to {plots_dir}/test_summary.png")


def find_result_files(results_dir, timestamp=None):
    """Find all result files, optionally filtered by timestamp."""
    result_files = {}
    
    for f in Path(results_dir).glob('*_merged.csv'):
        name = f.stem.replace('_merged', '')
        
        # If timestamp specified, filter
        if timestamp and not name.startswith(timestamp):
            continue
        
        # Extract scenario name
        parts = name.split('_')
        if len(parts) >= 2:
            # Remove timestamp prefix
            if parts[0].isdigit():
                scenario = '_'.join(parts[1:])
            else:
                scenario = name
        else:
            scenario = name
        
        result_files[scenario] = str(f)
    
    # Also check for individual client files if no merged files
    if not result_files:
        for f in Path(results_dir).glob('*.csv'):
            if 'merged' not in f.stem and 'comparison' not in f.stem:
                name = f.stem
                result_files[name] = str(f)
    
    return result_files


def main():
    parser = argparse.ArgumentParser(description='Grid Clash Metrics Analyzer')
    parser.add_argument('--results-dir', type=str, default='results',
                        help='Directory containing result CSV files')
    parser.add_argument('--plots-dir', type=str, default='plots',
                        help='Directory to save plots')
    parser.add_argument('--timestamp', type=str, default=None,
                        help='Filter results by timestamp prefix')
    parser.add_argument('--output-report', type=str, default=None,
                        help='Output report filename')
    
    args = parser.parse_args()
    
    # Find result files
    result_files = find_result_files(args.results_dir, args.timestamp)
    
    if not result_files:
        print(f"[ERROR] No result files found in {args.results_dir}")
        return 1
    
    print(f"[INFO] Found {len(result_files)} result file(s)")
    
    # Load and analyze each file
    scenarios = {}
    raw_metrics = {}
    
    for name, filepath in result_files.items():
        print(f"[INFO] Analyzing: {name}")
        metrics = load_csv(filepath)
        if metrics:
            raw_metrics[name] = metrics
            scenarios[name] = analyze_scenario(metrics)
    
    if not scenarios:
        print("[ERROR] No metrics to analyze")
        return 1
    
    # Generate outputs
    os.makedirs(args.results_dir, exist_ok=True)
    
    # Report
    report_file = args.output_report or os.path.join(args.results_dir, 'analysis_report.txt')
    generate_report(scenarios, report_file)
    
    # Comparison CSV
    comparison_file = os.path.join(args.results_dir, 'scenario_comparison.csv')
    generate_comparison_csv(scenarios, comparison_file)
    
    # Plots
    generate_plots(scenarios, raw_metrics, args.plots_dir)
    
    # Summary plot with acceptance criteria
    generate_acceptance_criteria_summary(scenarios, args.plots_dir)
    
    print(f"\n[SUCCESS] Analysis complete!")
    print(f"  Report: {report_file}")
    print(f"  Comparison: {comparison_file}")
    print(f"  Plots: {args.plots_dir}/")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
