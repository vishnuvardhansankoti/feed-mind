# FeedMind Voice Agent: a mobile app for feed-mind + sanathana-gnanam

**Status:** designed; not yet built
**Date:** 2026-09-19
**Scope:** a new Flutter app (iOS + Android) plus a new backend Cloud Run
service (working name: `feedmind-voice-backend`) that lets the family ask
FeedMind and sanathana-gnanam questions by voice — "what's today's India
political news," "open Adiparvam from Andhra Mahabharatam," "find papers
similar to \<paper\>." This is the first component in the feed-mind system that
does request-path compute for an end user; every existing deployable either
runs on a schedule or serves static/public-read data straight from Firestore
with no backend in the loop (see the root
[`CLAUDE.md`](../../CLAUDE.md#what-this-is)).

This document is the output of an interview-style design session
(`new-reqt.md`), not an implementation plan — no code was written. Read it as
the shared understanding to build from, including the things it deliberately
rejects.

---

## 1. What this explicitly assumes already exists

**A multi-book registry across the sanathana-gnanam family is a
prerequisite, not part of this project.** Today `sanathana-gnanam` is a thin
Astro portal (`src/data/apps.ts`) with zero build/runtime coupling to the
sites it links to — each site (`AndhraMahabharatam-audio`,
`bhratruhari-subhaashitaani-audio`, ...) is independently built and deployed,
and `AndhraMahabharatam-audio` today holds exactly **one** book (Adi Parvam),
not a container of several. Voice commands like "open Adiparvam from Andhra
Mahabharatam" or "open the first book" assume:

1. `AndhraMahabharatam-audio` has been restructured into a container of
   multiple named, ordered books, each with its own page manifest.
2. Some single, queryable index exists mapping site → book → manifest URL,
   so the voice agent can discover new books/sites without scraping HTML or
   being redeployed every time the family adds a book.

Neither exists yet. This design assumes both are built separately, ahead of
this project, and treats "the registry" as an external read-only dependency.

---

## 2. What the agent does

Two knowledge domains, three kinds of user intent, unified behind **one**
mechanism rather than a hand-built router plus a separate Q&A engine:

| Example | Intent | Mechanism |
|---|---|---|
| "What's today's India political news" | structured/semantic query over `stories` | RAG over feed-mind |
| "What's the news on Nepal floods today" | semantic match, not a category filter — must find the *right* story and its `audio_url` | RAG over feed-mind |
| "Open Adiparvam from Andhra Mahabharatam" / "open the first book" | navigation, resolved against the external registry | tool call, no RAG |
| "Find papers similar to \<paper on feed-mind\>" | open-web lookup | Gemini search grounding |

The backend hands the transcribed command to Gemini with a small tool set
(function-calling) and lets the model pick:

- `open_book(site, book, page?)` — resolves against the external registry,
  returns a deep-link/action for the client to execute
- `query_stories(text)` / `query_articles(text)` — vector RAG over feed-mind
- `query_book_content(text)` — vector RAG over sanathana-gnanam page text
- `web_search()` — Gemini's built-in Google Search grounding, config-gated

There is deliberately no separate hand-built intent classifier in front of
this — Gemini's tool selection *is* the router.

---

## 3. Why this needs a backend at all

`apps/web`'s entire model is backend-less: the browser reads Firestore
directly, public-read rules do authorization, and the "no request-path
compute" contract is intact system-wide (root `CLAUDE.md`). Two things break
that model here, not by choice but by what's technically possible:

1. **BigQuery has no public-client access path.** Firestore rules can grant
   public read; BigQuery cannot — it needs a service account and bills per
   query. Any "search the archive" capability requires a server in the loop,
   full stop.
2. **Firestore has no native vector index.** Real semantic retrieval
   ("Nepal floods" → the right story, not a category filter) needs either a
   managed vector store or an in-memory index computed and queried
   server-side.

So this is the first FeedMind deployable with a backend on the request path,
and the design below tries to keep it as close to the rest of the system's
free-tier, scale-to-zero discipline as that allows.

---

## 4. Architecture at a glance

```
                    ┌── iOS: App Intents / Siri Shortcuts (native ASR)
Flutter app (thin) ─┤
                    └── Android: in-app wake-word engine, foreground-only
                              │  audio / transcribed text
                              ▼
                    feedmind-voice-backend        (new Cloud Run service)
                              │
                    ┌─────────┼─────────────────────────┐
                    │         │                          │
                    ▼         ▼                          ▼
              Gemini (reasoning,   in-memory vector index    users/{uid}
              native audio in/out,  (today's stories +        (session /
              search grounding)     sanathana-gnanam text,    conversation
                    │                archive: config, off      state)
                    │                by default)
                    ▼
         feedmind-content-ready ──▶ embedding refresh (event-driven,
         (existing doorbell,         new subscriber on this topic)
          new 3rd consumer)

         sanathana-gnanam sites ──▶ embedding refresh (polled — no
         (external, no doorbell)     doorbell exists there)
```

---

## 5. Client: Flutter, thin

**No on-device LLM.** The original ask assumed a small local model
(`gemma:4b`) would be enough because the knowledge base was assumed small and
local. It isn't: real semantic retrieval requires a network round-trip to the
backend regardless, web search requires network, and `services/summarizer`
already depends on the Gemini API elsewhere in this system. Once retrieval is
inherently server-dependent, an on-device model duplicates work the backend
already has to do, with a strictly worse model (a 2.5–3GB int4 4B model needs
flagship-tier phones with 8GB+ RAM, has materially weaker function-calling
reliability than a hosted model, and buys offline capability the rest of the
design doesn't otherwise support). The phone is a **thin client**: capture
audio, call the backend, play back the response.

**Framework:** Flutter/Dart, chosen over React Native despite this being a
JS/TS-heavy monorepo, and over wrapping `apps/web` via Capacitor despite the
reuse that would offer — both the App Intents bridge (iOS) and the wake-word
foreground service (Android) need real native code regardless of shell
choice, and this is a deliberately unhurried personal project where getting
the native integration right outweighed reuse or a shorter learning curve.

**Wake trigger — platform-specific by necessity, not preference.** True
always-on background wake-word ("Hey Siri"-style) is not available to
third-party apps on either platform — iOS suspends backgrounded apps within
seconds and grants no public API for continuous background mic capture; the
Android equivalent (a foreground service) requires a persistent notification,
drains battery, and is aggressively killed by most OEMs anyway.

- **iOS:** native **App Intents** / Siri Shortcuts. "Hey Siri, ask FeedMind
  about \<X\>" is handled by Siri itself — Siri does the ASR and hands the app
  a parsed intent+text, without a custom wake-word engine and without the app
  needing to be foregrounded first.
- **Android:** a custom in-app wake-word engine (e.g. Porcupine or
  openWakeWord) via a foreground service, **foreground-only** — the app must
  already be open/frontmost for "hey feedmind" to be heard.

**Speech I/O — config-driven, two backends**, same shape as `apps/web`'s
`VITE_DATA_SOURCE` mock/firestore split:

- **Default: server-side**, using **Gemini's native audio understanding**
  for the input side and Gemini TTS for output — the same provider already
  used for reasoning, search grounding, and (via `services/summarizer`)
  narration elsewhere in this system. One voice loop, one vendor.
- **Switchable: platform-native** (`Speech`/`SpeechRecognizer`,
  `AVSpeechSynthesizer`/Android `TextToSpeech`) via a config flag — free,
  offline-tolerant, but weaker on domain vocabulary (book titles like
  "Adiparvam," transliterated Telugu names).

**Response language:** fixed English, regardless of whether the underlying
content is English (news) or Telugu-script OCR text (the books). No
per-domain language switching.

**Auth:** the same Google Sign-In + Firestore-rules allowlist as `apps/web`
(via FlutterFire) — not optional. It's also the identity conversation state
hangs off (§7).

---

## 6. Backend: `feedmind-voice-backend`

A new Cloud Run service, following the existing `news-curator`/`summarizer`
pattern (own `pyproject.toml`/`uv.lock`, own `deploy/*.sh`, not part of
`deploy-feedmind.sh`).

**Reasoning:** Gemini, given the four tools in §2 via function-calling.

**Vector store: DIY, embedded in the container, not a managed service.**
Every other GCP resource in this system scales to zero and stays inside
free-tier limits (root `CLAUDE.md`, Retention section); a managed vector DB
(Vertex AI Vector Search bills a running index endpoint hourly regardless of
query volume) would be the first that doesn't. Instead: embeddings persisted
to Firestore/Cloud Storage, loaded into memory in the Cloud Run container
(brute-force or ANN via `numpy`/`faiss-cpu`/`hnswlib`), queried at request
time. Default scope is **today's feed-mind content + sanathana-gnanam
text only** — bounded, cheap, fast to load on a cold start. Pulling BigQuery
archive content into the index is a **config flag, disabled by default**;
flip it if/when "search the archive" is actually wanted, and revisit the
DIY-vs-managed tradeoff if the in-memory index outgrows a single container's
memory once that flag is on.

**Refresh cadence — different per source, because the two sources have
different update mechanisms:**

- **feed-mind side: event-driven.** The backend is a new (third) subscriber
  on the existing `feedmind-content-ready` topic (root `CLAUDE.md`'s "The
  Pub/Sub topic is owned by its consumer" section — this needs the same
  `roles/pubsub.publisher` grant story every other consumer needed).
  Same-day freshness: a story published mid-afternoon is searchable that
  afternoon, not the next morning.
- **sanathana-gnanam side: polled.** There is no doorbell to subscribe to —
  it's a separate, manually-deployed project family with no event system of
  its own. The backend periodically checks the (external, prerequisite)
  registry for new/changed content.

**Web search:** Gemini's built-in Google Search grounding — a flag on the
Gemini request itself, not a separate provider/API key/quota. Chosen over a
standalone search API (Google Custom Search JSON API, etc.) specifically
because it reuses the same Gemini call already being made for reasoning, and
"config-driven enable/disable" falls out for free as a boolean on that
request. Considered and rejected: a paper-similarity-specific API
(Semantic Scholar / arXiv) — rejected because the requirement widened to
general open-web search, not just papers, during the design session.

---

## 7. Session / conversation memory

**Multi-turn, not single-shot** — "play the next page," "what about
yesterday's version of that story," "continue where I left off in Adiparvam"
all require the backend to remember the prior turn. State lives on
`users/{uid}`, the one Firestore doc `apps/web`'s `lib/prefs.js` already owns
(today: `bookmarks`, `unfollowed`) — a new session/conversation field added
there, written with the same `merge: true` discipline so it can't clobber the
existing fields. This is why phone-side auth isn't optional (§5): there is no
identity to hang session state off without it.

---

## 8. Distribution

**Private/internal only — no public store listing.** A 6-address family
allowlist has no reason for App Store/Play Store review exposure, especially
given the always-listening wake-word behavior would draw real scrutiny in a
public review.

- **iOS:** TestFlight internal testing (up to 100 testers, no App Store
  review required). Requires a **paid Apple Developer Program account
  ($99/yr)** — this is not optional even for purely private distribution,
  because App Intents needs entitlements that free provisioning profiles
  (7-day expiry, no App Intents capability) can't carry. This cost is a
  direct consequence of the iOS wake-trigger decision in §5, not a
  distribution preference.
- **Android:** sideloaded APK (free) or Play Console internal testing track
  ($25 one-time).

---

## 9. Cost shape (order of magnitude, not a quote)

Real usage volume isn't known yet — this is directional, not a budget.

| Item | Cost | Notes |
|---|---|---|
| Apple Developer Program | $99/yr | fixed, mandatory for App Intents (§8) |
| Google Play Console | $25 one-time | only if using internal test track over sideloading |
| Cloud Run (backend service + Pub/Sub subscriber) | ~$0 | family-scale, sporadic-query volume stays inside free tier, same discipline as the rest of this system |
| Cloud Storage (embeddings) | ~$0 | small volume |
| Gemini API (reasoning + audio in/out + search grounding + embeddings) | low, usage-driven | the one real variable — audio and grounding calls cost more per call than plain text; the line to watch if usage grows beyond occasional family use |

---

## 10. Rejected / deferred alternatives

Recorded so a future revisit doesn't re-litigate these from scratch:

- **On-device `gemma:4b` for reasoning** — rejected once retrieval was
  established as inherently server-dependent (§5). Feasible in isolation
  (Gemma 3/3n runs on both platforms via Google's MediaPipe LLM Inference
  API / LiteRT on flagship-tier 8GB+ RAM devices) but adds cost without a
  matching benefit here.
- **In-context retrieval without embeddings** (stuff today's story titles
  into the prompt directly, no vector index) — viable at today's data
  volume, rejected because archive-depth search was an explicit goal, even
  though archive pulling ended up config-gated and off by default (§6).
- **A managed vector DB from day one** (Vertex AI Vector Search, hosted
  Pinecone/Weaviate) — rejected in favor of DIY-in-container to preserve the
  system's scale-to-zero, free-tier posture; explicitly a "revisit if it
  outgrows the container" decision, not a permanent rejection.
- **A standalone web search API** (Google Custom Search, Bing — the latter
  retired in 2025) — rejected in favor of Gemini's built-in search grounding
  to avoid a second provider/key/bill for a "minimal" feature.
- **React Native, and Capacitor-wrapping `apps/web`** — both rejected for
  Flutter despite offering more code reuse or language familiarity; native
  wake-trigger integration on both platforms needs real native code
  regardless of shell, and this project explicitly traded reuse/speed for
  building the native pieces correctly.
- **Public App Store / Play Store listing** — rejected; family-only
  allowlist has no reason for the review exposure a public listing would
  invite, especially for the wake-word behavior.
