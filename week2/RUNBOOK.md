# RUNBOOK — Week 2 Deployment

End-to-end commands to bring up the `demand-api` service on GKE, wire CI/CD,
and tear it down. Project ID is `ops-ai-hanfuzhao` and the GCS bucket is
`gs://ops-ai-hanfuzhao-data`. Run from the repo root.

## Prereqs

- `gcloud`, `kubectl` on PATH
- `gcloud auth login` already done
- A billing account in **OPEN** state (`gcloud billing accounts list`)

## 1. Project and billing

```bash
# Create the project
gcloud projects create ops-ai-hanfuzhao --set-as-default

# Link billing FIRST (must be done before enabling paid APIs).
# Replace BILLING_ACCOUNT_ID with the OPEN account from `gcloud billing accounts list`
gcloud beta billing projects link ops-ai-hanfuzhao \
  --billing-account=BILLING_ACCOUNT_ID
```

## 2. Enable APIs

```bash
gcloud services enable \
  container.googleapis.com \
  artifactregistry.googleapis.com \
  compute.googleapis.com \
  storage-api.googleapis.com \
  cloudbuild.googleapis.com \
  --project=ops-ai-hanfuzhao
```

`cloudbuild` is the addition over the assignment's list — we build the
initial image with Cloud Build instead of a local Docker daemon.

## 3. GCS bucket and uploads

```bash
gsutil mb -p ops-ai-hanfuzhao gs://ops-ai-hanfuzhao-data

gsutil cp week2/data/demand_enriched.parquet              gs://ops-ai-hanfuzhao-data/
gsutil cp week2/model/demand_api_model.joblib             gs://ops-ai-hanfuzhao-data/
gsutil cp week2/backend/zone_hour_avg_fare.parquet        gs://ops-ai-hanfuzhao-data/
gsutil cp week2/backend/taxi_zones.geojson                gs://ops-ai-hanfuzhao-data/

gsutil ls -lh gs://ops-ai-hanfuzhao-data/
```

## 4. Artifact Registry

```bash
gcloud artifacts repositories create docker-repo \
  --repository-format=docker \
  --location=us-central1 \
  --project=ops-ai-hanfuzhao
```

## 5. Service account and key

```bash
gcloud iam service-accounts create github-actions \
  --project=ops-ai-hanfuzhao

SA=github-actions@ops-ai-hanfuzhao.iam.gserviceaccount.com

for ROLE in \
  roles/container.developer \
  roles/artifactregistry.writer \
  roles/artifactregistry.reader \
  roles/storage.objectViewer \
  roles/cloudbuild.builds.editor; do
  gcloud projects add-iam-policy-binding ops-ai-hanfuzhao \
    --member="serviceAccount:$SA" --role="$ROLE" --condition=None --quiet
done

# Also grant the GKE node's default Compute Engine SA read access to the
# bucket so the init container's gsutil cp works without making the bucket
# public.
PROJECT_NUMBER=$(gcloud projects describe ops-ai-hanfuzhao --format='value(projectNumber)')
COMPUTE_SA=${PROJECT_NUMBER}-compute@developer.gserviceaccount.com
gcloud projects add-iam-policy-binding ops-ai-hanfuzhao \
  --member="serviceAccount:$COMPUTE_SA" \
  --role=roles/storage.objectViewer --condition=None --quiet

gcloud iam service-accounts keys create key.json \
  --iam-account="$SA"
# key.json is already in .gitignore. Do not commit it.
```

## 6. Build and push the first image (no local Docker)

```bash
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/ops-ai-hanfuzhao/docker-repo/demand-api:latest \
  --project=ops-ai-hanfuzhao \
  --config=/dev/stdin <<'YAML'
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'week2/starter/Dockerfile', '-t',
           'us-central1-docker.pkg.dev/ops-ai-hanfuzhao/docker-repo/demand-api:latest', '.']
  - name: gcr.io/cloud-builders/docker
    args: ['push',
           'us-central1-docker.pkg.dev/ops-ai-hanfuzhao/docker-repo/demand-api:latest']
images:
  - 'us-central1-docker.pkg.dev/ops-ai-hanfuzhao/docker-repo/demand-api:latest'
options:
  logging: CLOUD_LOGGING_ONLY
YAML
```

(Equivalent to `docker build && docker push`, run by Cloud Build.)

## 7. GKE cluster

```bash
gcloud container clusters create operationalizing-ai \
  --zone=us-central1-a \
  --num-nodes=2 \
  --machine-type=n1-standard-2 \
  --enable-autoscaling --min-nodes=2 --max-nodes=5 \
  --project=ops-ai-hanfuzhao

gcloud container clusters get-credentials operationalizing-ai \
  --zone=us-central1-a --project=ops-ai-hanfuzhao

kubectl get nodes
```

## 8. Image-pull secret and apply manifests

```bash
gcloud iam service-accounts keys create /tmp/gke-key.json \
  --iam-account=github-actions@ops-ai-hanfuzhao.iam.gserviceaccount.com

kubectl create secret docker-registry artifact-registry-secret \
  --docker-server=us-central1-docker.pkg.dev \
  --docker-username=_json_key \
  --docker-password="$(cat /tmp/gke-key.json)" \
  --docker-email=github-actions@ops-ai-hanfuzhao.iam.gserviceaccount.com
rm /tmp/gke-key.json

kubectl apply -f week2/starter/k8s/configmap.yaml
kubectl apply -f week2/starter/k8s/deployment.yaml
kubectl apply -f week2/starter/k8s/service.yaml

kubectl rollout status deployment/demand-api --timeout=5m
```

## 9. Test the API

```bash
kubectl get svc demand-api -w   # wait for EXTERNAL-IP, then Ctrl+C

IP=$(kubectl get svc demand-api -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

curl http://$IP/health
curl "http://$IP/api/heatmap?hour=17&dow=4&date=2026-01-15&holiday=regular"
curl "http://$IP/api/forecast?zone_id=68&hour=17&dow=4&steps=16&date=2026-01-15"
curl "http://$IP/api/recommendations?zone_id=68&hour=17&dow=4&date=2026-01-15&n=3&holiday=regular"
```

## 10. Wire CI/CD

```bash
# Paste the contents of key.json as the GCP_SA_KEY secret in GitHub
gh secret set GCP_SA_KEY < key.json --repo hanfuzhao/Ops-AI-Student

# Trigger CD by pushing
git commit --allow-empty -m "Trigger CD"
git push
# Watch: gh run watch --repo hanfuzhao/Ops-AI-Student
```

## 11. Concurrency smoke test (the "10+ concurrent" requirement)

```bash
# 20 parallel /health probes
seq 20 | xargs -P 20 -I _ curl -s -o /dev/null -w "%{http_code}\n" http://$IP/health \
  | sort | uniq -c
# Expect: 20 lines of "200"
```

## 12. Cleanup (do after submission)

```bash
gcloud container clusters delete operationalizing-ai \
  --zone=us-central1-a --project=ops-ai-hanfuzhao --quiet

gcloud artifacts repositories delete docker-repo \
  --location=us-central1 --project=ops-ai-hanfuzhao --quiet

# Keep the GCS bucket — Week 3 reuses it.
gsutil ls gs://ops-ai-hanfuzhao-data/
```

Take a screenshot of the empty cluster list (`gcloud container clusters list
--project=ops-ai-hanfuzhao`) for the submission.
