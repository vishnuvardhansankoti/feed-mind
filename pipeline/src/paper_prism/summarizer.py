"""Stage-2 summarization via Gemini (PRD §3.2 step 4, §3.4).

Summarize-only — no re-ranking. Any failure (missing key, rate limit, safety
block, malformed response) returns None so the paper is written with
`summary: null` (PRD §3.3 / Branch 8b). Uses the AI Studio REST endpoint
directly to avoid an SDK dependency.
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("paper_prism.summarizer")

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_PROMPT = (
    "In exactly 2 sentences, state this paper's key innovation. "
    "Use only the provided title and abstract; do not speculate or add "
    "information not present.\n\n"
    "Title: {title}\n\nAbstract: {abstract}"
)


class Summarizer:
    def __init__(self, api_key: str | None, model: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def summarize(self, title: str, abstract: str) -> str | None:
        if not self.api_key:
            return None

        prompt = _PROMPT.format(title=title, abstract=abstract)
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200},
        }
        try:
            resp = requests.post(
                _ENDPOINT.format(model=self.model),
                params={"key": self.api_key},
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            return _extract_text(resp.json())
        except requests.RequestException as exc:
            log.warning("Gemini summary failed (%s) — writing null", type(exc).__name__)
            return None


def _extract_text(payload: dict) -> str | None:
    candidates = payload.get("candidates") or []
    if not candidates:
        # e.g. blocked by safety filters -> promptFeedback with no candidates
        return None
    parts = candidates[0].get("content", {}).get("parts") or []
    text = " ".join(p.get("text", "") for p in parts).strip()
    return text or None
