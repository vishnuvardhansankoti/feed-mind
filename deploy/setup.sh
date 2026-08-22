#!/usr/bin/env bash
# One-time project setup: APIs, service accounts, IAM.
#
# Run this once per project, before the first ./deploy/deploy.sh. It is
# idempotent - every step either creates something or reports that it already
# exists - so re-running it after changing deploy/config.sh is safe.
#
#     ./deploy/setup.sh
#
# What it does NOT do: create the Firestore database, the storage bucket, or the
# LLM API key secret. Those belong to FeedMind proper or hold data this script
# has no business inventing. It checks for them and tells you what is missing.

source "$(dirname "$0")/config.sh"
require_gcloud

say "Project ${PROJECT_ID}, region ${REGION}"

# ---------------------------------------------------------------------------
say "Enabling APIs"
# cloudbuild/artifactregistry are how a gen2 function gets built and stored;
# run is what it is actually served on.
gcloud services enable \
    cloudfunctions.googleapis.com \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    eventarc.googleapis.com \
    cloudscheduler.googleapis.com \
    texttospeech.googleapis.com \
    firestore.googleapis.com \
    storage.googleapis.com \
    secretmanager.googleapis.com \
    --project="$PROJECT_ID"

# ---------------------------------------------------------------------------
create_service_account() {
    local id="$1" description="$2"
    if gcloud iam service-accounts describe "${id}@${PROJECT_ID}.iam.gserviceaccount.com" \
        --project="$PROJECT_ID" >/dev/null 2>&1; then
        echo "  service account ${id} already exists"
    else
        gcloud iam service-accounts create "$id" \
            --project="$PROJECT_ID" \
            --display-name="$description"
    fi
}

say "Creating service accounts"
create_service_account "$SERVICE_ACCOUNT_ID" "FeedMind audio function runtime"
create_service_account "$SCHEDULER_SA_ID" "FeedMind audio function invoker"

# ---------------------------------------------------------------------------
say "Granting IAM roles to ${SERVICE_ACCOUNT}"

# Firestore read and write. datastore.user is the narrowest predefined role that
# covers both; there is no per-collection predefined role.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/datastore.user" \
    --condition=None \
    --quiet >/dev/null

# Writing objects into the audio bucket. Scoped to the one bucket rather than
# granted project-wide, because the function has no reason to touch any other.
if gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/storage.objectAdmin" \
        --quiet >/dev/null
    echo "  granted objectAdmin on gs://${BUCKET_NAME}"
else
    echo "  WARNING: gs://${BUCKET_NAME} does not exist." >&2
    echo "  Create it, and make its objects publicly readable - feedmind_audio.py" >&2
    echo "  writes https://storage.googleapis.com/<bucket>/<blob> URLs into" >&2
    echo "  Firestore, which only resolve for anonymous readers:" >&2
    echo "    gcloud storage buckets create gs://${BUCKET_NAME} --location=${REGION}" >&2
    echo "    gcloud storage buckets add-iam-policy-binding gs://${BUCKET_NAME} \\" >&2
    echo "        --member=allUsers --role=roles/storage.objectViewer" >&2
fi

# Reading the LLM API key at runtime.
if gcloud secrets describe "$LLM_API_KEY_SECRET" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets add-iam-policy-binding "$LLM_API_KEY_SECRET" \
        --project="$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/secretmanager.secretAccessor" \
        --quiet >/dev/null
    echo "  granted secretAccessor on ${LLM_API_KEY_SECRET}"
else
    echo "  WARNING: secret ${LLM_API_KEY_SECRET} does not exist. Create it with:" >&2
    echo "    printf '%s' \"\$YOUR_KEY\" | gcloud secrets create ${LLM_API_KEY_SECRET} \\" >&2
    echo "        --project=${PROJECT_ID} --data-file=-" >&2
    echo "  then re-run this script." >&2
fi

# Nothing extra is needed for Text-to-Speech: it authorizes on the caller's
# credentials and the enabled API, with no per-identity role to grant.

# The scheduler account only needs to be allowed to invoke. That binding is made
# in deploy.sh, because it targets the deployed Cloud Run service by name and so
# cannot be made before the function exists.

say "Setup complete"
echo "Next: ./deploy/deploy.sh"
