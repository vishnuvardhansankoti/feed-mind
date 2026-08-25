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


# Header metadata per feed category: (badge emoji, display title).
#
# The title is spelled out rather than derived because `str.capitalize()` does
# not survive the separators used in `config.RSS_FEEDS` category codes — they
# are inconsistent by design (`open-source` hyphenates, `top_stories`
# underscores), and capitalize() would emit "Open-source" and "Top_stories".
# The underscore is then MarkdownV2-escaped, so it reaches Telegram as a
# literal "Top\_stories".
_CATEGORY_META = {
    "academic": ("🎓", "Academic News"),
    "industry": ("🏢", "Industry News"),
    "cloud": ("☁️", "Cloud News"),
    "open-source": ("💻", "Open Source"),
    "top_stories": ("🗞️", "Top Stories"),
}


def _title_from_code(category: str) -> str:
    """Fallback display title: 'top_stories' -> 'Top Stories'."""
    return re.sub(r"[_\-]+", " ", category).strip().title() or "News"


def _category_header(category: str) -> str:
    """
    Return the '<emoji> <Title>' header text for a feed category code.

    A category with no entry in `_CATEGORY_META` still renders sanely, so
    adding a feed to `config.RSS_FEEDS` under a new category does not require a
    change here — it just gets the generic badge.
    """
    emoji, title = _CATEGORY_META.get(category, ("📰", _title_from_code(category)))
    return f"{emoji} {_escape_md(title)}"


def build_category_messages(category: str, items: list[tuple[Article, str]]) -> list[str]:
    """
    Build a list of MarkdownV2 Telegram messages for a given category.
    Splits into multiple messages if the length exceeds config.TELEGRAM_MAX_MESSAGE_LENGTH.
    """
    if not items:
        return []

    header_text = _category_header(category)
    header = f"*{header_text}*\n\n"

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
            current_message = f"*{header_text} \\(Cont\\.\\)*\n\n"

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
    url = f"{config.TELEGRAM_API_BASE}/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
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
