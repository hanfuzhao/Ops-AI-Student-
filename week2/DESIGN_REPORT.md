# Design Report — Week 2 Deployment

## What was deployed

A FastAPI server wrapping a pre-trained demand-forecasting model, on a
3-pod GKE Deployment in `us-central1-a` behind a LoadBalancer Service
(port 80 → 8000). Each pod pulls its model and data from a GCS bucket at
startup via an init container. Pushes to `main` trigger GitHub Actions,
which builds the image with Cloud Build, pushes it to Artifact Registry,
and rolling-updates the cluster. Measured on the actual run: pods
`1/1 Running` after about 2 minutes, LoadBalancer external IP in roughly
45 seconds, CD end-to-end in 4m59s, and 20 concurrent `/health` requests
all returning 200.

## Health checks, readiness vs. liveness

`/health` only returns `{"status":"ok"}`. It does not verify the model
is loaded. On its own that is the trap the readings warn about: a green
rollout sitting on top of a broken application. What partly covers it is
that `data.py` loads its parquet and joblib files at module import time,
so a missing or corrupt file crashes the process and the readiness probe
simply can't connect.

The two probes are deliberately asymmetric: readiness `15/10/3`, liveness
`45/20/3`. Readiness decides whether the LoadBalancer routes traffic and
should fail fast; liveness decides whether to restart the pod and should
be slow, because identical thresholds turn a transient blip into a
restart that delays startup and fails readiness again, which cascades.
The few-second model load fits inside the readiness window without ever
tripping liveness.

## Resources and rolling update

Requests are 512m CPU / 1Gi memory, limits 1000m / 3Gi. The demand
parquet (74MB on disk, larger once pandas decodes it) plus the
precomputed caches put a fresh pod near 1Gi, so the 1Gi request stops the
scheduler over-packing nodes and the 3Gi limit leaves headroom before
OOMKill. The sizing is intentionally conservative: with no production
traffic data, the cost of under-provisioning (throttling or eviction in
front of users) outweighs the wasted budget, and tightening it is a
measure-then-resize follow-up. The rollout uses `maxSurge: 1,
maxUnavailable: 1`, so at most four pods exist and at least two serve.
`maxUnavailable: 0` would be tighter but needs room for a full surge on
top of the old fleet, which does not scale; the chosen setting is the
right tradeoff at three replicas.

## Pipeline, rollback, trust

`ci.yml` runs tests on push and PR; `cd.yml` deploys only on `main`. The
`GCP_SA_KEY` secret is injected as `credentials_json` and never written
to logs. Every image is tagged with both `:latest` and the commit SHA,
and `kubectl set image` references the SHA, so deploys are reproducible
(same SHA, same bytes) and rollback is a one-line `kubectl set image`
(or `kubectl rollout undo`) against an older SHA with no rebuild. Known
gap: CI and CD run as independent workflows, so CD does not wait for CI
to pass; a `needs:` chain or a required status check would close this in
a team setting. The `github-actions` service account is scoped to
`container.developer`, `artifactregistry.*`, and `storage.objectViewer`.
That is enough to deploy but not enough to touch IAM or billing, so a
leaked key stays contained to the cluster and registry.

## A real silent-failure incident

The most instructive thing in the bring-up was a clean silent failure.
After the first rollout every signal was green: 3 pods `1/1 Running`,
readiness passing, LoadBalancer IP assigned, `kubectl rollout status`
reporting success. But `/api/forecast` returned `[]`, a clean 200 and
not an error. One line was buried in the pod startup log:

```
[NYC Cab Analytics] Error loading model: No module named 'sklearn'
```

The model pickle needs scikit-learn at unpickle time and
`requirements.txt` did not list it. `data.py` catches the import error,
sets `_lgbm_model = None`, and the forecast endpoint short-circuits to
`[]`. Adding sklearn then surfaced a deeper skew: the model was trained
on sklearn 1.8.0, and `predict()` raised `X has 30 features, but
RandomForestRegressor is expecting 20`, which is a model-vs-code
mismatch that is out of scope to fix here. The shipped mitigation is to
leave sklearn out, so the load fails cleanly and forecast returns the
documented `[]` instead of a 500. The point this report keeps coming
back to: a probe that actually ran a prediction would have failed the
rollout, instead of letting a broken endpoint look healthy.

## What I'd improve

A real `/health` that runs one prediction against a fixed feature vector
and only then returns 200; structured logs into Cloud Logging with a
request ID so LoadBalancer and pod logs can be joined; and an SLO
dashboard with an alert for the exact case here, where infrastructure
is green while application metrics quietly degrade.
