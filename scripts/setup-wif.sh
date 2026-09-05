#!/usr/bin/env bash
# setup-wif.sh — One-time setup for GitHub Actions Workload Identity Federation
#
# Run this ONCE from your local machine before pushing to GitHub.
# After running, copy the printed values into GitHub Secrets.
#
# Usage:
#   chmod +x setup-wif.sh
#   ./setup-wif.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Project owner or IAM admin permissions

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — update before running
# ---------------------------------------------------------------------------
PROJECT_ID="feed-mind"         # TODO: replace
GITHUB_ORG="vishnuvardhansankoti"        # TODO: replace (username or org name)
GITHUB_REPO="feed-mind"                  # TODO: replace if repo name differs

# ---------------------------------------------------------------------------
# Derived values (no need to change)
# ---------------------------------------------------------------------------
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
POOL_ID="github-actions-pool"
PROVIDER_ID="github-provider"
SA_NAME="feedmind-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Project: ${PROJECT_ID} (${PROJECT_NUMBER})"
echo "==> GitHub:  ${GITHUB_ORG}/${GITHUB_REPO}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Enable IAM Credentials API (required for WIF)
# ---------------------------------------------------------------------------
echo "==> Enabling required APIs..."
gcloud services enable iamcredentials.googleapis.com --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# Step 2: Create the Workload Identity Pool
# ---------------------------------------------------------------------------
echo "==> Creating Workload Identity Pool: ${POOL_ID}..."
gcloud iam workload-identity-pools create "${POOL_ID}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  2>/dev/null || echo "  (pool already exists — skipping)"

POOL_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"

# ---------------------------------------------------------------------------
# Step 3: Create the GitHub OIDC Provider in the pool
# ---------------------------------------------------------------------------
echo "==> Creating Workload Identity Provider: ${PROVIDER_ID}..."
gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL_ID}" \
  --display-name="GitHub OIDC Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository_owner=='${GITHUB_ORG}'" \
  2>/dev/null || echo "  (provider already exists — skipping)"

PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

# ---------------------------------------------------------------------------
# Step 4: Create the service account (if not already done by deploy.sh)
# ---------------------------------------------------------------------------
echo "==> Ensuring service account exists: ${SA_EMAIL}..."
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="FeedMind Service Account" \
  --project="${PROJECT_ID}" \
  2>/dev/null || echo "  (already exists — skipping)"

# ---------------------------------------------------------------------------
# Step 5: Grant the SA minimum IAM roles
# ---------------------------------------------------------------------------
echo "==> Granting IAM roles to service account..."

for ROLE in \
  "roles/datastore.user" \
  "roles/secretmanager.secretAccessor" \
  "roles/logging.logWriter" \
  "roles/cloudfunctions.developer" \
  "roles/iam.serviceAccountUser" \
  "roles/run.admin"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --quiet
  echo "  Granted: ${ROLE}"
done

# ---------------------------------------------------------------------------
# Step 6: Allow GitHub Actions to impersonate the service account
# ---------------------------------------------------------------------------
echo "==> Binding GitHub Actions identity to service account..."
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_NAME}/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}"

# ---------------------------------------------------------------------------
# Step 7: Print GitHub Secrets to add
# ---------------------------------------------------------------------------
echo ""
echo "=================================================================="
echo "✅ WIF setup complete! Add these as GitHub repository secrets:"
echo "   (GitHub repo → Settings → Secrets and variables → Actions → New)"
echo "=================================================================="
echo ""
echo "  Secret Name              | Value"
echo "  -------------------------|-----------------------------------------------"
echo "  WIF_PROVIDER             | ${PROVIDER_RESOURCE}"
echo "  WIF_SERVICE_ACCOUNT      | ${SA_EMAIL}"
echo "  GCP_PROJECT_ID           | ${PROJECT_ID}"
echo "  GCP_REGION               | us-central1"
echo "  FUNCTION_SERVICE_ACCOUNT | ${SA_EMAIL}"
echo ""
echo "After adding secrets, push to main to trigger your first deployment."
