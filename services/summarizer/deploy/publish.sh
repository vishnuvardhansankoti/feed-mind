#!/usr/bin/env bash
# Publish a trigger message by hand - the manual equivalent of what FeedMind
# does at the end of its run.
#
#     ./deploy/publish.sh                                  # latest RSS batch
#     ./deploy/publish.sh RESEARCH_PAPERS                  # latest papers
#     ./deploy/publish.sh RESEARCH_PAPERS --category CV
#     ./deploy/publish.sh RSS_FEED --limit 1 --dry-run     # no uploads, no writes
#
# Any flag feedmind_audio.py accepts can be passed through; it is turned into
# the JSON field main.py expects (--dry-run -> "dry_run": true).
#
# This publishes to the real topic, so anything without --dry-run does real
# work: real synthesis, real uploads, real Firestore writes.

source "$(dirname "$0")/config.sh"
require_gcloud

MODE="RSS_FEED"
if [[ $# -gt 0 && "$1" != --* ]]; then
    MODE="$1"
    shift
fi

# Build the JSON body from the remaining flags. Values are emitted unquoted when
# they are numeric or boolean, so --limit 5 becomes 5 rather than "5"; main.py
# would coerce either, but the message reads better in the logs this way.
fields="\"process_doc\": \"${MODE}\""

while [[ $# -gt 0 ]]; do
    flag="$1"
    [[ "$flag" == --* ]] || { echo "Expected a --flag, got: ${flag}" >&2; exit 1; }
    key="${flag#--}"
    key="${key//-/_}"

    if [[ $# -ge 2 && "$2" != --* ]]; then
        value="$2"
        shift 2
        if [[ "$value" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; then
            fields+=", \"${key}\": ${value}"
        else
            fields+=", \"${key}\": \"${value}\""
        fi
    else
        shift
        fields+=", \"${key}\": true"
    fi
done

MESSAGE="{${fields}}"

say "Publishing to ${TOPIC_NAME}"
echo "  ${MESSAGE}"

gcloud pubsub topics publish "$TOPIC_NAME" \
    --project="$PROJECT_ID" \
    --message="$MESSAGE"

echo
echo "Watch it run:"
echo "  gcloud functions logs read ${FUNCTION_NAME} --gen2 --region=${REGION} --limit=50"
