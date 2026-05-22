"""
Tests for the data quality checks.

Covers:
  - the clean baseline passes
  - the corrupted feed fails
  - each of the 4 issues gets detected
  - graceful degradation fixes things and the API doesn't crash

Run from the week3/ folder:
    python3 -m pytest validation/test_data_quality.py -v
"""
from pathlib import Path

import pandas as pd
import pytest

from validation.check_data_quality import (
    DataQualityValidator,
    TRIP_COUNT_MAX,
    apply_graceful_degradation,
    load_and_validate_data,
    validate_data,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BASELINE_PATH = DATA_DIR / "demand_enriched_baseline.parquet"
CORRUPTED_PATH = DATA_DIR / "demand_enriched_corrupted.parquet"


# The corrupted file is 6.3M rows, so load both files once for the whole run.
@pytest.fixture(scope="session")
def baseline_data():
    return pd.read_parquet(BASELINE_PATH)


@pytest.fixture(scope="session")
def corrupted_data():
    return pd.read_parquet(CORRUPTED_PATH)


@pytest.fixture
def validator(baseline_data):
    return DataQualityValidator(baseline_data)


def _types(result):
    return {issue["type"] for issue in result["issues"]}


class TestBaselineData:

    def test_baseline_passes_validation(self, baseline_data, validator):
        # Clean data should have zero issues.
        result = validator.validate(baseline_data)
        assert result["is_valid"], f"baseline failed: {result['issues']}"
        assert result["num_issues"] == 0

    def test_repaired_data_passes_validation(self, baseline_data, corrupted_data):
        # After fixing the corrupted data it should validate clean.
        result = validate_data(corrupted_data, baseline_data)
        cleaned, _ = apply_graceful_degradation(corrupted_data, result["issues"])
        recheck = DataQualityValidator(baseline_data).validate(cleaned)
        assert recheck["is_valid"]
        assert recheck["num_issues"] == 0


class TestDataQualityIssues:

    def test_corrupted_fails_validation(self, corrupted_data, validator):
        result = validator.validate(corrupted_data)
        assert not result["is_valid"]
        assert result["num_issues"] >= 4

    def test_detect_issue_1_duplicate_rows(self, corrupted_data, validator):
        # Issue 1: duplicate (zone, time_bucket) rows.
        result = validator.validate(corrupted_data)
        dup = next(i for i in result["issues"] if i["type"] == "duplicate_rows")
        assert dup["count"] == 10085
        assert dup["severity"] == "high"

    def test_detect_issue_2_negative_trip_count(self, corrupted_data, validator):
        # Issue 2: negative trip counts.
        result = validator.validate(corrupted_data)
        neg = next(i for i in result["issues"] if i["type"] == "negative_trip_count")
        assert neg["count"] > 0
        assert all(v < 0 for v in neg["sample_values"])
        assert neg["severity"] == "critical"

    def test_detect_issue_3_extreme_trip_count(self, corrupted_data, validator):
        # Issue 3: huge sentinel trip counts.
        result = validator.validate(corrupted_data)
        ext = next(i for i in result["issues"] if i["type"] == "extreme_trip_count")
        assert ext["count"] > 0
        assert all(v > TRIP_COUNT_MAX for v in ext["sample_values"])
        assert ext["severity"] == "critical"

    def test_detect_issue_4_holiday_drift(self, corrupted_data, validator):
        # Issue 4: holiday flag stuck on for a run of days.
        result = validator.validate(corrupted_data)
        drift = next(i for i in result["issues"] if i["type"] == "holiday_flag_drift")
        assert drift["count"] > 0
        assert len(drift["windows"]) >= 1


class TestNoFalsePositives:

    def test_isolated_holiday_not_flagged_as_drift(self, baseline_data):
        # A single real holiday shouldn't count as drift.
        df = baseline_data.copy()
        df["is_holiday"] = 0
        new_year = df["time_bucket"].dt.normalize() == pd.Timestamp("2026-01-01")
        df.loc[new_year, "is_holiday"] = 1
        result = DataQualityValidator().validate(df)
        assert "holiday_flag_drift" not in _types(result)

    def test_clean_trip_counts_not_flagged(self, baseline_data):
        result = DataQualityValidator().validate(baseline_data)
        assert "negative_trip_count" not in _types(result)
        assert "extreme_trip_count" not in _types(result)


class TestGracefulDegradation:

    def test_api_does_not_crash_with_bad_data(self, corrupted_data, baseline_data):
        # Should hand back a usable DataFrame, not raise.
        result = validate_data(corrupted_data, baseline_data)
        cleaned, _ = apply_graceful_degradation(corrupted_data, result["issues"])
        assert isinstance(cleaned, pd.DataFrame)
        assert len(cleaned) > 0

    def test_duplicates_removed(self, corrupted_data, baseline_data):
        result = validate_data(corrupted_data, baseline_data)
        cleaned, _ = apply_graceful_degradation(corrupted_data, result["issues"])
        assert not cleaned.duplicated(subset=["PULocationID", "time_bucket"]).any()

    def test_bad_trip_counts_repaired(self, corrupted_data, baseline_data):
        result = validate_data(corrupted_data, baseline_data)
        cleaned, _ = apply_graceful_degradation(corrupted_data, result["issues"])
        assert cleaned["trip_count"].min() >= 0
        assert cleaned["trip_count"].max() <= TRIP_COUNT_MAX

    def test_holiday_flags_repaired(self, corrupted_data, baseline_data):
        result = validate_data(corrupted_data, baseline_data)
        cleaned, _ = apply_graceful_degradation(corrupted_data, result["issues"])
        # Jan 8 isn't a holiday, so the flag should be off after the fix.
        jan8 = cleaned[(cleaned["time_bucket"] >= "2026-01-08")
                       & (cleaned["time_bucket"] < "2026-01-09")]
        assert (jan8["is_holiday"] == 0).all()

    def test_fallback_is_logged(self, corrupted_data, baseline_data):
        # The fixes should be written to a log so operators can see them.
        result = validate_data(corrupted_data, baseline_data)
        _, degrade_log = apply_graceful_degradation(corrupted_data, result["issues"])
        assert len(degrade_log) >= 3
        assert any("duplicate" in line for line in degrade_log)

    def test_load_falls_back_on_unreadable_file(self, baseline_data):
        # A missing file should fall back to the baseline, not crash.
        df = load_and_validate_data("does_not_exist.parquet", baseline_df=baseline_data)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_load_and_validate_returns_clean_data(self, baseline_data):
        # End to end: load the bad feed and check it comes back fixed.
        df = load_and_validate_data(CORRUPTED_PATH, baseline_df=baseline_data)
        assert df["trip_count"].min() >= 0
        assert df["trip_count"].max() <= TRIP_COUNT_MAX
        assert not df.duplicated(subset=["PULocationID", "time_bucket"]).any()
