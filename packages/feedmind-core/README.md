# feedmind-core

The shared FeedMind pipeline: feed URLs in, Firestore documents out.

Not deployed on its own. Five Cloud Functions depend on it, and it reaches each
of them by being copied into the deploy directory — see
[`scripts/stage-service.sh`](../../scripts/stage-service.sh).

## What a consuming service looks like

Two files. A `feeds.yaml`:

```yaml
service: news
kind: rss                 # rss | youtube
summarize: sumy           # sumy | gemini | none
deliver_telegram: true    # mark articles pending, then ring the notifier
content_ready: true       # wake services/summarizer for AI summary + audio

feeds:
  - name: Hugging Face Papers
    url: https://huggingface.co/blog/feed.xml
    category: academic
```

and a `main.py`:

```python
import functions_framework
from feedmind_core import runner, serviceconfig

CONFIG = serviceconfig.load_beside(__file__)

@functions_framework.http
def ingest(request):
    return json.dumps(runner.run_rss_ingest(CONFIG)), 200
```

The config is loaded at import, so a malformed `feeds.yaml` fails the cold start
loudly rather than looking like "no new articles today" in the run summary.

## Dependency extras

Base install covers Firestore, Secret Manager and YAML. Everything else is an
extra, so a service ships only what it calls:

| Extra | Pulls in | Used by |
|---|---|---|
| `feeds` | feedparser | every ingest service |
| `sumy` | sumy, nltk, numpy | the services that summarize |
| `gemini` | google-generativeai | `summarize: gemini` |
| `telegram` | httpx | the notifier, and the archive's run report |
| `events` | google-cloud-pubsub | services that announce downstream |
| `archive` | google-cloud-bigquery | the archiver |

This is why `models.py` imports nothing outside the standard library and why
`runner.py`'s heavy imports are lazy. See `CLAUDE.md` before adding an import.

## Local development

```bash
uv sync          # the dev group carries every extra
uv run pytest -q
```

Consuming services depend on this as an editable path dependency, so an edit
here is live in every service immediately.
