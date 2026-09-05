# GitHub Actions — CI/CD Setup Guide

This guide walks you through configuring the GitHub Actions deployment pipeline for FeedMind.
The pipeline uses **Workload Identity Federation (WIF)** — no long-lived service account JSON keys are stored anywhere.

---

## How the Pipeline Works

```
push to main
     │
     ▼
┌─────────┐    fails    ┌──────────────────────────────────────┐
│  Lint   │────────────►│  ✗ Block deploy, fix errors locally  │
│  (Ruff) │             └──────────────────────────────────────┘
└────┬────┘
     │ passes
     ▼
┌──────────────────────────────────┐
│  Authenticate (WIF — keyless)    │  No JSON keys anywhere
└────┬─────────────────────────────┘
     │
     ▼
┌──────────────────────────────────┐
│  Deploy Cloud Function Gen 2     │
└────┬─────────────────────────────┘
     │
     ▼
┌──────────────────────────────────┐
│  Update Cloud Scheduler URI      │
└──────────────────────────────────┘
```

**Trigger:** Any push to `main` that touches a `.py` file, `requirements.txt`, or the workflow file itself.  
**Manual trigger:** Available via the GitHub Actions UI (`workflow_dispatch`).

---

## Prerequisites

- [ ] GCP project created with billing enabled
- [ ] `gcloud` CLI installed and authenticated (`gcloud auth login`)
- [ ] `deploy.sh` has been run **at least once** to create the Cloud Function and Scheduler job
- [ ] Repository pushed to GitHub

---

## Setup Order

### Step 1 — Run `deploy.sh` (first-time only)

If you haven't deployed the function yet, do that first so Cloud Scheduler exists:

```bash
# Edit PROJECT_ID and SCHEDULER_TIMEZONE in deploy.sh first
./deploy.sh
```

---

### Step 2 — Configure Workload Identity Federation

Edit `setup-wif.sh` and fill in your values:

```bash
PROJECT_ID="your-gcp-project-id"    # your GCP project
GITHUB_ORG="your-github-username"   # your GitHub username or org name
GITHUB_REPO="feed-mind"             # your repository name
```

Then run it:

```bash
chmod +x setup-wif.sh
./setup-wif.sh
```

The script will:
1. Enable the IAM Credentials API
2. Create a Workload Identity Pool (`github-actions-pool`)
3. Create a GitHub OIDC Provider (`github-provider`)
4. Create the `feedmind-sa` service account (if not already done)
5. Grant the service account the minimum required IAM roles
6. Bind GitHub Actions to the service account
7. **Print the 5 values you need to add as GitHub Secrets**

---

### Step 3 — Add GitHub Secrets

Go to your repository on GitHub:  
**Settings → Secrets and variables → Actions → New repository secret**

Add each of the following (values are printed at the end of `setup-wif.sh`):

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `WIF_PROVIDER` | Full WIF provider resource name | `projects/123456/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider` |
| `WIF_SERVICE_ACCOUNT` | Service account email | `feedmind-sa@your-project.iam.gserviceaccount.com` |
| `GCP_PROJECT_ID` | Your GCP project ID | `your-gcp-project-id` |
| `GCP_REGION` | GCP region for the function | `us-central1` |
| `FUNCTION_SERVICE_ACCOUNT` | SA the function runs as (same as `WIF_SERVICE_ACCOUNT`) | `feedmind-sa@your-project.iam.gserviceaccount.com` |

> **Security note:** These values are not sensitive credentials — they are resource identifiers.
> The actual authentication is handled by GitHub's OIDC token exchange at runtime, scoped to your specific repository only.

---

### Step 4 — Push to Main

```bash
git add .
git commit -m "feat: add GitHub Actions CI/CD pipeline"
git push origin main
```

The workflow will fire automatically. Watch it at:  
`https://github.com/YOUR_ORG/feed-mind/actions`

---

## Why Workload Identity Federation (Not a JSON Key)?

| | JSON Key | Workload Identity Federation |
|---|---|---|
| **Key stored in GitHub** | ✗ Yes (long-lived, risky) | ✅ No |
| **Key rotation needed** | ✗ Manual | ✅ Automatic (short-lived tokens) |
| **Scope** | Any machine with the key | ✅ Locked to your specific GitHub repo |
| **Google's recommendation** | ✗ Deprecated for CI/CD | ✅ Recommended |

---

## Triggering a Manual Deployment

From the GitHub UI: **Actions → Deploy FeedMind to GCP → Run workflow → Run workflow**

Or trigger Cloud Scheduler directly to test the function:

```bash
gcloud scheduler jobs run feedmind-daily-trigger \
  --location=us-central1 \
  --project=your-gcp-project-id
```

---

## Checking Deployment Logs

**GitHub Actions logs:**  
`https://github.com/YOUR_ORG/feed-mind/actions`

**Cloud Logging (function execution logs):**

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND jsonPayload.message="FeedMind run complete"' \
  --limit=5 \
  --project=your-gcp-project-id \
  --format=json
```

---

## Troubleshooting

### `Permission denied` during deploy

Ensure the service account has `roles/cloudfunctions.developer` and `roles/run.admin`:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:feedmind-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudfunctions.developer"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:feedmind-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.admin"
```

### `Error: google-github-actions/auth failed`

- Confirm `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` secrets are set correctly
- Confirm `GITHUB_ORG` in `setup-wif.sh` exactly matches your GitHub username/org (case-sensitive)
- Re-run `setup-wif.sh` to verify the binding

### Lint fails locally before pushing

```bash
pip install ruff
ruff check .
ruff check --fix .   # auto-fix safe issues
```
