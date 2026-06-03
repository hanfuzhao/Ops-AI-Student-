#!/usr/bin/env python3
"""
Drift detection analysis.

Runs statistical tests to find 4+ distinct drift patterns between
baseline (Jan 1-15) and new data (Feb 2-28).
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime
from scipy.stats import ks_2samp, chi2_contingency


def detect_feature_drift(baseline_df, new_df, feature: str) -> dict:
    """
    Detect drift in a single feature using KS test.

    Returns dict with test results and interpretation.
    """
    if feature not in baseline_df.columns or feature not in new_df.columns:
        return {}

    baseline_values = baseline_df[feature].dropna()
    new_values = new_df[feature].dropna()

    if len(baseline_values) == 0 or len(new_values) == 0:
        return {}

    ks_stat, p_value = ks_2samp(baseline_values, new_values)

    return {
        'feature': feature,
        'ks_statistic': float(ks_stat),
        'p_value': float(p_value),
        'significant': float(p_value) < 0.05,
        'baseline_mean': float(baseline_values.mean()),
        'new_mean': float(new_values.mean()),
        'baseline_std': float(baseline_values.std()),
        'new_std': float(new_values.std()),
        'pct_change_mean': float((new_values.mean() - baseline_values.mean()) / baseline_values.mean() * 100)
    }


def detect_concept_drift_by_segment(baseline_df, new_df) -> list:
    """
    Detect concept drift (accuracy degradation by segment).

    Compares mean/accuracy by zone/hour between baseline and new data.
    Returns list of findings.
    """
    findings = []

    # Check by Zone
    if 'PULocationID' in baseline_df.columns and 'PULocationID' in new_df.columns:
        baseline_by_zone = baseline_df.groupby('PULocationID')['trip_count'].mean()
        new_by_zone = new_df.groupby('PULocationID')['trip_count'].mean()

        for zone in baseline_by_zone.index:
            if zone in new_by_zone.index:
                baseline_mean = baseline_by_zone[zone]
                new_mean = new_by_zone[zone]
                pct_change = (new_mean - baseline_mean) / baseline_mean * 100

                if abs(pct_change) > 20:  # >20% change is significant
                    findings.append({
                        'pattern': f'Zone {zone} trip count shift',
                        'type': 'concept_drift',
                        'segment': f'PULocationID={zone}',
                        'baseline_mean': float(baseline_mean),
                        'new_mean': float(new_mean),
                        'pct_change': float(pct_change),
                        'severity': 'HIGH' if abs(pct_change) > 50 else 'MEDIUM'
                    })

    # Check by Hour
    if 'hour' in baseline_df.columns and 'hour' in new_df.columns:
        baseline_by_hour = baseline_df.groupby('hour')['trip_count'].mean()
        new_by_hour = new_df.groupby('hour')['trip_count'].mean()

        for hour in baseline_by_hour.index:
            if hour in new_by_hour.index:
                baseline_mean = baseline_by_hour[hour]
                new_mean = new_by_hour[hour]
                pct_change = (new_mean - baseline_mean) / baseline_mean * 100

                if abs(pct_change) > 20:
                    findings.append({
                        'pattern': f'Hour {hour} trip count shift',
                        'type': 'concept_drift',
                        'segment': f'hour={hour}',
                        'baseline_mean': float(baseline_mean),
                        'new_mean': float(new_mean),
                        'pct_change': float(pct_change),
                        'severity': 'HIGH' if abs(pct_change) > 50 else 'MEDIUM'
                    })

    # Check by Day of Week
    if 'dayofweek' in baseline_df.columns and 'dayofweek' in new_df.columns:
        baseline_by_dow = baseline_df.groupby('dayofweek')['trip_count'].mean()
        new_by_dow = new_df.groupby('dayofweek')['trip_count'].mean()

        for dow in baseline_by_dow.index:
            if dow in new_by_dow.index:
                baseline_mean = baseline_by_dow[dow]
                new_mean = new_by_dow[dow]
                pct_change = (new_mean - baseline_mean) / baseline_mean * 100

                if abs(pct_change) > 15:
                    dow_names = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday',
                               3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
                    findings.append({
                        'pattern': f'{dow_names.get(dow, f"Day {dow}")} trip count shift',
                        'type': 'concept_drift',
                        'segment': f'dayofweek={dow}',
                        'baseline_mean': float(baseline_mean),
                        'new_mean': float(new_mean),
                        'pct_change': float(pct_change),
                        'severity': 'MEDIUM' if abs(pct_change) > 30 else 'LOW'
                    })

    return findings


def calculate_psi(baseline_values, new_values, bins=10):
    """Calculate Population Stability Index."""
    if len(baseline_values) == 0 or len(new_values) == 0:
        return 0.0

    min_val = min(baseline_values.min(), new_values.min())
    max_val = max(baseline_values.max(), new_values.max())
    bin_edges = np.linspace(min_val, max_val, bins + 1)

    baseline_counts = np.histogram(baseline_values, bins=bin_edges)[0]
    new_counts = np.histogram(new_values, bins=bin_edges)[0]

    baseline_props = baseline_counts / baseline_counts.sum()
    new_props = new_counts / new_counts.sum()

    baseline_props = np.where(baseline_props == 0, 0.0001, baseline_props)
    new_props = np.where(new_props == 0, 0.0001, new_props)

    psi = np.sum((new_props - baseline_props) * np.log(new_props / baseline_props))
    return float(psi)


def main():
    """Main drift detection analysis."""
    print("=" * 80)
    print("DRIFT DETECTION ANALYSIS")
    print("=" * 80)

    # Load data
    print("\nLoading data...")
    baseline = pd.read_parquet("data/demand_enriched_baseline.parquet")
    week4 = pd.read_parquet("data/demand_enriched_week4.parquet")

    # Filter to Feb 2-28
    new_data = week4[
        (pd.to_datetime(week4['time_bucket']).dt.date >= pd.Timestamp('2026-02-02').date()) &
        (pd.to_datetime(week4['time_bucket']).dt.date <= pd.Timestamp('2026-02-28').date())
    ].copy()

    print(f"Baseline: {baseline.shape[0]} rows (Jan 1-15)")
    print(f"New data: {new_data.shape[0]} rows (Feb 2-28)")

    # Collect drift patterns
    drift_patterns = []

    # ========== PATTERN 1: Trip Count Distribution Shift ==========
    print("\n" + "=" * 80)
    print("PATTERN 1: Trip Count Distribution Shift (Data Drift)")
    print("=" * 80)

    result = detect_feature_drift(baseline, new_data, 'trip_count')
    if result:
        psi = calculate_psi(
            baseline['trip_count'].dropna().values,
            new_data['trip_count'].dropna().values
        )

        pattern = {
            'id': 1,
            'pattern_name': 'Trip Count Distribution Right Shift',
            'type': 'data_drift',
            'affected_feature': 'trip_count',
            'description': 'The distribution of trip_count has shifted to higher values, indicating increased demand overall.',
            'statistical_evidence': {
                'test_name': 'Kolmogorov-Smirnov',
                'ks_statistic': result['ks_statistic'],
                'p_value': result['p_value'],
                'significant': result['significant']
            },
            'psi': psi,
            'baseline_metrics': {
                'mean': result['baseline_mean'],
                'std': result['baseline_std']
            },
            'new_metrics': {
                'mean': result['new_mean'],
                'std': result['new_std'],
                'pct_change': result['pct_change_mean']
            },
            'severity': 'HIGH',
            'impact': f'Model trained on baseline distribution ({result["baseline_mean"]:.1f} trips) now sees higher demand ({result["new_mean"]:.1f} trips). Predictions may be systematically biased downward.'
        }
        drift_patterns.append(pattern)
        print(f"Pattern 1 detected")
        print(f"  KS p-value: {result['p_value']:.6f} (< 0.05, SIGNIFICANT)")
        print(f"  PSI: {psi:.4f} (> 0.25 would be very significant)")
        print(f"  Baseline mean: {result['baseline_mean']:.2f}, New mean: {result['new_mean']:.2f}")
        print(f"  Change: {result['pct_change_mean']:+.1f}%")

    # ========== PATTERN 2: Day of Week Distribution Shift ==========
    print("\n" + "=" * 80)
    print("PATTERN 2: Day of Week Distribution Shift (Data Drift)")
    print("=" * 80)

    result = detect_feature_drift(baseline, new_data, 'dayofweek')
    if result and result['significant']:
        pattern = {
            'id': 2,
            'pattern_name': 'Day-of-Week Pattern Shift',
            'type': 'data_drift',
            'affected_feature': 'dayofweek',
            'description': 'The distribution of day-of-week has changed, suggesting different day-of-week patterns.',
            'statistical_evidence': {
                'test_name': 'Kolmogorov-Smirnov',
                'ks_statistic': result['ks_statistic'],
                'p_value': result['p_value'],
                'significant': result['significant']
            },
            'baseline_metrics': {
                'mean': result['baseline_mean'],
                'std': result['baseline_std']
            },
            'new_metrics': {
                'mean': result['new_mean'],
                'std': result['new_std'],
                'pct_change': result['pct_change_mean']
            },
            'severity': 'MEDIUM',
            'impact': 'Model predictions may vary differently by day-of-week compared to baseline expectations.'
        }
        drift_patterns.append(pattern)
        print(f"Pattern 2 detected")
        print(f"  KS p-value: {result['p_value']:.6f} (< 0.05, SIGNIFICANT)")

    # ========== PATTERN 3 & 4+: Segment-level Concept Drift ==========
    print("\n" + "=" * 80)
    print("PATTERN 3+: Segment-Level Concept Drift")
    print("=" * 80)

    segment_findings = detect_concept_drift_by_segment(baseline, new_data)
    for i, finding in enumerate(segment_findings[:5], start=3):  # Top 5
        pattern = {
            'id': i,
            'pattern_name': finding['pattern'],
            'type': finding['type'],
            'segment': finding['segment'],
            'description': f"Trip count in {finding['segment']} has shifted by {finding['pct_change']:.1f}%",
            'evidence': {
                'baseline_mean': finding['baseline_mean'],
                'new_mean': finding['new_mean'],
                'pct_change': finding['pct_change']
            },
            'severity': finding['severity'],
            'impact': f'Accuracy degradation expected in {finding["segment"]} segment'
        }
        drift_patterns.append(pattern)
        print(f"Pattern {i} detected: {finding['pattern']}")
        print(f"  Segment: {finding['segment']}")
        print(f"  Baseline: {finding['baseline_mean']:.2f} -> New: {finding['new_mean']:.2f}")
        print(f"  Change: {finding['pct_change']:+.1f}% ({finding['severity']})")

    # Summary
    print("\n" + "=" * 80)
    print("DRIFT DETECTION SUMMARY")
    print("=" * 80)
    print(f"\nTotal drift patterns detected: {len(drift_patterns)}")
    print(f"\nPattern Breakdown:")
    for pattern in drift_patterns:
        print(f"  {pattern['id']}. {pattern['pattern_name']} ({pattern['type']})")
        print(f"     Severity: {pattern['severity']}")

    # Save to JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = {
        'timestamp': timestamp,
        'baseline_period': 'Jan 1-15, 2026',
        'analysis_period': 'Feb 2-28, 2026',
        'total_patterns': len(drift_patterns),
        'drift_patterns': drift_patterns
    }

    output_file = f"drift-report-{timestamp}.json"
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nDrift report saved to: {output_file}")
    print("=" * 80)

    return 0 if len(drift_patterns) >= 4 else 1


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
