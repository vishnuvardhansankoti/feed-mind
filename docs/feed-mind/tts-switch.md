# Switching FeedMind's TTS backend

`feedmind-audio`'s Cloud Run container ships both TTS backends —
`webscraper/cloud_speech.py` (Google Cloud Text-to-Speech) and
`webscraper/speech.py` (pyttsx3 + espeak-ng, transcoded to MP3 with ffmpeg).
`FEEDMIND_TTS` picks between them at request time (`main.py` reads it into
`--tts` for every run of `feedmind_audio.py`). Flipping it is a config update
only — no rebuild, no redeploy of code, just a new revision with the changed
env var. See `services/summarizer/CLAUDE.md`'s "Cloud Run migration" section
for why this needed a platform change to become possible at all.

The default on the initial deploy is `cloud` — no voice-quality change on
cutover day. Switch to `local` by hand when Cloud TTS's 1M-character/month
free tier is close to its cap, and back once the next month's quota resets.

## Switch to local (pyttsx3/espeak-ng)

```bash
gcloud run services update feedmind-audio \
  --region=us-central1 \
  --project=feed-mind \
  --update-env-vars=FEEDMIND_TTS=local
```

## Switch back to cloud (Google Cloud TTS, en-US-Neural2-F)

```bash
gcloud run services update feedmind-audio \
  --region=us-central1 \
  --project=feed-mind \
  --update-env-vars=FEEDMIND_TTS=cloud
```

## Verify which backend is active

```bash
gcloud run services describe feedmind-audio \
  --region=us-central1 \
  --project=feed-mind \
  --format="value(spec.template.spec.containers[0].env)"
```

## Note on the service name during migration

`feedmind-audio` above is the **permanent** name, reached only after the old
gen2 Cloud Function is deleted and the Cloud Run service is deployed under
that name (see `services/summarizer/deploy/00-config.sh` and its cutover
notes). Until then, the service under validation is named `feedmind-audio-run`
— substitute that name in the commands above if the migration hasn't
completed yet.
