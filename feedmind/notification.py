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


def build_category_messages(category: str, items: list[tuple[Article, str]]) -> list[str]:
    """
    Build a list of MarkdownV2 Telegram messages for a given category.
    Splits into multiple messages if the length exceeds config.TELEGRAM_MAX_MESSAGE_LENGTH.
    """
    if not items:
        return []

    emoji = _category_emoji(category)
    header = f"*{emoji} {_escape_md(category.capitalize())} News*\n\n"

    messages = []
    current_message = header

    for article, summary in items:
        escaped_title = _escape_md(article.title)

        if summary and summary != article.title:
            escaped_summary = _escape_md(summary)
            item_text = (
                f"• *{escaped_title}* — {escaped_summary}\n"
                f"  🔗 [Read More]({article.url}) \\| 📰 {_escape_md(article.feed_source)}\n\n"
            )
        else:
            item_text = (
                f"• *{escaped_title}*\n"
                f"  🔗 [Read More]({article.url}) \\| 📰 {_escape_md(article.feed_source)}\n\n"
            )

        if len(current_message) + len(item_text) > config.TELEGRAM_MAX_MESSAGE_LENGTH:
            messages.append(current_message.strip())
            current_message = f"*{emoji} {_escape_md(category.capitalize())} News \\(Cont\\.\\)*\n\n"

        current_message += item_text

    if current_message.strip() and current_message != header.strip():
        messages.append(current_message.strip())

    return messages


def send_message(
    telegram_token: str,
    chat_id: str,
    text: str,
) -> bool:
    """
    Send a raw text Telegram message.

    Returns True on success, False on failure.
    Sleeps TELEGRAM_MESSAGE_DELAY_S after each call to respect rate limits.
    """
    url     = f"{config.TELEGRAM_API_BASE}/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    try:
        response = httpx.post(url, json=payload, timeout=10.0)
        response.raise_for_status()
        logger.info("Telegram message sent successfully. length=%d", len(text))
        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "Telegram HTTP error: status=%d body=%s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return False

    except Exception as exc:
        logger.error("Telegram delivery error: %s", exc)
        return False

    finally:
        # Always sleep to respect rate limits, even on failure
        time.sleep(config.TELEGRAM_MESSAGE_DELAY_S)
