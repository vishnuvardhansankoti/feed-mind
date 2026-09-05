"""Web Push notifications, sent once a batch of audio summaries is finished.

Why here and not in the pipelines: both feed-mind and paper-prism publish a
`feedmind-content-ready` event when their documents land, but that is *before*
this script has generated `ai_summary` and `audio_url`. Notifying then sends the
reader into an app with nothing to listen to. This script is the last step for
both sources, and it already knows how many items it produced — so the
notification goes out from here.

Subscriptions live on `users/{uid}.push_subscriptions` in Firestore, written by
the web app. That is the only document a browser may write, and it is gated by
the allowlist in paper-prism's firestore.rules, which is why notifications are
signed-in only.

Best-effort, like the rest of the pipeline: the audio is already uploaded and
recorded by the time this runs, so a failure to notify must never fail the
batch or invite a retry of the whole thing.
"""

from __future__ import annotations

import json
import os

USERS_COLLECTION = "users"
SUBSCRIPTIONS_FIELD = "push_subscriptions"

# The private half of the VAPID pair whose public half is baked into the web
# bundle as VITE_VAPID_PUBLIC_KEY. Set from Secret Manager in the deployed
# function; absent locally, which disables sending.
VAPID_PRIVATE_KEY_ENV = "VAPID_PRIVATE_KEY"
# Contact address required by the push services, as a mailto: or https: URI.
VAPID_SUBJECT_ENV = "VAPID_SUBJECT"
DEFAULT_SUBJECT = "mailto:shankotai@gmail.com"

RSS_FEED = "RSS_FEED"
RESEARCH_PAPERS = "RESEARCH_PAPERS"

# Endpoints the push service has permanently rejected. Anything else (a 500, a
# timeout) is transient and the subscription is kept.
DEAD_ENDPOINT_STATUSES = (404, 410)


def _message(process_doc, count):
    """Title, body, deep link and collapse tag for one finished run."""
    if process_doc == RESEARCH_PAPERS:
        noun = "paper" if count == 1 else "papers"
        return {
            "title": "This week's research digest",
            "body": f"{count} new {noun}, summarized and ready to listen.",
            "url": "/#/papers",
            # One tag per source, so a re-run replaces its own notification
            # rather than stacking a second one for the same batch.
            "tag": "feedmind-papers",
        }
    noun = "story" if count == 1 else "stories"
    return {
        "title": "Today's tech news",
        "body": f"{count} new {noun}, summarized and ready to listen.",
        "url": "/",
        "tag": "feedmind-news",
    }


def _subscribers(db):
    """Every stored subscription, as (user_ref, subscription dict) pairs."""
    out = []
    for snapshot in db.collection(USERS_COLLECTION).stream():
        subs = (snapshot.to_dict() or {}).get(SUBSCRIPTIONS_FIELD) or []
        if not isinstance(subs, list):
            continue
        for sub in subs:
            if isinstance(sub, dict) and sub.get("endpoint"):
                out.append((snapshot.reference, sub))
    return out


def _drop(reference, endpoint):
    """Remove one dead endpoint, leaving the rest of the user's document alone."""
    try:
        snapshot = reference.get()
        subs = (snapshot.to_dict() or {}).get(SUBSCRIPTIONS_FIELD) or []
        kept = [s for s in subs if s.get("endpoint") != endpoint]
        if len(kept) != len(subs):
            reference.update({SUBSCRIPTIONS_FIELD: kept})
    except Exception:  # noqa: BLE001 - pruning is opportunistic
        pass


def notify(db, process_doc, count, log, dry_run=False):
    """Push one notification per subscribed device. Never raises.

    Returns the number of successful sends, which is 0 whenever notifications
    are switched off, unconfigured, or there is nothing to announce.
    """
    if count <= 0:
        log("  notifications: nothing produced, not sending")
        return 0

    private_key = os.environ.get(VAPID_PRIVATE_KEY_ENV, "").strip()
    if not private_key:
        log(f"  notifications: {VAPID_PRIVATE_KEY_ENV} unset - not sending")
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        log("  notifications: pywebpush not installed - not sending")
        return 0

    try:
        targets = _subscribers(db)
    except Exception as error:  # noqa: BLE001 - the batch already succeeded
        log(f"  notifications: could not read subscriptions ({error})")
        return 0

    if not targets:
        log("  notifications: nobody subscribed")
        return 0

    payload = json.dumps(_message(process_doc, count))
    claims = {"sub": os.environ.get(VAPID_SUBJECT_ENV) or DEFAULT_SUBJECT}

    if dry_run:
        log(f"  notifications: dry run - would notify {len(targets)} device(s)")
        return 0

    sent = 0
    for reference, sub in targets:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub.get("p256dh", ""), "auth": sub.get("auth", "")},
                },
                data=payload,
                vapid_private_key=private_key,
                # A fresh dict per send: pywebpush mutates claims to add `aud`
                # and `exp`, and a reused dict carries the first endpoint's
                # audience to every later one, which they then reject.
                vapid_claims=dict(claims),
            )
            sent += 1
        except WebPushException as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status in DEAD_ENDPOINT_STATUSES:
                _drop(reference, sub["endpoint"])
                log(f"  notifications: dropped a dead endpoint ({status})")
            else:
                log(f"  notifications: send failed ({status or error})")
        except Exception as error:  # noqa: BLE001 - never fail the batch
            log(f"  notifications: send failed ({error})")

    log(f"  notifications: sent to {sent}/{len(targets)} device(s)")
    return sent
