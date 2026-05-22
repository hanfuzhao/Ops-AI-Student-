# Week 3 Report: Data Quality Validation

For this assignment I added data quality checks to the NYC cab demand API from
Week 2. The new upstream file (`demand_enriched_corrupted.parquet`, about 6.33M
rows) has problems in it, so I compared it against the clean baseline
(`demand_enriched_baseline.parquet`, 1,440 rows from zone 4, Jan 1-15) to find
out what was wrong.

## Issues I found

I found four issues in the corrupted data:

**1. Duplicate rows.** 10,085 rows are duplicates on (zone, time_bucket). They
show up in 5 zones (4, 43, 87, 107, 229) between Feb 7 and Feb 28. This matters
because the demand profile is built with a groupby, so duplicated rows get
counted twice. That inflates the heatmap, the KPIs, and the unmet-demand
numbers, which would lead to bad surge advice. Probably an upstream batch that
got delivered or ingested twice.

**2. Negative trip counts.** 353 rows have a `trip_count` of -1 or -5, starting
Jan 16. A trip count can't be negative. These drag the zone averages down and
feed garbage into the lag and rolling-average features the model uses. Likely a
sign error somewhere upstream.

**3. Extreme / sentinel values.** 311 rows have a `trip_count` of 9999 or 99999,
which is hundreds to thousands of times bigger than a realistic count. Even one
of these in a `mean()` makes a zone look like the busiest place in the city.
This looks like an overflow value or a placeholder the source system used for
missing data.

**4. Holiday flag drift.** `is_holiday` is set to 1 for every single day from
Jan 7 to Jan 21 (82,080 rows). Real holidays are single days. The model builds
a separate demand profile for holidays, so 14 ordinary days getting pulled into
it distorts both the holiday profile and the regular one. Looks like a calendar
or join bug that smeared the flag across a date range.

The check runs in about 2 seconds on the full 6.33M-row file, and the clean
baseline passes it with 0 issues, so it isn't just flagging everything.

## Validation schedule: every hour

I set the GitHub Actions workflow to run hourly (`cron: '0 * * * *'`). The feed
updates roughly every hour and the dashboard is used for real dispatch
decisions, so waiting a full day to catch bad data is too slow. The job is
cheap (a minute or two, well within the free tier), so running it hourly keeps
the worst case of bad data being live down to about an hour. I considered every
15 minutes but that's roughly 4x the runs for not much benefit given how often
the feed actually changes, and daily felt too slow. The workflow also runs on
push and can be triggered manually. If it finds critical or high severity
issues it exits with an error, which fails the build and blocks deployment.

## Graceful degradation

The API now loads data through `load_and_validate_data()` instead of calling
`pd.read_parquet()` directly. The idea is that it never crashes and never fixes
things silently. It validates the data, repairs what it can, and logs every fix
so an operator can see what happened. Here is what it does per issue:

- Duplicates: keep the first copy of each (zone, time_bucket).
- Negative and extreme trip counts: blank out the bad values and fill them with
  the median trip count for that zone and hour.
- Holiday drift: recompute `is_holiday` from the real calendar, but only inside
  the bad window so I don't wipe out correct holiday flags elsewhere.
- If the file can't be read at all, fall back to the last data that passed, and
  if there isn't one, fall back to the clean baseline. The zone lookup file
  also falls back to basic metadata instead of crashing.

After degradation the corrupted feed comes out as 6,320,160 rows (10,085
duplicates dropped, 642 bad trip counts replaced, 76,608 holiday flags fixed)
and re-validates with 0 issues. So the API keeps serving, but CI still fails
loudly so the real upstream problem gets noticed and fixed.

I verified all of this with 16 tests in `validation/test_data_quality.py`: the
baseline passes, the corrupted data fails, each of the four issues is detected
on its own, the degradation actually repairs the data, and the fallbacks don't
crash.
