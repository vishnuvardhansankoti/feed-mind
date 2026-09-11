# Switching FeedMind's TTS backend

`feedmind-audio`'s Cloud Run container ships both TTS backends —
`webscraper/cloud_speech.py` (Google Cloud Text-to-Speech) and
`webscraper/speech.py` (Piper, a neural TTS, transcoded to MP3 with ffmpeg).
`FEEDMIND_TTS` picks between them at request time (`main.py` reads it into
`--tts` for every run of `feedmind_audio.py`). Flipping it is a config update
only — no rebuild, no redeploy of code, just a new revision with the changed
env var. See `services/summarizer/CLAUDE.md`'s "Cloud Run migration" section
for why this needed a platform change to become possible at all.

The default is `local` — free, unlike Cloud TTS's metered
1M-character/month tier. Switch to `cloud` by hand if Piper's voice quality
isn't good enough for some use. Piper replaced espeak-ng as the local
backend (2026-09) — same free/unlimited property, a neural vocoder instead
of espeak-ng's formant synthesizer for meaningfully better voice quality;
see `services/summarizer/CLAUDE.md`'s "Piper" section.

This also controls whether `NEWS_STORIES`' `TOP_K_PER_CATEGORY` audio cap
(`services/news-curator`'s `config.py`, default 10) applies at all: every
canonical story gets a text summary regardless, but audio generation only
respects that cap under `--tts cloud` — the free-tier reason for capping it.
Under `local` every canonical story gets audio too. See
`services/summarizer/CLAUDE.md`'s NEWS_STORIES section.

## Switch to local (Piper)

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
