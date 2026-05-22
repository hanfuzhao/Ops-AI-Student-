# Week 3 Report: Data Quality Validation

I added automated data quality checks to the NYC cab demand API from Week 2.
The new upstream file (`demand_enriched_corrupted.parquet`, about 6.33M rows)
has problems in it, so I compared it against the clean baseline
(`demand_enriched_baseline.parquet`, 1,440 rows from zone 4, Jan 1-15) to find
what was wrong.

## Issues I found

| Issue | Rows | What is wrong and why it matters | Likely cause |
|-------|------|----------------------------------|--------------|
| Duplicate rows | 10,085 | The same (zone, time_bucket) row appears twice, in 5 zones over Feb 7-28. The demand profile is built with a groupby, so duplicates get counted twice and inflate the heatmap, the KPIs, and the unmet-demand numbers. | A batch ingested twice |
| Negative trip counts | 353 | `trip_count` of -1 or -5, starting Jan 16. A count cannot be negative. It drags zone averages down and feeds bad values into the model's lag features. | Sign error upstream |
| Extreme values | 311 | `trip_count` of 9999 or 99999, hundreds to thousands of times too big. Even one in a `mean()` makes a zone look like the busiest in the city. | Overflow or a missing-data placeholder |
| Holiday flag drift | 82,080 | `is_holiday` is 1 for every day from Jan 7 to Jan 21. Real holidays are single days, so 14 ordinary days get pulled into the separate holiday demand profile and distort it. | A calendar or join bug |

The check runs in about 2 seconds on the full file, and the clean baseline
passes it with 0 issues, so it is not just flagging everything.

## Validation schedule: every hour

I set the GitHub Actions workflow to run hourly (`cron: '0 * * * *'`). The feed
updates roughly every hour and the dashboard is used for real dispatch
decisions, so waiting a full day to catch bad data is too slow. The job only
takes a minute or two, so running it hourly keeps the worst case of bad data
being live down to about an hour. Every 15 minutes would be about 4x the runs
for not much benefit given how often the feed actually changes, and daily felt
too slow. The workflow also runs on push and can be triggered manually, and it
exits with an error on critical or high severity issues, which fails the build
and blocks deployment.

## Graceful degradation

The API loads data through `load_and_validate_data()` instead of calling
`pd.read_parquet()` directly. It never crashes and never fixes things silently:
it validates the data, repairs what it can, and logs every fix. Per issue:

- Duplicates: keep the first copy of each (zone, time_bucket).
- Negative and extreme counts: blank out the bad values and fill them with the
  median trip count for that zone and hour.
- Holiday drift: recompute `is_holiday` from the real calendar, but only inside
  the bad window so correct holiday flags elsewhere are left alone.
- If the file cannot be read at all, fall back to the last data that passed,
  and if there is none, fall back to the clean baseline. The zone lookup file
  also falls back to basic metadata instead of crashing.

After degradation the corrupted feed comes out as 6,320,160 rows (10,085
duplicates dropped, 642 bad counts replaced, 76,608 holiday flags fixed) and
re-validates with 0 issues. So the API keeps serving, but CI still fails loudly
so the real upstream problem gets fixed. All of this is verified by 16 tests in
`validation/test_data_quality.py`.
