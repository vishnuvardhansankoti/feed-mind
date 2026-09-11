# news-curator

Embeds, classifies, clusters and ranks the articles `services/india-news-ingest`
stores, so only a handful of deduplicated, ranked stories a day ever reach an
LLM. Design doc: `../../docs/feed-mind/news-curator-design.md`. Working
guidance: `CLAUDE.md`.

```bash
uv sync --extra dev
cp .env.example .env
uv run python -m news_curator   # local dry run: reads real Firestore, writes JSON to ./output/stories/
uv run pytest
```

Deployed as a Cloud Run service triggered by a Pub/Sub push subscription on
`feedmind-news-ingested` — see `deploy/README.md`-equivalent instructions in
`CLAUDE.md`'s Commands section (there is no separate deploy README; the four
`deploy/NN-*.sh` scripts are numbered in run order and each is self-documenting).
