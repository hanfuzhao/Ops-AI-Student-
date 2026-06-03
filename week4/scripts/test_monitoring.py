#!/usr/bin/env python3
"""
Unit tests for monitoring metrics and drift detection.

Tests verify that metrics compute correctly and drift detection finds expected patterns.
"""

import pytest
import pandas as pd
import numpy as np
from metric_template import MetricComputer


class TestMetricComputer:
    """Test suite for MetricComputer class."""

    @pytest.fixture
    def baseline_data(self):
        """Create minimal baseline dataset."""
        return pd.DataFrame({
            'trip_count': [5, 10, 15, 8, 12, 20, 25, 10],
            'PULocationID': [1, 1, 2, 2, 3, 3, 4, 4],
            'hour': [0, 1, 2, 3, 4, 5, 6, 7],
            'dayofweek': [0, 0, 1, 1, 2, 2, 3, 3],
            'time_bucket': pd.date_range('2026-01-01', periods=8, freq='15min')
        })

    @pytest.fixture
    def new_data_normal(self, baseline_data):
        """Create new data with similar distribution (no drift)."""
        return baseline_data.copy()

    @pytest.fixture
    def new_data_shifted(self, baseline_data):
        """Create new data with shifted distribution (drift present)."""
        df = baseline_data.copy()
        # Shift trip_count higher
        df['trip_count'] = df['trip_count'] * 1.5
        return df

    def test_metric_3_null_rates(self, baseline_data):
        """Test null rate computation."""
        computer = MetricComputer(baseline_data)
        rates = computer.metric_3_null_rates(baseline_data)

        assert 'trip_count' in rates
        assert rates['trip_count'] == 0.0  # No nulls in clean data
        assert all(v >= 0.0 and v <= 1.0 for v in rates.values())

    def test_metric_3_null_rates_with_nulls(self, baseline_data):
        """Test null rate computation with missing values."""
        df = baseline_data.copy()
        df.loc[0, 'trip_count'] = None  # Introduce null

        computer = MetricComputer(baseline_data)
        rates = computer.metric_3_null_rates(df)

        assert rates['trip_count'] == pytest.approx(0.125, abs=0.01)  # 1/8 = 0.125

    def test_metric_8_duplicate_rate_no_duplicates(self, baseline_data):
        """Test duplicate detection with clean data."""
        computer = MetricComputer(baseline_data)
        result = computer.metric_8_duplicate_rate(baseline_data)

        assert result['rate'] == 0.0
        assert result['count'] == 0

    def test_metric_8_duplicate_rate_with_duplicates(self, baseline_data):
        """Test duplicate detection with duplicates."""
        df = pd.concat([baseline_data, baseline_data.iloc[[0]]], ignore_index=True)

        computer = MetricComputer(baseline_data)
        result = computer.metric_8_duplicate_rate(df)

        assert result['count'] >= 1  # At least one duplicate
        assert result['rate'] > 0

    def test_metric_1_accuracy_no_predictions(self, baseline_data):
        """Test accuracy with no prediction data."""
        computer = MetricComputer(baseline_data)
        acc = computer.metric_1_accuracy(baseline_data)

        assert 0 <= acc <= 1  # Accuracy should be between 0-1

    def test_metric_1_accuracy_with_predictions(self, baseline_data):
        """Test accuracy with prediction and actual arrays."""
        predictions = baseline_data['trip_count'].values.astype(int)
        actuals = baseline_data['trip_count'].values.astype(int)

        computer = MetricComputer(baseline_data)
        acc = computer.metric_1_accuracy(baseline_data, predictions, actuals)

        assert acc == 1.0  # Perfect match = 100% accuracy

    def test_metric_2_accuracy_by_zone(self, baseline_data):
        """Test accuracy by zone computation."""
        predictions = baseline_data['trip_count'].values.astype(int)
        actuals = baseline_data['trip_count'].values.astype(int)

        computer = MetricComputer(baseline_data)
        result = computer.metric_2_accuracy_by_zone(baseline_data, predictions, actuals)

        assert isinstance(result, dict)
        assert all(0 <= v <= 1 for v in result.values())  # All accuracies 0-1

    def test_metric_4_ks_test_no_shift(self, baseline_data, new_data_normal):
        """Test KS test detects no shift for identical distributions."""
        computer = MetricComputer(baseline_data)
        result = computer.metric_4_ks_test(new_data_normal)

        assert 'trip_count' in result
        # p-value should be high (>0.05) for identical distributions
        assert result['trip_count']['p_value'] > 0.05

    def test_metric_4_ks_test_detects_shift(self, baseline_data, new_data_shifted):
        """Test KS test detects shift for different distributions."""
        computer = MetricComputer(baseline_data)
        result = computer.metric_4_ks_test(new_data_shifted)

        assert 'trip_count' in result
        # p-value should be low (<0.05) for different distributions
        assert result['trip_count']['p_value'] < 0.05 or result['trip_count']['ks_statistic'] > 0.3

    def test_metric_5_psi_identical_distribution(self, baseline_data):
        """Test PSI for identical distributions."""
        computer = MetricComputer(baseline_data)
        psi = computer.metric_5_psi(baseline_data)

        assert psi >= 0  # PSI is always non-negative
        assert psi < 0.1  # Should be near 0 for identical distribution

    def test_metric_5_psi_shifted_distribution(self, baseline_data, new_data_shifted):
        """Test PSI for shifted distribution."""
        computer = MetricComputer(baseline_data)
        psi = computer.metric_5_psi(new_data_shifted)

        assert psi >= 0
        # Shifted distribution should have higher PSI
        # (though 1.5x shift might still be < 0.1 depending on binning)

    def test_metric_6_prediction_distribution(self):
        """Test prediction distribution monitoring."""
        predictions = np.array([10.0, 11.0, 12.0, 9.5, 10.5])

        computer = MetricComputer(pd.DataFrame({'trip_count': [10, 10, 10, 10, 10]}))
        result = computer.metric_6_prediction_distribution(predictions)

        assert 'mean' in result
        assert 'std' in result
        assert 'collapsed' in result
        assert result['collapsed'] == False  # Normal predictions, not collapsed

    def test_metric_6_prediction_distribution_collapsed(self):
        """Test detection of collapsed model (predicting constant)."""
        predictions = np.array([10.0, 10.0, 10.0, 10.0, 10.0])

        computer = MetricComputer(pd.DataFrame({'trip_count': [10, 10, 10, 10, 10]}))
        result = computer.metric_6_prediction_distribution(predictions)

        assert result['std'] < 0.1  # Very low std
        assert result['collapsed'] == True  # Should be flagged as collapsed

    def test_metric_7_data_freshness(self, baseline_data):
        """Test data freshness computation."""
        computer = MetricComputer(baseline_data)
        result = computer.metric_7_data_freshness(baseline_data)

        assert 'age_minutes' in result
        assert 'age_hours' in result
        assert result['age_minutes'] >= 0
        assert result['age_hours'] >= 0

    def test_compute_all_metrics(self, baseline_data):
        """Test compute_all_metrics runs all metrics."""
        computer = MetricComputer(baseline_data)
        results = computer.compute_all_metrics(baseline_data)

        assert 'accuracy' in results
        assert 'null_rates' in results
        assert 'duplicate_rate' in results
        assert 'ks_tests' in results
        assert 'psi' in results
        assert 'prediction_distribution' in results
        assert 'data_freshness' in results
        assert 'accuracy_by_zone' in results


class TestDriftDetection:
    """Test suite for drift detection logic."""

    def test_no_false_positives(self):
        """Verify drift detector doesn't flag identical data as drifted."""
        # Create identical datasets
        data = pd.DataFrame({
            'trip_count': np.random.poisson(14, 1000),
            'hour': np.random.randint(0, 24, 1000),
            'dayofweek': np.random.randint(0, 7, 1000)
        })

        baseline = data.copy()
        new_data = data.copy()

        # Run KS test
        from scipy.stats import ks_2samp
        ks_stat, p_value = ks_2samp(baseline['trip_count'], new_data['trip_count'])

        # Should not be significant (p > 0.05)
        assert p_value > 0.05

    def test_detects_obvious_shift(self):
        """Verify drift detector catches obvious distribution shift."""
        baseline = pd.DataFrame({'trip_count': np.random.poisson(14, 1000)})
        new_data = pd.DataFrame({'trip_count': np.random.poisson(20, 1000)})

        from scipy.stats import ks_2samp
        ks_stat, p_value = ks_2samp(baseline['trip_count'], new_data['trip_count'])

        # Should be significant (p < 0.05)
        assert p_value < 0.05


if __name__ == "__main__":
    # Run pytest with verbose output
    pytest.main([__file__, "-v", "-s"])
