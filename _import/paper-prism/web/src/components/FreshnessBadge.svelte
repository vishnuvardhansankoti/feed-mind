<script>
  import { LENSES } from "../lib/constants.js";

  // Surfaces the run_status doc so a silently-skipped lens is visible (PRD §9a).
  //
  // This used to render one chip per lens, every visit, all of them reading
  // "fresh" whenever the pipeline was healthy — an alarm that is always green,
  // which is an alarm nobody reads. Worse, "fresh" claimed recency it could not
  // know: run_status only records whether the last run *succeeded*, so a
  // scheduler that stopped firing a month ago still showed three green chips.
  //
  // So: state the thing that is actually true and useful (when the digest was
  // built), and raise a chip only for a lens that genuinely did not complete.
  let { status } = $props();

  // UTC, not local: run_date is a calendar date (the run doc id is
  // `runs/YYYY-MM-DD_<CAT>`) stamped at midnight UTC, not an instant. Formatting
  // it locally renders the 13th as "Aug 12" for anyone behind UTC.
  const dateFmt = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

  // run_date is a Date by the time it reaches here (data.js::normalizeStatus),
  // but guard anyway — Intl throws on an Invalid Date and would take the
  // masthead down with it.
  let built = $derived(
    status?.run_date instanceof Date && !isNaN(status.run_date)
      ? dateFmt.format(status.run_date)
      : null,
  );

  // Anything the pipeline did not mark `ok`, including a lens missing from the
  // doc entirely — a run that died before reaching a lens never records it.
  //
  // No status doc at all is different from a doc reporting failures: it means we
  // know nothing, so say nothing. Flagging all three lenses there would assert a
  // pipeline failure we have no evidence for.
  let problems = $derived(
    status
      ? LENSES.filter((l) => (status.categories?.[l.code]?.status ?? "missing") !== "ok")
      : [],
  );
</script>

{#if built || problems.length}
  <div class="badges" role="status" aria-label="digest freshness">
    {#if built}
      <span class="chip" title="When this digest was built">
        <b>Digest</b>
        {built}
      </span>
    {/if}

    {#each problems as lens (lens.code)}
      <span class="chip warn" title="This lens did not complete in the last run">
        <b>{lens.label}</b>
        {status?.categories?.[lens.code] ? "incomplete" : "no data"}
      </span>
    {/each}
  </div>
{/if}

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
    white-space: nowrap;
  }
  .chip b { color: var(--text); font-weight: 600; }
  .chip.warn { border-color: color-mix(in srgb, var(--warn) 55%, var(--border)); }
  .chip.warn b { color: var(--warn); }
</style>
