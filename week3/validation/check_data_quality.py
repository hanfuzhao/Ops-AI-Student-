"""
Data quality checks for the NYC cab demand pipeline.

I load the new upstream parquet, compare it to a clean baseline, and flag the
problems I found in Part 1:

    duplicate_rows      same (zone, time_bucket) row delivered twice
    negative_trip_count trip counts below zero
    extreme_trip_count  huge sentinel counts like 9999 / 99999
    holiday_flag_drift  is_holiday=1 stuck on for a whole stretch of days

There are also a few cheap guardrail checks (schema, nulls, ranges).

To run the check from the command line (this is what the GitHub Action calls),
cd into week3/ first:

    python3 -m validation.check_data_quality
"""
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("data_quality")

# A row is identified by its zone and its 15-minute bucket.
KEY_COLUMNS = ["PULocationID", "time_bucket"]

# Columns the model can't run without, so they must never be null.
CRITICAL_COLUMNS = ["PULocationID", "time_bucket", "trip_count", "hour", "dayofweek"]

# One zone in 15 minutes doesn't get more than a few hundred trips. Anything
# above this is a junk value (the bad feed has 9999 and 99999).
TRIP_COUNT_MAX = 2000

# Real holidays are single days (the longest real run is Christmas Eve + Day).
# So 3+ days in a row flagged as holiday means something is wrong.
HOLIDAY_RUN_THRESHOLD = 3

# How many nulls I'll tolerate in a normal column.
NULL_RATE_THRESHOLD = 0.02

# Allowed (min, max) for the categorical / time columns.
EXPECTED_RANGES = {
    "hour": (0, 23),
    "minute": (0, 45),
    "dayofweek": (0, 6),
    "month": (1, 12),
    "is_holiday": (0, 1),
    "is_weekend": (0, 1),
    "cbd_pricing_active": (0, 1),
    "is_airport_zone": (0, 1),
}

# Holiday calendar as (month, day). This matches the HOLIDAYS dict in
# backend/data.py so the fix below lines up with what the model expects.
US_HOLIDAYS = {
    (1, 1), (1, 20), (2, 17), (3, 17), (5, 26), (7, 4), (9, 1),
    (10, 13), (10, 31), (11, 11), (11, 27), (12, 24), (12, 25), (12, 31),
}


class DataQualityValidator:
    """Runs the quality checks on a demand DataFrame."""

    def __init__(self, baseline_df=None):
        # baseline_df is the clean reference data. The structural checks still
        # work without it, but schema/distribution checks need it.
        self.baseline = baseline_df
        self.issues = []

    def validate(self, df):
        """Run every check and return a result dict."""
        self.issues = []

        self.check_schema(df)
        self.check_null_rates(df)
        self.check_value_ranges(df)
        self.check_duplicates(df)
        self.check_holiday_drift(df)
        self.check_distributions(df)

        # Critical/high issues are bad enough to block a deploy.
        blocking = {"critical", "high"}
        is_valid = not any(i["severity"] in blocking for i in self.issues)
        return {
            "is_valid": is_valid,
            "num_issues": len(self.issues),
            "issues": self.issues,
        }

    def check_schema(self, df):
        """Make sure the expected columns exist and key columns have sane types."""
        if self.baseline is not None:
            required = list(self.baseline.columns)
        else:
            required = CRITICAL_COLUMNS

        missing = [c for c in required if c not in df.columns]
        if missing:
            self._add_issue("schema_mismatch", "critical",
                            f"missing required column(s): {missing}",
                            count=len(missing), columns=missing)

        if "time_bucket" in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df["time_bucket"]):
                self._add_issue("schema_mismatch", "critical",
                                "time_bucket is not a datetime column",
                                column="time_bucket")
        for col in ("PULocationID", "trip_count"):
            if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
                self._add_issue("schema_mismatch", "critical",
                                f"{col} is not numeric", column=col)

    def check_null_rates(self, df):
        """Critical columns can't have any nulls.

        I deliberately don't check the lag/rolling columns here, they are
        legitimately null at the start of each zone's history.
        """
        for col in CRITICAL_COLUMNS:
            if col not in df.columns:
                continue
            n_null = int(df[col].isna().sum())
            if n_null > 0:
                self._add_issue("null_in_critical_column", "high",
                                f"{col} has {n_null} null value(s), the model needs it",
                                count=n_null, column=col)

    def check_value_ranges(self, df):
        """trip_count sanity checks, plus range checks on the categorical columns."""
        if "trip_count" in df.columns:
            tc = df["trip_count"]

            negative = tc < 0
            n_neg = int(negative.sum())
            if n_neg > 0:
                bad_vals = sorted(tc[negative].unique().tolist())
                self._add_issue("negative_trip_count", "critical",
                                f"{n_neg} rows with negative trip_count {bad_vals}, "
                                f"demand can't be negative",
                                count=n_neg, sample_values=bad_vals,
                                first_seen=_first_time(df, negative))

            extreme = tc > TRIP_COUNT_MAX
            n_ext = int(extreme.sum())
            if n_ext > 0:
                bad_vals = sorted(tc[extreme].unique().tolist())
                self._add_issue("extreme_trip_count", "critical",
                                f"{n_ext} rows with trip_count > {TRIP_COUNT_MAX} "
                                f"(values {bad_vals}), looks like sentinel/overflow values",
                                count=n_ext, sample_values=bad_vals,
                                first_seen=_first_time(df, extreme))

        for col, (lo, hi) in EXPECTED_RANGES.items():
            if col not in df.columns:
                continue
            out_of_range = (df[col] < lo) | (df[col] > hi)
            n_out = int(out_of_range.sum())
            if n_out > 0:
                self._add_issue("value_out_of_range", "high",
                                f"{n_out} rows where {col} is outside [{lo}, {hi}]",
                                count=n_out, column=col)

    def check_duplicates(self, df):
        """Each (zone, time_bucket) should show up exactly once."""
        if not all(c in df.columns for c in KEY_COLUMNS):
            return
        dup_mask = df.duplicated(subset=KEY_COLUMNS, keep=False)
        n_dup = int(df.duplicated(subset=KEY_COLUMNS, keep="first").sum())
        if n_dup > 0:
            dups = df[dup_mask]
            zones = sorted(dups["PULocationID"].unique().tolist())
            window = f"{dups['time_bucket'].min()} .. {dups['time_bucket'].max()}"
            self._add_issue("duplicate_rows", "high",
                            f"{n_dup} duplicate (zone, time_bucket) rows in "
                            f"{len(zones)} zone(s), this double-counts demand",
                            count=n_dup, zones=zones, window=window)

    def check_holiday_drift(self, df):
        """is_holiday should only be on for isolated days, not long runs."""
        if "is_holiday" not in df.columns or "time_bucket" not in df.columns:
            return
        flagged = df.loc[df["is_holiday"] == 1, "time_bucket"]
        if flagged.empty:
            return

        # Get the distinct days that are flagged, then look for runs of
        # consecutive days.
        dates = sorted({pd.Timestamp(d).normalize()
                        for d in flagged.dt.normalize().unique()})
        runs = _consecutive_runs(dates)
        drift_runs = [(s, e) for s, e in runs
                      if (e - s).days + 1 >= HOLIDAY_RUN_THRESHOLD]
        if not drift_runs:
            return

        affected = 0
        windows = []
        for start, end in drift_runs:
            mask = ((df["time_bucket"] >= start)
                    & (df["time_bucket"] < end + pd.Timedelta(days=1))
                    & (df["is_holiday"] == 1))
            affected += int(mask.sum())
            windows.append(f"{start.date()}..{end.date()}")
        self._add_issue("holiday_flag_drift", "high",
                        f"is_holiday=1 for {len(drift_runs)} run(s) of "
                        f"{HOLIDAY_RUN_THRESHOLD}+ days in a row ({', '.join(windows)}), "
                        f"this messes up the holiday demand profile",
                        count=affected, windows=windows)

    def check_distributions(self, df):
        """Compare trip_count against the baseline as an extra guardrail.

        Uses the median instead of the mean so the extreme outliers (already
        caught above) don't trip it, this only fires on a real shift.
        """
        if self.baseline is None or "trip_count" not in df.columns:
            return
        if "PULocationID" not in df.columns or "trip_count" not in self.baseline:
            return

        base_zones = set(self.baseline["PULocationID"].unique())
        comparable = df[df["PULocationID"].isin(base_zones)]
        if len(comparable) < 100:
            return

        cur = comparable["trip_count"]
        cur = cur[(cur >= 0) & (cur <= TRIP_COUNT_MAX)]  # drop the known junk
        base_med = self.baseline["trip_count"].median()
        cur_med = cur.median()
        if base_med > 0:
            ratio = cur_med / base_med
            if ratio > 3 or ratio < 1 / 3:
                self._add_issue("distribution_shift", "medium",
                                f"trip_count median shifted {ratio:.1f}x vs baseline "
                                f"({base_med:.1f} -> {cur_med:.1f})",
                                baseline_median=float(base_med),
                                current_median=float(cur_med))

    def _add_issue(self, issue_type, severity, description, count=None, **details):
        # severity is one of: critical, high, medium, low
        self.issues.append({
            "type": issue_type,
            "severity": severity,
            "description": description,
            "count": count,
            **details,
        })


def _first_time(df, mask):
    """First time_bucket where mask is True (or None)."""
    if "time_bucket" not in df.columns or not mask.any():
        return None
    return str(df.loc[mask, "time_bucket"].min())


def _consecutive_runs(dates):
    """Turn a sorted list of dates into (start, end) runs of consecutive days."""
    if not dates:
        return []
    runs = []
    start = prev = dates[0]
    for d in dates[1:]:
        if (d - prev).days == 1:
            prev = d
        else:
            runs.append((start, prev))
            start = prev = d
    runs.append((start, prev))
    return runs


def validate_data(df, baseline_df=None):
    """Shortcut wrapper, same signature the assignment suggested."""
    return DataQualityValidator(baseline_df).validate(df)


# --- graceful degradation -------------------------------------------------

def apply_graceful_degradation(df, issues):
    """Fix the issues so the model still gets usable data.

    What I do for each issue:
      duplicate_rows      -> keep the first copy of each (zone, time_bucket)
      negative/extreme    -> blank out the bad values, fill with the
                             per-(zone, hour) median
      holiday_flag_drift  -> recompute is_holiday from the real calendar,
                             but only inside the bad window

    Returns the fixed DataFrame and a list of strings describing what changed,
    so nothing is fixed silently.
    """
    out = df.copy()
    log = []
    types = {i["type"] for i in issues}

    if "duplicate_rows" in types and all(c in out.columns for c in KEY_COLUMNS):
        before = len(out)
        out = out.drop_duplicates(subset=KEY_COLUMNS, keep="first")
        log.append(f"duplicate_rows: dropped {before - len(out)} duplicate "
                   f"(zone, time_bucket) rows")

    if ("negative_trip_count" in types or "extreme_trip_count" in types) \
            and "trip_count" in out.columns:
        tc = out["trip_count"]
        bad = (tc < 0) | (tc > TRIP_COUNT_MAX)
        n_bad = int(bad.sum())
        if n_bad:
            out.loc[bad, "trip_count"] = np.nan
            if {"PULocationID", "hour"}.issubset(out.columns):
                med = out.groupby(["PULocationID", "hour"])["trip_count"].transform("median")
            else:
                med = pd.Series(np.nan, index=out.index)
            global_med = float(out["trip_count"].median(skipna=True) or 0.0)
            out["trip_count"] = (out["trip_count"].fillna(med).fillna(global_med)
                                 .round().astype("int64"))
            log.append(f"trip_count: replaced {n_bad} bad values with the "
                       f"per-(zone, hour) median")

    if "holiday_flag_drift" in types and {"is_holiday", "time_bucket"}.issubset(out.columns):
        # Only fix inside the bad windows. If I recomputed the whole column I'd
        # wipe out the real (moving) holiday flags everywhere else.
        windows = []
        for issue in issues:
            if issue["type"] == "holiday_flag_drift":
                windows = issue.get("windows", [])
        valid_codes = {m * 100 + d for (m, d) in US_HOLIDAYS}
        n_fixed = 0
        for win in windows:
            start_s, end_s = win.split("..")
            start = pd.Timestamp(start_s)
            end = pd.Timestamp(end_s) + pd.Timedelta(days=1)
            in_win = (out["time_bucket"] >= start) & (out["time_bucket"] < end)
            codes = (out.loc[in_win, "time_bucket"].dt.month * 100
                     + out.loc[in_win, "time_bucket"].dt.day)
            correct = codes.isin(valid_codes).astype(out["is_holiday"].dtype)
            n_fixed += int((out.loc[in_win, "is_holiday"] != correct).sum())
            out.loc[in_win, "is_holiday"] = correct
        if n_fixed:
            log.append(f"is_holiday: recomputed inside the bad window from the "
                       f"real calendar, fixed {n_fixed} rows")

    return out, log


# Keep the last DataFrame that passed validation, so I can fall back to it if
# a later load fails completely.
_LAST_VALID = None


def load_and_validate_data(path, baseline_df=None, columns=None):
    """Load a parquet file, validate it, and degrade gracefully if needed.

    The API uses this instead of pd.read_parquet directly. It always returns
    something usable:
      - clean data           -> returned as-is
      - data with issues     -> fixed by apply_graceful_degradation
      - file won't load      -> last valid data, or the baseline
    """
    global _LAST_VALID
    try:
        df = pd.read_parquet(path, columns=columns)
    except Exception as exc:
        # The API must not crash here.
        logger.error("data load failed for %s: %s", path, exc)
        if _LAST_VALID is not None:
            logger.warning("falling back to last valid data (%d rows)", len(_LAST_VALID))
            return _LAST_VALID
        if baseline_df is not None:
            logger.warning("falling back to clean baseline data (%d rows)", len(baseline_df))
            return baseline_df
        raise

    # If we only loaded some columns, compare against the same subset of the
    # baseline, otherwise the schema check complains about "missing" columns.
    baseline_for_check = baseline_df
    if columns is not None and baseline_df is not None:
        baseline_for_check = baseline_df[
            [c for c in columns if c in baseline_df.columns]]

    result = DataQualityValidator(baseline_for_check).validate(df)
    if result["is_valid"] and result["num_issues"] == 0:
        logger.info("data quality OK, %d rows, no issues", len(df))
        _LAST_VALID = df
        return df

    logger.warning("data quality check found %d issue(s) in %s:",
                    result["num_issues"], path)
    for issue in result["issues"]:
        logger.warning("  [%s] %s (%s rows)",
                       issue["severity"], issue["description"], issue["count"])

    cleaned, degrade_log = apply_graceful_degradation(df, result["issues"])
    for line in degrade_log:
        logger.warning("  fixed -> %s", line)
    logger.warning("serving degraded data: %d rows (was %d)", len(cleaned), len(df))
    _LAST_VALID = cleaned
    return cleaned


# --- command line entry point (used by the GitHub Action) -----------------

def _run_cli():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    data_dir = Path("data")
    baseline_path = data_dir / "demand_enriched_baseline.parquet"
    current_path = data_dir / "demand_enriched_corrupted.parquet"

    if not current_path.exists():
        logger.error("data file not found: %s (did you run `git lfs pull`?)", current_path)
        return 1

    baseline = pd.read_parquet(baseline_path) if baseline_path.exists() else None
    if baseline is None:
        logger.warning("no baseline found, running structural checks only")

    current = pd.read_parquet(current_path)
    logger.info("validating %s (%d rows)", current_path, len(current))

    result = DataQualityValidator(baseline).validate(current)

    report = {
        "data_file": str(current_path),
        "rows": int(len(current)),
        "is_valid": result["is_valid"],
        "num_issues": result["num_issues"],
        "issues": result["issues"],
    }
    Path("validation-results.json").write_text(json.dumps(report, indent=2, default=str))
    logger.info("wrote validation-results.json")

    if result["num_issues"] == 0:
        logger.info("PASS, data quality validation passed")
        return 0

    print("\n" + "=" * 64)
    print(f"DATA QUALITY: {result['num_issues']} issue(s) found")
    print("=" * 64)
    for issue in result["issues"]:
        print(f"  [{issue['severity'].upper():8s}] {issue['type']}")
        print(f"             {issue['description']}")
    print("=" * 64)

    if not result["is_valid"]:
        logger.error("FAIL, critical/high issues found, blocking deployment")
        return 1
    logger.warning("PASS with warnings, only low/medium issues")
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
