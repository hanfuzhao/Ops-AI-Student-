#!/usr/bin/env python3
"""
Compute monitoring metrics and check against thresholds.

Loads baseline and new data, runs all metrics, checks alert thresholds,
and outputs results to metrics-*.json file.
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime
from metric_template import MetricComputer


def load_data():
    baseline = pd.read_parquet("data/demand_enriched_baseline.parquet")
    week4 = pd.read_parquet("data/demand_enriched_week4.parquet")

    # Filter to Feb 2-28
    week4_filtered = week4[
        (pd.to_datetime(week4['time_bucket']).dt.date >= pd.Timestamp('2026-02-02').date()) &
        (pd.to_datetime(week4['time_bucket']).dt.date <= pd.Timestamp('2026-02-28').date())
    ].copy()

    print(f"Baseline: {baseline.shape[0]} rows, Week 4: {week4_filtered.shape[0]} rows")
    return baseline, week4_filtered


def compute_metrics(baseline, new_data):
    """Compute all metrics."""
    print("\nComputing metrics...")
    computer = MetricComputer(baseline)
    results = computer.compute_all_metrics(new_data)
    return results


def check_thresholds(metrics):
    """Check metrics against alert thresholds."""
    alerts = []
    alert_details = {}

    # 1. Null rate check
    null_rates = metrics['null_rates']
    for field, rate in null_rates.items():
        if rate > 0.01:  # 1% threshold
            alerts.append(f"NULL_RATE_{field.upper()}")
            alert_details[f"null_rate_{field}"] = {
                'value': rate,
                'threshold': 0.01,
                'severity': 'HIGH' if rate > 0.05 else 'MEDIUM'
            }

    # 2. Duplicate rate check
    dup_rate = metrics['duplicate_rate']['rate']
    if dup_rate > 0.005:  # 0.5% threshold
        alerts.append("DUPLICATE_RATE_HIGH")
        alert_details['duplicate_rate'] = {
            'value': dup_rate,
            'threshold': 0.005,
            'severity': 'HIGH' if dup_rate > 0.01 else 'MEDIUM'
        }

    # 3. KS test checks
    ks_tests = metrics['ks_tests']
    for feature, results in ks_tests.items():
        if results['significant']:
            alerts.append(f"DISTRIBUTION_SHIFT_{feature.upper()}")
            alert_details[f"ks_{feature}"] = {
                'p_value': results['p_value'],
                'threshold': 0.05,
                'severity': 'HIGH' if results['p_value'] < 0.01 else 'MEDIUM'
            }

    # 4. PSI check
    psi = metrics['psi']
    if psi > 0.25:  # Significant change threshold
        alerts.append("PSI_HIGH")
        alert_details['psi'] = {
            'value': psi,
            'threshold': 0.25,
            'severity': 'HIGH' if psi > 0.5 else 'MEDIUM'
        }

    # 5. Data freshness check
    freshness = metrics['data_freshness']
    if freshness['age_hours'] > 4:
        alerts.append("DATA_STALE")
        alert_details['data_freshness'] = {
            'age_hours': freshness['age_hours'],
            'threshold': 4,
            'severity': 'LOW'
        }

    return alerts, alert_details


def main():
    """Main function."""
    print("=" * 70)
    print("MONITORING METRICS COMPUTATION")
    print("=" * 70)

    # Load data
    baseline, new_data = load_data()

    # Compute metrics
    metrics = compute_metrics(baseline, new_data)

    # Check thresholds
    alerts, alert_details = check_thresholds(metrics)

    # Prepare output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Convert numpy types to Python types for JSON serialization
    def convert_to_serializable(obj):
        if isinstance(obj, dict):
            return {k: convert_to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_serializable(v) for v in obj]
        elif isinstance(obj, (bool, np.bool_)):
            return bool(obj)
        elif isinstance(obj, (int, np.integer)):
            return int(obj)
        elif isinstance(obj, (float, np.floating)):
            return float(obj)
        else:
            return obj

    ks_tests_clean = {k: convert_to_serializable(v) for k, v in metrics['ks_tests'].items()}

    output = {
        'timestamp': timestamp,
        'baseline_shape': list(baseline.shape),
        'new_data_shape': list(new_data.shape),
        'metrics': {
            'accuracy': float(metrics['accuracy']),
            'null_rates': {k: float(v) for k, v in metrics['null_rates'].items()},
            'duplicate_rate': {k: (float(v) if isinstance(v, (int, float)) else v)
                             for k, v in metrics['duplicate_rate'].items()},
            'ks_tests': ks_tests_clean,
            'psi': float(metrics['psi']),
            'prediction_distribution': {k: (float(v) if isinstance(v, (int, float)) else v)
                                      for k, v in metrics['prediction_distribution'].items()},
            'data_freshness': {k: float(v) if isinstance(v, (int, float)) else v
                             for k, v in metrics['data_freshness'].items()},
            'accuracy_by_zone': {str(k): float(v) for k, v in metrics['accuracy_by_zone'].items()}
        },
        'alerts': alerts,
        'alert_details': alert_details,
        'alert_count': len(alerts)
    }

    # Write to file
    output_file = f"metrics-{timestamp}.json"
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"\nBaseline accuracy: {metrics['accuracy']:.2%}")
    print(f"Trip count PSI: {metrics['psi']:.4f}")
    print(f"  - PSI < 0.10: negligible")
    print(f"  - PSI 0.10-0.25: small")
    print(f"  - PSI > 0.25: significant")
    print(f"\nNull rates (baseline=0%):")
    for field, rate in metrics['null_rates'].items():
        status = "ok" if rate < 0.01 else "ALERT"
        print(f"  [{status}] {field}: {rate:.4f}")

    print(f"\nDuplicate rate: {metrics['duplicate_rate']['rate']:.4f}")
    print(f"KS Tests (p-value < 0.05 = significant shift):")
    for feature, results in metrics['ks_tests'].items():
        status = "SHIFT" if results['significant'] else "ok"
        print(f"  [{status}] {feature}: p={results['p_value']:.6f}")

    print(f"\n{'=' * 70}")
    print(f"ALERTS: {len(alerts)}")
    print(f"{'=' * 70}")
    if alerts:
        for alert in alerts:
            print(f"  - {alert}")
        print(f"\nAlert output file: {output_file}")
        return 1  # Exit with error code to trigger CI failure
    else:
        print("  No alerts triggered")
        print(f"\nMetrics output file: {output_file}")
        return 0


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
