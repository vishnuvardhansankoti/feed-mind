"""Talking to the model.

Three wire formats are supported. Each is an adapter with two jobs: build the
request, and pull the text out of the response. Adding a fourth provider means
writing one adapter and registering it in ADAPTERS - nothing else changes.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from .config import DEFAULT_MAX_INPUT_CHARS, DEFAULT_PROMPT
from .errors import LLMError

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)

# Small models like to announce themselves before answering. Strip one leading
# line of the form "Here is a rewritten summary of the text:".
PREAMBLE_RE = re.compile(
    r"^\s*(here\s+(is|are)|here's|sure|certainly|okay|of course|below\s+is)\b"
    r"[^\n:]{0,120}:\s*\n+",
    re.I,
)
ERROR_DETAIL_CHARS = 500
SHAPE_DETAIL_CHARS = 300


def post_json(url, payload, headers, timeout):
    """POST JSON, return the parsed JSON reply, raise LLMError on any failure."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:ERROR_DETAIL_CHARS].strip()
        raise LLMError(f"{url} returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise LLMError(f"Could not reach {url}: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise LLMError(f"{url} returned a non-JSON response: {error}") from error


def _unexpected(data):
    return LLMError(f"Unexpected response shape: {str(data)[:SHAPE_DETAIL_CHARS]}")


class Adapter:
    """Base class for a provider wire format."""

    name = ""

    @staticmethod
    def _messages(prompt, text):
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

    def build(self, settings, prompt, text):
        """Return (url, payload, headers)."""
        raise NotImplementedError

    def parse(self, data):
        """Return the reply text from a decoded JSON response."""
        raise NotImplementedError


class OpenAIAdapter(Adapter):
    """OpenAI, Ollama's /v1 endpoint, Groq, vLLM, LM Studio, OpenRouter..."""

    name = "openai"

    def build(self, settings, prompt, text):
        base = settings["base_url"].rstrip("/")
        if not base.endswith("/v1") and "/v1/" not in base:
            base += "/v1"
        headers = dict(settings.get("headers") or {})
        if settings.get("api_key"):
            headers.setdefault("Authorization", f"Bearer {settings['api_key']}")
        payload = {
            "model": settings["model"],
            "messages": self._messages(prompt, text),
            "temperature": float(settings.get("temperature", 0.2)),
            "max_tokens": int(settings.get("max_tokens", 300)),
            "stream": False,
        }
        return f"{base}/chat/completions", payload, headers

    def parse(self, data):
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise _unexpected(data) from error


class OllamaAdapter(Adapter):
    """Ollama's native /api/chat endpoint."""

    name = "ollama"

    def build(self, settings, prompt, text):
        base = settings["base_url"].rstrip("/")
        headers = dict(settings.get("headers") or {})
        if settings.get("api_key"):
            headers.setdefault("Authorization", f"Bearer {settings['api_key']}")
        payload = {
            "model": settings["model"],
            "messages": self._messages(prompt, text),
            "stream": False,
            "options": {
                "temperature": float(settings.get("temperature", 0.2)),
                "num_predict": int(settings.get("max_tokens", 300)),
            },
        }
        return f"{base}/api/chat", payload, headers

    def parse(self, data):
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as error:
            raise _unexpected(data) from error


class AnthropicAdapter(Adapter):
    """The Anthropic Messages API."""

    name = "anthropic"
    version = "2023-06-01"

    def build(self, settings, prompt, text):
        if not settings.get("api_key"):
            raise LLMError("The anthropic api needs an api_key (set api_key_env).")
        base = settings["base_url"].rstrip("/")
        headers = dict(settings.get("headers") or {})
        headers.setdefault("x-api-key", settings["api_key"])
        headers.setdefault("anthropic-version", self.version)
        payload = {
            "model": settings["model"],
            "max_tokens": int(settings.get("max_tokens", 300)),
            "temperature": float(settings.get("temperature", 0.2)),
            "system": prompt,
            "messages": [{"role": "user", "content": text}],
        }
        return f"{base}/v1/messages", payload, headers

    def parse(self, data):
        try:
            return "".join(
                part.get("text", "")
                for part in data["content"]
                if part.get("type") == "text"
            )
        except (KeyError, TypeError) as error:
            raise _unexpected(data) from error


ADAPTERS = {
    adapter.name: adapter
    for adapter in (OpenAIAdapter(), OllamaAdapter(), AnthropicAdapter())
}


def call_llm(settings, prompt, text):
    """Send one request and return the model's reply."""
    adapter = ADAPTERS.get(settings["api"])
    if adapter is None:
        raise LLMError(f"No adapter for api {settings['api']!r}.")

    url, payload, headers = adapter.build(settings, prompt, text)
    data = post_json(url, payload, headers, float(settings.get("timeout", 120)))
    return adapter.parse(data)


def clip(text, max_chars):
    """Trim `text` to `max_chars` on a word boundary."""
    if not max_chars or len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " ..."


def summarize(text, settings, prompt=DEFAULT_PROMPT,
              max_input_chars=DEFAULT_MAX_INPUT_CHARS):
    """Return a short summary of `text`, or raise LLMError."""
    if not text.strip():
        raise LLMError("Nothing to summarize.")

    reply = call_llm(settings, prompt, clip(text, max_input_chars)) or ""
    # Reasoning models (deepseek-r1, qwen3...) prepend a think block.
    reply = THINK_BLOCK_RE.sub("", reply)
    reply = PREAMBLE_RE.sub("", reply.lstrip())
    return re.sub(r"\n{3,}", "\n\n", reply).strip()
