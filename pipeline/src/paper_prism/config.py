"""Runtime configuration, loaded from environment (PRD §3.1)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from .models import LENSES

log = logging.getLogger("paper_prism.config")

# Fallback example profiles. If any of these is used verbatim, we warn — the
# profiles are the product and should be authored deliberately (PRD §7 / P1).
_EXAMPLE_PROFILES = {
    "AIML": "Efficient training and inference for large models.",
    "NLP": "Practical large language models and generative text systems.",
    "CV": "Generative vision: diffusion, text-to-image, text-to-video.",
}


@dataclass
class Config:
    profiles: dict[str, str]
    gemini_api_key: str | None
    gemini_model: str
    sink: str
    window_days: int
    top_k: int
    arxiv_page_size: int
    arxiv_throttle_seconds: float
    arxiv_max_pages: int
    output_dir: str
    firestore_project: str | None = field(default=None)

    @property
    def summaries_enabled(self) -> bool:
        return bool(self.gemini_api_key)


def load_config() -> Config:
    load_dotenv()

    profiles: dict[str, str] = {}
    for lens in LENSES:
        raw = os.getenv(f"PROFILE_{lens}", "").strip()
        if not raw:
            raw = _EXAMPLE_PROFILES[lens]
            log.warning(
                "PROFILE_%s not set — using a placeholder. Ranking quality "
                "depends on authoring a real profile.",
                lens,
            )
        profiles[lens] = raw

    key = os.getenv("GEMINI_API_KEY", "").strip() or None
    if not key:
        log.warning("GEMINI_API_KEY not set — summaries will be written as null.")

    return Config(
        profiles=profiles,
        gemini_api_key=key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        sink=os.getenv("SINK", "local").strip().lower(),
        window_days=int(os.getenv("WINDOW_DAYS", "7")),
        top_k=int(os.getenv("TOP_K", "3")),
        arxiv_page_size=int(os.getenv("ARXIV_PAGE_SIZE", "100")),
        arxiv_throttle_seconds=float(os.getenv("ARXIV_THROTTLE_SECONDS", "3")),
        arxiv_max_pages=int(os.getenv("ARXIV_MAX_PAGES", "10")),
        output_dir=os.getenv("OUTPUT_DIR", "output"),
        firestore_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None,
    )
