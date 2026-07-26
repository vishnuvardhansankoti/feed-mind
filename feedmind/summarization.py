"""
summarization.py — Article summarization backends.

Two interchangeable implementations, selected at runtime by
config.ENABLE_GEMINI_SUMMARIES:
  - summarize_with_sumy(): offline extractive summarization (sumy LSA + NLTK).
    The default. No API key, no network call, deterministic, cannot hallucinate.
  - summarize(): abstractive summarization via the Gemini API. Opt-in.
"""

import logging
import time

import google.generativeai as genai
from sumy.nlp.stemmers import Stemmer
from sumy.nlp.tokenizers import Tokenizer
from sumy.parsers.plaintext import PlaintextParser
from sumy.summarizers.lsa import LsaSummarizer
from sumy.utils import get_stop_words

from feedmind import config
from feedmind.ingestion import Article

logger = logging.getLogger(__name__)


def init_gemini(api_key: str) -> genai.GenerativeModel:
    """Configure the Gemini SDK and return a GenerativeModel instance."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=config.GEMINI_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            max_output_tokens=150,   # 3 bullets × ~50 tokens — keep it tight
            temperature=0.3,         # low temperature for deterministic, factual output
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
        logger.warning(
            "Empty snippet — skipping summarization: article_id=%s", article.article_id
        )
        return None

    prompt = (
        f"Article title: {article.title}\n\n"
        f"Article content:\n{article.snippet}"
    )

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
    """Extract a 1-sentence summary using the Sumy extractive NLP library."""
    if not article.snippet:
        return article.title

    try:
        parser = PlaintextParser.from_string(article.snippet, Tokenizer("english"))
        stemmer = Stemmer("english")
        summarizer = LsaSummarizer(stemmer)
        summarizer.stop_words = get_stop_words("english")

        # Request exactly 1 sentence
        summary_sentences = summarizer(parser.document, 1)
        if summary_sentences:
            return str(summary_sentences[0])
        else:
            return article.title
    except Exception as exc:
        logger.error("Sumy summarization failed for article_id=%s: %s", article.article_id, exc)
        return article.title
