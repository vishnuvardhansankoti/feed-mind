#!/usr/bin/env bash
# One-time setup for a named (non-default) Firestore database — the one the
# pipeline actually writes to (FIRESTORE_DATABASE, default "feed-mind-db").
#
# Firestore has no "create collection" step: the runs/run_status collections
# materialize on first write. What carries the default database's "properties"
# is the database itself, its TTL policies, and the composite index the UI needs
# — this script replicates those onto FIRESTORE_DATABASE. Idempotent; safe to
# re-run.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

echo "==> Firestore database '${FIRESTORE_DATABASE}' (native mode)"
gcloud firestore databases create \
  --database="$FIRESTORE_DATABASE" \
  --location="$REGION" --type=firestore-native --project "$PROJECT_ID" \
  2>/dev/null || echo "    database '${FIRESTORE_DATABASE}' already exists — skipping"

echo "==> Firestore TTL on '${FIRESTORE_DATABASE}' (auto-delete records past expire_at)"
# The pipeline writes expire_at = run_date + RETENTION_DAYS on every doc; these
# policies let Firestore sweep expired docs. Idempotent (re-enabling is a no-op).
for cg in runs run_status; do
  gcloud firestore fields ttls update expire_at \
    --collection-group="$cg" --enable-ttl \
    --database="$FIRESTORE_DATABASE" \
    --project "$PROJECT_ID" --quiet
done

echo "==> Composite index on '${FIRESTORE_DATABASE}' (runs: category ASC, run_date DESC)"
# The Latest/Archive queries need this composite index (mirrors
# firestore.indexes.json / infra/main.tf). `indexes composite create` errors if
# an identical index already exists, so treat that as success.
gcloud firestore indexes composite create \
  --collection-group=runs --query-scope=COLLECTION \
  --field-config=field-path=category,order=ascending \
  --field-config=field-path=run_date,order=descending \
  --database="$FIRESTORE_DATABASE" --project "$PROJECT_ID" \
  2>/dev/null || echo "    index already exists (or is building) — skipping"

echo "Firestore database '${FIRESTORE_DATABASE}' setup complete."
