"""
notification.py — Telegram Bot API delivery module.

Uses httpx for synchronous HTTP calls to the Telegram sendMessage endpoint.
Messages are formatted in MarkdownV2 with proper escaping.
"""

import logging
import re
import time

import httpx

from feedmind import config
from feedmind.ingestion import Article

logger = logging.getLogger(__name__)

# Characters that must be escaped in Telegram MarkdownV2
# https://core.telegram.org/bots/api#markdownv2-style
_MARKDOWNV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MARKDOWNV2_ESCAPE_RE.sub(r"\\\1", text)


def _category_emoji(category: str) -> str:
    """Return a category badge emoji."""
    return {"academic": "🎓", "industry": "🏢", "cloud": "☁️"}.get(category, "📰")


def _build_message(article: Article, summary: str) -> str:
    """
    Compose the Telegram MarkdownV2 message for a single article.

    Format:
        *Title*

        • Bullet one
        • Bullet two
        • Bullet three

        🔗 [Read More](url)
        📰 Source: arXiv ML  🎓 Academic
    """
    escaped_title  = _escape_md(article.title)
    escaped_source = _escape_md(article.feed_source)
    emoji          = _category_emoji(article.feed_category)
    category_label = article.feed_category.capitalize()

    # summary bullets are already markdown-formatted by Gemini;
    # we trust them to be safe but escape the enclosing metadata.
    return (
        f"*{escaped_title}*\n\n"
        f"{summary}\n\n"
        f"🔗 [Read More]({article.url})\n"
        f"📰 Source: {escaped_source}  {emoji} {_escape_md(category_label)}"
    )


def send_message(
    telegram_token: str,
    chat_id: str,
    article: Article,
    summary: str,
) -> bool:
    """
    Send a single Telegram message for an article.

    Returns True on success, False on failure.
    Sleeps TELEGRAM_MESSAGE_DELAY_S after each call to respect rate limits.
    """
    url     = f"{config.TELEGRAM_API_BASE}/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       _build_message(article, summary),
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }

    try:
        response = httpx.post(url, json=payload, timeout=10.0)
        response.raise_for_status()
        logger.info(
            "Telegram message sent: article_id=%s source=%s",
            article.article_id,
            article.feed_source,
        )
        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "Telegram HTTP error: article_id=%s status=%d body=%s",
            article.article_id,
            exc.response.status_code,
            exc.response.text[:200],
        )
        return False

    except Exception as exc:
        logger.error(
            "Telegram delivery error: article_id=%s error=%s",
            article.article_id,
            exc,
        )
        return False

    finally:
        # Always sleep to respect rate limits, even on failure
        time.sleep(config.TELEGRAM_MESSAGE_DELAY_S)
