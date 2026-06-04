# Week 4: Monitoring, Drift Detection, and Retraining Strategy

June 3, 2026

## Overview

The February data shows that the demand model trained on January is no longer seeing the conditions it learned. Average trips per 15-minute interval fell from 14.07 to 12.56, about an 11% drop, and the change is concentrated rather than uniform: a handful of zones lost a fifth to nearly half of their volume while the rest held steady. The Kolmogorov-Smirnov test puts the chance this is sampling noise below 0.001, so it is worth acting on.

In total I found seven separate drift signals: two that show up as shifts in the input distribution (overall trip volume and the day-of-week mix) and five that are zone-specific demand collapses. The recommendation at the end is to retrain on February data, but only after validating the new model against held-out ground truth and rolling it out gradually.

## Baseline and what changed

January 1-15 is the reference period the current model was trained on. It is clean: no missing values, no duplicate rows, all 57 pickup zones present across 82,080 rows (15 days, 57 zones, 96 quarter-hour buckets a day).

| | Baseline (Jan 1-15) | New (Feb 2-28) |
|---|---|---|
| Rows | 82,080 | 147,744 |
| Mean trips / 15 min | 14.07 | 12.56 |
| Std dev | 19.24 | 17.35 |
| Null rate | 0% | 0% |
| Duplicate rate | 0% | 0% |

The thing that stands out is that February has 80% more rows but a lower average. More data and less demand at the same time rules out a sampling artifact and points to a real change in rider behavior.

Data quality itself is fine in both periods. Nothing is missing or duplicated, so whatever is happening is in the signal, not the pipeline.

## The drift patterns

### Trip volume shifted down

The whole trip_count distribution moved left, not just the mean. The tails came in noticeably:

| | Baseline | February |
|---|---|---|
| Mean | 14.07 | 12.56 |
| Std dev | 19.24 | 17.35 |
| 95th pct | 53 | 44 |
| 99th pct | 91 | 78 |

KS comes back at p < 0.001. The practical consequence is that the busy intervals the model expects show up less often, so its high-end predictions will tend to run hot. Cause is unknown from the data alone; weather, a fare or policy change, or a seasonal dip are all plausible.

### Day-of-week mix moved too

Running KS on dayofweek also returns p < 0.001. Comparing daily averages, Mondays took the biggest hit and the weekend softened less:

| Day | Baseline | February | Change |
|---|---|---|---|
| Monday | 13.2 | 11.1 | -15.9% |
| Friday | 15.4 | 13.8 | -10.4% |
| Saturday | 13.8 | 12.1 | -12.3% |
| Sunday | 13.2 | 12.4 | -6.1% |

A model that assumes January's weekday/weekend balance will be off on the days that moved most.

### Five zones drove most of the loss

The global drop is not spread evenly. Five zones account for most of it:

| Zone | Baseline | February | Change |
|---|---|---|---|
| 195 | 0.12 | 0.06 | -48.1% |
| 88 | 2.08 | 1.52 | -26.9% |
| 209 | 1.09 | 0.80 | -26.9% |
| 230 | 29.26 | 22.89 | -21.8% |
| 45 | 1.14 | 0.90 | -21.1% |

Zone 195's drop is the largest in percentage terms but it is a tiny zone, so the absolute effect is small. Zone 230 is the one that matters: it is the highest-volume zone in the system, and losing six or seven trips per interval there explains a large share of the overall 1.5-trip decline by itself. The other 52 zones are close to their January numbers. This is the kind of thing a single global accuracy number would hide, which is why the monitoring below tracks zones separately.

## Monitoring metrics

Eight metrics, grouped by what they protect against. Not all of them need the same cadence, and a couple are far more urgent than the rest, so the thresholds and frequencies differ.

**Catching distribution drift early.** The KS test and PSI both compare a recent 7-day window against the January baseline on trip_count. KS flags a shift when its p-value drops below 0.05; PSI flags one above 0.25 (below 0.10 is noise, in between is worth watching). I run both daily at 8am, before the accuracy numbers come in. KS is the more sensitive of the two and is what caught the drift here; PSI is the easier one to put in front of a non-technical stakeholder because it is a single number. When both fire at once I treat the drift as confirmed. Worth noting: in this dataset PSI came in at only 0.0057 even though KS was decisive, which is a good reminder that a small PSI does not clear you if the test designed to catch shape changes is screaming.

**Watching model performance.** Overall accuracy is the headline metric, but on its own it is misleading, so the real workhorse is per-zone accuracy across all 57 zones. Baseline accuracy runs around 91% overall and 85-95% per zone; I alert when any zone falls under 80%. Both are checked once a day at 9am, after the previous day's ground truth has landed. High-volume zones like 230 get watched more closely, and the very low-volume zones can use a looser threshold since their accuracy is naturally noisier.

**Data quality.** Null rate and duplicate rate are cheap and should always read zero, so any movement is suspicious. I check them every four hours. Null rate above 1% in a key field, or duplicates above 0.5%, usually means the pipeline broke or double-wrote, and the right response is to page the data engineer rather than wait for the next daily cycle.

**Infrastructure and model health.** Data freshness checks how old the newest record is; past four hours, the feed has probably stalled, and since we cannot retrain on data we do not have, that is checked hourly. The last metric watches the spread of the model's own predictions: if the standard deviation collapses toward zero the model has degenerated into predicting one number for everything, which throws no errors and is otherwise invisible. That one runs every six hours.

| Metric | Baseline | Alert | Cadence |
|---|---|---|---|
| Accuracy (per zone) | 85-95% | < 80% | daily |
| KS test | p > 0.05 | p < 0.05 | daily |
| PSI | < 0.10 | > 0.25 | daily |
| Null rate | 0% | > 1% | 4h |
| Duplicate rate | 0% | > 0.5% | 4h |
| Data freshness | < 2h | > 4h | hourly |
| Prediction spread | std 5-6 | std < 0.1 | 6h |

## Retraining strategy

### When to retrain

I use three triggers rather than one, because the signals arrive at different speeds. The proactive trigger fires on drift alone (KS p < 0.01 or PSI > 0.25) and aims to retrain within a couple of hours, before accuracy has even degraded. The reactive trigger fires on measured performance (any zone under 80%, or global under 82%) and is the safety net for drift the statistical tests miss. On top of both there is a standing weekly retrain every Monday at 2am, which keeps the model current even in quiet periods.

For the February data all three would have fired, so the call is clear: retrain now.

### Pipeline

The retrain runs as a sequence with a hard stop in the middle:

1. **Prepare** the February 2-28 data (147,744 rows), rebuild the lag and rolling-average features, and confirm it is clean before training. About 30 minutes.
2. **Train** with the same algorithm and hyperparameters as the deployed model. Changing the data and the model at once makes a regression impossible to diagnose, so this step deliberately holds everything but the data fixed. About 45 minutes.
3. **Validate offline** against held-out ground truth from Jan 16 to Feb 1. The new model has to be within 2 points of the old one globally, and no single zone is allowed to fall more than 10 points below its baseline. If it fails either test, stop here and keep the current model. This is the gate that prevents shipping a worse model.
4. **Canary** at 1% of traffic for six hours, watching accuracy, latency, and error rate. Anything off and it rolls straight back.
5. **Ramp** over the next day: 5%, then 25%, 50%, 100%, with the same auto-rollback at each step.
6. **Keep watching** with the daily metrics above once it is fully live.

End to end that is roughly two days, most of it the canary and ramp.

### Versioning and rollback

Every model is saved with its training date, sample count, validation accuracy, and per-zone breakdown, named so the lineage is obvious (for example `model_v2026-02-28`). The January baseline is kept indefinitely; the last three versions are kept for rollback and anything older is pruned after 30 days. Rollback is automatic if accuracy drops more than 5% after a deploy, and a person can revert manually within the first week if something subtler shows up.

## The monitoring workflow and why daily

The GitHub Actions workflow in `week4/.github/workflows/monitor-drift.yml` runs `compute_metrics.py` and then `detect_drift.py` on a schedule, and opens an issue if either crosses a threshold. I set the schedule to once a day at 9am UTC.

Daily is the right granularity for this problem. Demand forecasting can tolerate a 24-hour detection lag, since one day of slightly-off predictions is not a catastrophe, and a daily job costs almost nothing. Hourly would catch drift a few hours sooner but multiply the cost and the noise for a signal that does not move that fast, and weekly would let nearly a week of drift accumulate before anyone looked. The faster checks (data quality, freshness) still run more often inside the framework, but the core drift-and-accuracy pass is daily.

## Recommendations

The immediate action is to retrain on the February data through the pipeline above and to look into the five zones by hand, starting with 230 because of its volume and 195 because of the size of its drop. A 20-plus percent fall in a single zone usually has a concrete cause such as a closure, construction, or a competing service, and that is worth knowing before assuming the model is simply stale.

Beyond the immediate fix, the monitoring is currently global-first; the next improvement is per-zone alerting so a localized collapse like Zone 230's is caught on its own rather than diluted into the average. Further out, a shadow-mode deployment (run the new model alongside the old without serving it, and compare against ground truth for a week or two) would give more confidence than the offline test alone before a full rollout.

## Implementation notes

The code is in `week4/scripts/`: `metric_template.py` holds the eight metric implementations in a `MetricComputer` class, `compute_metrics.py` loads the data and checks every metric against its threshold, `detect_drift.py` runs the statistical tests and writes out the pattern report, and `test_monitoring.py` covers the lot. Running `compute_metrics.py` on the February window flags three alerts (the trip_count and dayofweek shifts, plus a stale-data flag from the fixed dataset) and writes its results to a timestamped JSON file.

Two methods underpin the drift detection. KS (`scipy.stats.ks_2samp`) is a non-parametric test of whether two samples come from the same distribution; we reject that they do when p < 0.05, and apply it to trip_count, hour, and dayofweek. PSI bins both distributions and sums the weighted log-ratio of the bin proportions, giving the single 0.0057 figure quoted above. The zone-level patterns come from comparing per-zone means directly rather than from a test.
