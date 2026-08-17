<script>
  // One YouTube video from the `youtube_videos` collection. The whole card is a
  // link that opens the video on youtube.com in a new tab.
  let { video } = $props();

  const dateFmt = new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric",
  });

  function relAge(d) {
    if (!(d instanceof Date) || isNaN(d)) return "";
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86_400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86_400)}d`;
  }
</script>

<a class="card" href={video.url} target="_blank" rel="noopener noreferrer">
  <div class="thumb">
    <img src={video.thumbnail_url} alt="" loading="lazy" />
    <span class="play" aria-hidden="true">▶</span>
  </div>
  <div class="body">
    <h3 class="title">{video.title}</h3>
    <div class="meta">
      <span class="channel">{video.channel}</span>
      {#if video.published_date}
        <span class="age" title={video.published_date.toString()}>
          {dateFmt.format(video.published_date)} · {relAge(video.published_date)} ago
        </span>
      {/if}
    </div>
  </div>
</a>

<style>
  .card {
    display: flex;
    gap: 0.9rem;
    text-decoration: none;
    color: inherit;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.6rem;
    transition: border-color 0.15s ease, transform 0.15s ease;
  }
  .card:hover { border-color: var(--accent); transform: translateY(-1px); }
  .card:hover .play { opacity: 1; }

  .thumb {
    position: relative;
    flex: 0 0 160px;
    aspect-ratio: 16 / 9;
    border-radius: calc(var(--radius) - 3px);
    overflow: hidden;
    background: var(--surface-2, var(--border));
  }
  .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .play {
    position: absolute; inset: 0; margin: auto;
    width: 2.4rem; height: 2.4rem; line-height: 2.4rem;
    text-align: center; border-radius: 50%;
    background: rgba(0, 0, 0, 0.6); color: #fff; font-size: 0.9rem;
    opacity: 0.85; transition: opacity 0.15s ease;
  }

  .body {
    display: flex; flex-direction: column; gap: 0.35rem;
    min-width: 0; padding: 0.15rem 0.15rem 0.15rem 0;
  }
  .title {
    margin: 0; font-size: 0.95rem; font-weight: 600; line-height: 1.3;
    display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden;
  }
  .meta {
    display: flex; flex-wrap: wrap; gap: 0.6rem;
    font-size: 0.75rem; color: var(--muted); margin-top: auto;
  }
  .channel { color: var(--accent); }

  @media (max-width: 520px) {
    .thumb { flex-basis: 120px; }
  }
</style>
