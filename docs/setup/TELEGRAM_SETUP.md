# Telegram Bot — Setup Guide

This guide walks you through creating a Telegram bot, finding your Chat ID, and wiring both into GCP Secret Manager for FeedMind.

---

## Step 1 — Create a Bot via BotFather

1. Open Telegram and search for **[@BotFather](https://t.me/botfather)** (the official bot, blue checkmark)
2. Start a chat and send:
   ```
   /newbot
   ```
3. BotFather will ask for a **name** (display name, e.g. `FeedMind`)
4. Then a **username** — must end in `bot` (e.g. `feedmind_notify_bot`)
5. BotFather replies with your **Bot Token**:
   ```
   Use this token to access the HTTP API:
   7412345678:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

> ⚠️ **Keep this token secret.** Anyone with it can send messages as your bot.  
> Never commit it to Git — it goes into GCP Secret Manager only.

---

## Step 2 — Find Your Chat ID

Your bot needs to know *where* to send messages. You'll get a **Chat ID** — a numeric ID for your personal chat (or a group).

### Option A — Personal chat (simplest)

1. Open Telegram and search for your new bot by username
2. Send it any message (e.g. `/start` or `hello`)
3. In your browser, open:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Replace `<YOUR_TOKEN>` with your actual token.
4. Look for the `id` field inside `message.chat`:
   ```json
   {
     "ok": true,
     "result": [
       {
         "message": {
           "chat": {
             "id": 123456789,      ← this is your Chat ID
             "type": "private"
           }
         }
       }
     ]
   }
   ```

### Option B — Private group

1. Create a Telegram group and add your bot to it
2. Send a message in the group
3. Fetch `getUpdates` (same URL as above)
4. Group Chat IDs are **negative numbers** (e.g. `-987654321`)

> **Tip:** If `getUpdates` returns an empty `result`, send another message to the bot/group and try again.

---

## Step 3 — Test the Bot Works

Before touching GCP, confirm your token and Chat ID are correct:

```bash
TOKEN="7412345678:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
CHAT_ID="123456789"

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"${CHAT_ID}\", \"text\": \"✅ FeedMind bot is working!\"}"
```

Expected response:
```json
{
  "ok": true,
  "result": {
    "message_id": 1,
    "text": "✅ FeedMind bot is working!"
  }
}
```

If `"ok": false`, double-check your token and that you sent at least one message to the bot first.

---

## Step 4 — Store Secrets in GCP Secret Manager

Once confirmed working, store both values in GCP Secret Manager:

```bash
PROJECT_ID="your-gcp-project-id"   # replace with your project

# Store the Bot Token
echo -n "7412345678:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" | \
  gcloud secrets create TELEGRAM_BOT_TOKEN \
    --data-file=- \
    --project="${PROJECT_ID}"

# Store the Chat ID
echo -n "123456789" | \
  gcloud secrets create TELEGRAM_CHAT_ID \
    --data-file=- \
    --project="${PROJECT_ID}"
```

Verify they were stored:
```bash
gcloud secrets list --project="${PROJECT_ID}"
```

Expected output:
```
NAME                  CREATED              REPLICATION_POLICY
TELEGRAM_BOT_TOKEN    2026-07-24T...       automatic
TELEGRAM_CHAT_ID      2026-07-24T...       automatic
GEMINI_API_KEY        2026-07-24T...       automatic
```

---

## Step 5 — Verify Secret Access from the Function

The `feedmind-sa` service account must have `roles/secretmanager.secretAccessor`.  
This is granted by `deploy.sh` and `setup-wif.sh`, but you can verify:

```bash
gcloud projects get-iam-policy your-gcp-project-id \
  --flatten="bindings[].members" \
  --filter="bindings.members:feedmind-sa AND bindings.role:secretmanager.secretAccessor" \
  --format="table(bindings.role,bindings.members)"
```

Expected output:
```
ROLE                                    MEMBERS
roles/secretmanager.secretAccessor      serviceAccount:feedmind-sa@...
```

---

## What a FeedMind Telegram Message Looks Like

Once deployed, each new article generates a message like this:

```
*Attention Is All You Need — Transformer Architecture*

• Introduces multi-head self-attention replacing recurrence in seq2seq models.
• Achieves SOTA on WMT translation benchmarks with 3× faster training.
• Positional encodings preserve order without sequential computation overhead.

🔗 Read More
📰 Source: arXiv ML  🎓 Academic
```

---

## Updating the Bot Token

If you need to regenerate the token (e.g. it was compromised), do it in BotFather:

```
/mybots → select your bot → API Token → Revoke current token
```

Then update the secret in GCP without changing the version number:

```bash
echo -n "NEW_TOKEN_HERE" | \
  gcloud secrets versions add TELEGRAM_BOT_TOKEN \
    --data-file=- \
    --project="your-gcp-project-id"
```

The function always reads the **latest** version, so no redeployment is needed.

---

## Troubleshooting

### `"ok": false, "description": "Unauthorized"`
→ Token is wrong or revoked. Regenerate via BotFather.

### `"ok": false, "description": "Chat not found"`
→ The bot hasn't received a message from that chat yet, or the Chat ID is wrong.  
→ Send `/start` to the bot from the target chat and retry `getUpdates`.

### `"ok": false, "description": "Bad Request: can't parse entities"`
→ MarkdownV2 escaping issue. The function handles this automatically via `notification.py`.  
→ If testing manually, use `"parse_mode": "HTML"` or plain text instead.

### Secret not found in Cloud Function logs
→ Confirm the secret name matches exactly (case-sensitive): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`  
→ Confirm the SA has `secretmanager.secretAccessor` (see Step 5 above)
