"""
summarization.py — Gemini 2.0 Flash API integration for article summarization.
"""

import logging
from typing import Optional

import google.generativeai as genai

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


def summarize(model: genai.GenerativeModel, article: Article) -> Optional[str]:
    """
    Call the Gemini API to produce a 3-bullet summary of the article.

    Args:
        model: Initialised GenerativeModel.
        article: Article to summarize.

    Returns:
        Markdown-formatted summary string, or None on failure.
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
