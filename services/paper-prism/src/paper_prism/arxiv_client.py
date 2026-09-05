"""arXiv ingestion (PRD §3.2 step 1).

Uses the legacy Atom XML query API — throttled, paginated, retried. Papers are
kept only when their *primary* arXiv category belongs to the requested lens,
which resolves cross-listing duplication (PRD §7 / Branch 7b).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import feedparser
import requests

from .models import Candidate

log = logging.getLogger("paper_prism.arxiv")

_API_URL = "http://export.arxiv.org/api/query"
_USER_AGENT = "paper-prism/0.1 (weekly research digest; contact via repo)"


class ArxivClient:
    def __init__(
        self,
        page_size: int = 100,
        throttle_seconds: float = 3.0,
        max_pages: int = 10,
        max_retries: int = 4,
    ) -> None:
        self.page_size = page_size
        self.throttle_seconds = throttle_seconds
        self.max_pages = max_pages
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def fetch_lens(
        self, source_categories: tuple[str, ...], window_days: int
    ) -> list[Candidate]:
        """Fetch candidates submitted within `window_days` for one lens.

        Results are sorted by submission date (newest first), so we stop paging
        once we cross the cutoff.
        """
        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        source_set = set(source_categories)
        query = " OR ".join(f"cat:{c}" for c in source_categories)

        candidates: list[Candidate] = []
        for page in range(self.max_pages):
            start = page * self.page_size
            entries = self._fetch_page(query, start)
            if not entries:
                break

            crossed_cutoff = False
            for entry in entries:
                submitted = _parse_dt(entry.get("published"))
                if submitted is None:
                    continue
                if submitted < cutoff:
                    crossed_cutoff = True
                    continue

                primary = _primary_category(entry)
                if primary not in source_set:
                    # Cross-listed here but "owned" by another lens — skip.
                    continue

                candidates.append(_to_candidate(entry, primary, submitted))

            if crossed_cutoff:
                # Newest-first ordering means everything beyond here is older.
                break

        log.info(
            "arXiv: %d candidates within %dd for %s",
            len(candidates),
            window_days,
            ",".join(source_categories),
        )
        return candidates

    # -- internals ---------------------------------------------------------

    def _fetch_page(self, query: str, start: int) -> list[dict]:
        params = {
            "search_query": query,
            "start": start,
            "max_results": self.page_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = requests.get(
                    _API_URL,
                    params=params,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=30,
                )
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
                # arXiv occasionally returns an empty feed transiently; retry a
                # couple of times before accepting "genuinely empty".
                if not parsed.entries and start == 0 and attempt < self.max_retries:
                    raise _TransientEmpty()
                return parsed.entries
            except (requests.RequestException, _TransientEmpty) as exc:
                backoff = min(2 ** attempt, 30)
                log.warning(
                    "arXiv fetch attempt %d/%d failed (%s); backing off %ds",
                    attempt,
                    self.max_retries,
                    type(exc).__name__,
                    backoff,
                )
                time.sleep(backoff)
        raise RuntimeError(f"arXiv fetch failed after {self.max_retries} attempts")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.throttle_seconds:
            time.sleep(self.throttle_seconds - elapsed)
        self._last_request_at = time.monotonic()


class _TransientEmpty(Exception):
    pass


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        # feedparser gives RFC3339 like "2026-08-10T09:00:00Z"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _primary_category(entry: dict) -> str:
    primary = entry.get("arxiv_primary_category")
    if primary and primary.get("term"):
        return primary["term"]
    # Fallback: first tag term.
    tags = entry.get("tags") or []
    return tags[0]["term"] if tags else ""


def _to_candidate(entry: dict, primary: str, submitted: datetime) -> Candidate:
    arxiv_id = _short_id(entry.get("id", ""))
    return Candidate(
        title=_clean(entry.get("title", "")),
        abstract=_clean(entry.get("summary", "")),
        arxiv_id=arxiv_id,
        url=entry.get("id", "") or f"https://arxiv.org/abs/{arxiv_id}",
        primary_category=primary,
        submitted=submitted,
    )


def _short_id(url: str) -> str:
    # "http://arxiv.org/abs/2508.01234v1" -> "2508.01234"
    tail = url.rstrip("/").split("/abs/")[-1]
    return tail.split("v")[0] if tail else url


def _clean(text: str) -> str:
    return " ".join(text.split())
