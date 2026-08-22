"""Exception hierarchy shared by every module in the package."""

from __future__ import annotations


class ScraperError(Exception):
    """Base class - catching this catches everything we raise on purpose."""


class FetchError(ScraperError):
    """The page could not be downloaded."""


class ConfigError(ScraperError):
    """The LLM config is missing, malformed or incomplete."""


class LLMError(ScraperError):
    """Something went wrong talking to the model."""


class CondenseError(ScraperError):
    """The extractive pre-filter is unavailable or failed."""


class SpeechError(ScraperError):
    """Text-to-speech is unavailable or failed."""
