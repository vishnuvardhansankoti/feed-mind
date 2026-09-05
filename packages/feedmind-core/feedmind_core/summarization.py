"""
summarization.py — Article summarization backends.

Two interchangeable implementations, selected at runtime by
the feed group's `summarize:` setting:
  - summarize_with_sumy(): offline extractive summarization (sumy LSA + NLTK).
    The default. No API key, no network call, deterministic, cannot hallucinate.
  - summarize(): abstractive summarization via the Gemini API. Opt-in.
"""

import logging
import re
import time

import google.generativeai as genai
from sumy.nlp.stemmers import Stemmer
from sumy.nlp.tokenizers import Tokenizer
from sumy.parsers.plaintext import PlaintextParser
from sumy.summarizers.lex_rank import LexRankSummarizer
from sumy.utils import get_stop_words

from feedmind_core import settings as config
from feedmind_core.models import Article

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sumy helpers
# ---------------------------------------------------------------------------
_MAX_SUMMARY_WORDS = 15

# Patterns stripped from RSS snippets before summarization
_BOILERPLATE_PATTERNS = [
    re.compile(r"(?i)\bRead\s+more\.?\.?\.?\s*$"),
    re.compile(r"(?i)\bContinue\s+reading\.?\.?\.?\s*$"),
    re.compile(r"(?i)The\s+post\s+.{0,120}\s+appeared\s+first\s+on\s+.{0,80}\.?\s*$"),
    re.compile(r"(?i)\[…\]"),
    re.compile(r"(?i)\[\.\.\.\]"),
    re.compile(r"\s{2,}"),  # collapse multiple spaces
]


def _clean_snippet(text: str) -> str:
    """Strip common RSS boilerplate and collapse whitespace."""
    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub(" ", text)
    return text.strip()


def _truncate_to_words(text: str, max_words: int = _MAX_SUMMARY_WORDS) -> str:
    """Truncate text to at most *max_words* words, appending '...' if trimmed."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def init_gemini(api_key: str) -> genai.GenerativeModel:
    """Configure the Gemini SDK and return a GenerativeModel instance."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=config.GEMINI_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            max_output_tokens=150,  # 3 bullets × ~50 tokens — keep it tight
            temperature=0.3,  # low temperature for deterministic, factual output
        ),
    )
    logger.info("Gemini model initialised: %s", config.GEMINI_MODEL)
    return model


def summarize(model: genai.GenerativeModel, article: Article) -> str | None:
    """
    Call the Gemini API to produce a one-sentence summary of the article.

    Args:
        model: Initialised GenerativeModel.
        article: Article to summarize.

    Returns:
        Summary string, or None on failure (caller skips the article and
        retries it on the next run).
    """
    if not article.snippet:
        logger.warning("Empty snippet — skipping summarization: article_id=%s", article.article_id)
        return None

    prompt = f"Article title: {article.title}\n\nArticle content:\n{article.snippet}"

    try:
        response = model.generate_content(
            prompt,
            request_options={"timeout": config.GEMINI_TIMEOUT_SECONDS},
        )
        summary = response.text.strip()
        logger.info(
            "Article summarized: article_id=%s source=%s",
            article.article_id,
            article.feed_source,
        )
        return summary

    except Exception as exc:
        logger.error(
            "Gemini summarization failed: article_id=%s error=%s",
            article.article_id,
            exc,
        )
        return None

    finally:
        # Respect free-tier rate limits (e.g. 15 RPM)
        time.sleep(config.GEMINI_REQUEST_DELAY_S)


def summarize_with_sumy(article: Article) -> str:
    """
    Extract a single concise sentence using the LexRank algorithm.

    Pipeline: clean snippet → LexRank (1 sentence) → truncate to ≤15 words.
    Falls back to a truncated title when the snippet is empty or extraction fails.
    Skips LexRank for very short inputs (< 2 sentences) to avoid numpy
    RuntimeWarning from zero-norm vectors in the power method.
    """
    if not article.snippet:
        return _truncate_to_words(article.title)

    cleaned = _clean_snippet(article.snippet)
    if not cleaned:
        return _truncate_to_words(article.title)

    try:
        parser = PlaintextParser.from_string(cleaned, Tokenizer("english"))

        # LexRank needs ≥ 2 sentences to build a meaningful similarity matrix.
        # With only 1 sentence the cosine-similarity matrix is degenerate and
        # numpy raises: "RuntimeWarning: invalid value encountered in divide".
        if len(parser.document.sentences) < 2:
            return _truncate_to_words(str(parser.document.sentences[0]))

        stemmer = Stemmer("english")
        summarizer = LexRankSummarizer(stemmer)
        summarizer.stop_words = get_stop_words("english")

        # Request exactly 1 sentence — the most "central" one
        summary_sentences = summarizer(parser.document, 1)
        if summary_sentences:
            return _truncate_to_words(str(summary_sentences[0]))
        return _truncate_to_words(article.title)
    except Exception as exc:
        logger.error("Sumy summarization failed for article_id=%s: %s", article.article_id, exc)
        return _truncate_to_words(article.title)
