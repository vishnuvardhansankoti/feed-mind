<script>
  import { LENSES } from "../lib/constants.js";
  // Surfaces the run_status doc so a silently-skipped lens is visible (PRD §9a).
  let { status } = $props();

  function state(code) {
    const c = status?.categories?.[code];
    if (!c) return { cls: "unknown", text: "—" };
    return c.status === "ok"
      ? { cls: "ok", text: "fresh" }
      : { cls: "warn", text: "stale" };
  }
</script>

<div class="badges" role="status" aria-label="data freshness by lens">
  {#each LENSES as lens (lens.code)}
    {@const s = state(lens.code)}
    <span class="chip {s.cls}">
      <b>{lens.label}</b>
      {s.text}
    </span>
  {/each}
</div>

<style>
  .badges { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .chip {
    font-size: 0.72rem;
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--muted);
    display: inline-flex;
    gap: 0.3rem;
  }
  .chip b { color: var(--text); font-weight: 600; }
  .chip.ok { border-color: color-mix(in srgb, var(--ok) 45%, var(--border)); }
  .chip.ok b { color: var(--ok); }
  .chip.warn { border-color: color-mix(in srgb, var(--warn) 55%, var(--border)); }
  .chip.warn b { color: var(--warn); }
</style>
