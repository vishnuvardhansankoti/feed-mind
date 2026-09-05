"""Readable-content extraction for web pages, with optional LLM summaries.

Standard library only, except for the optional pyttsx3 dependency that the
`speech` module imports lazily. Typical use as a library:

    from webscraper import fetch, extract, summarize, load_config, resolve_provider

    html = fetch("https://example.com/article")
    text = extract(html, width=100)
    settings = resolve_provider(load_config())
    print(summarize(text, settings))

Module map:
    dom        parsing HTML into a forgiving tree, plus node metrics
    cleaner    pruning ads, nav, sidebars, comments and other chrome
    scorer     picking the subtree that holds the article
    renderer   flattening that subtree into tidy text blocks
    extractor  the pipeline that ties the four together
    fetcher    downloading pages
    config     layering config file, environment and CLI overrides
    condense   spaCy extractive pre-filter (optional dependency)
    llm        provider adapters and the summarize() call
    speech     pyttsx3 text-to-speech (optional dependency)
    cli        argument parsing and console output
"""

from __future__ import annotations

from .condense import extractive_filter
from .config import (
    DEFAULT_PROMPT,
    load_config,
    resolve_provider,
    write_sample_config,
)
from .errors import (
    CondenseError,
    ConfigError,
    FetchError,
    LLMError,
    ScraperError,
    SpeechError,
)
from .extractor import Article, extract, extract_article
from .fetcher import fetch, normalize_url
from .llm import call_llm, summarize
from .speech import list_voices, speak

__version__ = "1.0.0"

__all__ = [
    "Article",
    "CondenseError",
    "ConfigError",
    "DEFAULT_PROMPT",
    "FetchError",
    "LLMError",
    "ScraperError",
    "SpeechError",
    "call_llm",
    "extract",
    "extractive_filter",
    "extract_article",
    "fetch",
    "list_voices",
    "load_config",
    "normalize_url",
    "resolve_provider",
    "speak",
    "summarize",
    "write_sample_config",
]
