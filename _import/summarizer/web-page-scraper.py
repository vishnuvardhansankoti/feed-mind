#!/usr/bin/env python3
"""Scrape a web page, print just the readable article text, and optionally
summarize it with an LLM.

Strips scripts, styles, nav bars, headers/footers, sidebars, ad slots, share
widgets, comment sections and similar noise, then picks the densest block of
real prose (a readability-style heuristic) and prints it.

Standard library only, apart from the optional pyttsx3 dependency used by the
audio flags. This file is just the entry point - the implementation lives in
the `webscraper` package next to it.

Usage:
    python web-page-scraper.py https://example.com/some-article
    python web-page-scraper.py URL --width 0          # no wrapping
    python web-page-scraper.py URL --max-chars 2000   # truncate output
    python web-page-scraper.py URL --summarize        # + 2-3 sentence summary
    python web-page-scraper.py URL -s --summary-only  # just the summary
    python web-page-scraper.py URL --speak            # read the summary aloud
    python web-page-scraper.py URL --audio out.aiff   # save the summary as audio
    python web-page-scraper.py --list-voices          # list installed voices
    python web-page-scraper.py --init-config          # write a sample config

The summarizer is config driven - see webscraper/config.py and --init-config.
Any provider works as long as it speaks one of three wire formats: "openai"
(OpenAI, Ollama's /v1 endpoint, Groq, vLLM, LM Studio, OpenRouter, Together...),
"ollama" (native /api/chat) or "anthropic" (/v1/messages).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from webscraper.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
