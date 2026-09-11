<script>
  // One curated story from the `stories` collection (services/news-curator).
  // `ai_summary`/`audio_url` are only ever populated for the handful of
  // stories services/summarizer has processed — everything else degrades to
  // "not shown", same convention as ArticleCard/PaperCard.
  import ListenButton from "./ListenButton.svelte";
  import { BUSINESS_STORY_CATEGORIES } from "../lib/constants.js";

  let { story } = $props();

  // "3 sources" beside the headline is the whole point of clustering — it is
  // the signal that this was not one outlet's lone take.
  let sourceCount = $derived(story.sources?.length ?? story.cluster_size ?? 1);
</script>

<article class="card">
  <h3 class="title">
    <a href={story.canonical?.url} target="_blank" rel="noopener noreferrer">
      {story.canonical?.title}
    </a>
  </h3>
  <div class="meta">
    <span class="source">{story.canonical?.source}</span>
    {#if sourceCount > 1}
      <span class="corroboration" title={story.sources?.join(", ")}>
        +{sourceCount - 1} more
      </span>
    {/if}
    {#if story.business_category}
      <span class="badge">{BUSINESS_STORY_CATEGORIES[story.business_category] ?? story.business_category}</span>
    {/if}
    {#if story.audio_url}
      <ListenButton url={story.audio_url} label={story.canonical?.title} />
    {/if}
  </div>

  {#if story.ai_summary}
    <details class="ai-summary">
      <summary>AI summary</summary>
      <p>{story.ai_summary}</p>
    </details>
  {/if}

  {#if story.related_articles?.length}
    <details class="related">
      <summary>Also covered by {story.related_articles.length} other outlet{story.related_articles.length === 1 ? "" : "s"}</summary>
      <ul>
        {#each story.related_articles as related (related.url)}
          <li>
            <a href={related.url} target="_blank" rel="noopener noreferrer">
              {related.source}: {related.title}
            </a>
          </li>
        {/each}
      </ul>
    </details>
  {/if}
</article>

<style>
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.9rem 1rem;
  }
  .title { margin: 0 0 0.35rem; font-size: 0.98rem; font-weight: 600; }
  .meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    font-size: 0.75rem;
    color: var(--muted);
  }
  .source { color: var(--accent); }
  .corroboration { color: var(--muted); }
  .badge {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.1rem 0.5rem;
  }

  .ai-summary, .related { margin-top: 0.5rem; font-size: 0.82rem; }
  .ai-summary summary, .related summary {
    cursor: pointer;
    color: var(--muted);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .ai-summary summary:hover, .related summary:hover { color: var(--accent); }
  .ai-summary p { margin: 0.4rem 0 0; color: var(--muted); line-height: 1.5; }
  .related ul { margin: 0.4rem 0 0; padding-left: 1.1rem; }
  .related li { margin-bottom: 0.25rem; }
  .related a { color: var(--text); }
</style>
