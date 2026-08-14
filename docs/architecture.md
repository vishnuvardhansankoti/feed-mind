# paper-prism — Architecture

Visual companion to `paper-prism-prd.md`. Three loosely-coupled components joined
only by the Firestore document schema: a batch **pipeline** writes, a **web** SPA
reads, and **infra** provisions the GCP stack.

## System flow (deploy-time + run-time)

```mermaid
flowchart LR
    subgraph Trigger
        SCH[Cloud Scheduler<br/>weekly cron]
    end

    subgraph Compute["Cloud Run Job — ONNX-slim image"]
        JOB[paper_prism pipeline]
    end

    subgraph External
        ARX[(arXiv Atom XML API)]
        GEM[gemini 3.5 Flash<br/>AI Studio REST]
    end

    subgraph GCP["Google Cloud"]
        SM[Secret Manager<br/>gemini-api-key]
        FS[(Firestore<br/>runs / run_status)]
    end

    subgraph Frontend
        SPA[Svelte SPA<br/>Firebase Hosting]
        USER([Browser])
    end

    SCH -->|"run: (invoker SA)"| JOB
    JOB -->|fetch 7-day preprints| ARX
    JOB -->|read key at startup| SM
    JOB -->|summarize top-K| GEM
    JOB -->|write docs + expire_at TTL| FS
    USER --> SPA
    SPA -->|read-only client SDK| FS

    FS -. "TTL sweep: delete where expire_at < now<br/>(retention 45d)" .-> FS
```

Ranking is authoritative (local cosine); Gemini only summarizes. The browser
never writes — `firestore.rules` allows public read, `write: if false`; the job
writes server-side under a service account that bypasses rules.

## Pipeline internals (per run)

`Pipeline.run()` loops the three lenses **best-effort**: one lens failing is
recorded as `skipped` and does not abort the others.

```mermaid
flowchart TD
    START([python -m paper_prism]) --> CFG[load_config<br/>env-driven]
    CFG --> LOOP{for each lens<br/>AIML / NLP / CV}

    LOOP --> FETCH[ArxivClient.fetch_lens<br/>throttle · paginate · retry]
    FETCH --> PRIM{primary category<br/>owned by this lens?}
    PRIM -->|no: cross-listed elsewhere| DROP[skip paper]
    PRIM -->|yes| EMBED[Embedder.encode<br/>MiniLM ONNX, no torch<br/>L2-normalized]

    EMBED --> RANK[rank_top_k<br/>cosine = dot product<br/>take TOP_K]
    RANK --> SUM[Summarizer.summarize<br/>Gemini, 2 sentences]
    SUM -->|failure| NULLSUM[summary = null<br/>paper kept]
    SUM -->|ok| DOC
    NULLSUM --> DOC[build RunDocument<br/>+ expire_at]

    DOC --> SINK[Sink.write_run<br/>Local JSON or Firestore]
    SINK --> STATUS{lens ok?}
    STATUS -->|exception| SKIP[run_status: skipped]
    STATUS -->|ok| OK[run_status: ok]

    SKIP --> LOOP
    OK --> LOOP
    LOOP -->|done| WSTAT[write run_status doc<br/>+ expire_at]
    WSTAT --> EXIT([exit 1 if any lens failed])
```

**Lens → arXiv source mapping** (disjoint sets; a paper's *primary* category maps
it to at most one lens):

| Lens (`category`) | arXiv sources |
|---|---|
| `AIML` | `cs.LG`, `cs.AI` |
| `NLP` | `cs.CL` |
| `CV` | `cs.CV` |

## Web data path

`web/src/lib/data.js` is a source abstraction; `VITE_DATA_SOURCE` swaps the
backend behind identical return shapes. The Firebase SDK is dynamically imported,
so `mock` builds never ship it.

```mermaid
flowchart TD
    APP[App.svelte<br/>Latest · Archive tabs] --> API["getLatest / getArchive / getStatus"]
    API --> SRC{VITE_DATA_SOURCE}

    SRC -->|mock| FIX[public/fixtures/*.json<br/>manifest + runs + run_status]
    SRC -->|firestore| FSQ["Firestore queries<br/>where(category==X)<br/>orderBy(run_date desc)<br/>limit 1 (Latest) / 5 (Archive)"]

    FIX --> NORM[normalizeRun<br/>run_date → Date]
    FSQ --> NORM
    NORM --> RENDER[LensColumn / PaperCard / FreshnessBadge]
```

Latest/Archive queries require the composite index on `(category ASC, run_date
DESC)` declared in both `firestore.indexes.json` and `infra/main.tf`.

`VITE_FIRESTORE_DATABASE` (passed to `getFirestore(app, id)`; unset → `(default)`)
selects the Firestore database the browser reads. It **must match the pipeline's
`FIRESTORE_DATABASE`** (default `feed-mind-db`) — the read path is direct from the
browser, so a mismatch silently reads an empty `(default)`.

## Shared data contract (Firestore)

The one hard coupling across components — defined in
`pipeline/src/paper_prism/models.py`, consumed in `web/src/lib/data.js`.

```mermaid
erDiagram
    runs {
        string id "YYYY-MM-DD_CATEGORY (doc id)"
        timestamp run_date
        string category "AIML | NLP | CV"
        array papers "rank, title, arxiv_id, url, score, summary"
        timestamp expire_at "TTL: run_date + retention_days"
    }
    run_status {
        string id "YYYY-MM-DD (doc id)"
        timestamp run_date
        map categories "per-lens: status ok|skipped, paper_count|reason"
        timestamp expire_at "TTL: run_date + retention_days"
    }
```

Doc IDs are deterministic, so re-runs overwrite idempotently.

## Provisioning: two parallel paths

`infra/` (Terraform, IaC source of truth) and `pipeline/deploy/*.sh` (imperative
`gcloud`) create the **same** GCP resources — Artifact Registry, Firestore
(named database via `FIRESTORE_DATABASE` / `var.firestore_database`, default
`feed-mind-db`) + index + TTL policies, two service accounts (least-privilege job
SA + scheduler invoker SA), the Gemini secret, the Cloud Run Job, and the weekly
Scheduler. Use one; running both double-creates. On the gcloud path,
`pipeline/deploy/01b-setup-firestore-db.sh` provisions the named database.
