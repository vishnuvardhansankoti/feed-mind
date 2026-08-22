"""Where the LLM settings come from, and how the sources are layered.

Precedence, highest first: CLI flag > environment variable > config file >
built-in default. The built-in default matches a stock Ollama install so the
tool summarizes with no config file at all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .errors import ConfigError

CONFIG_ENV_VAR = "WEB_SCRAPER_CONFIG"

CONFIG_SEARCH_PATHS = [
    Path("./scraper-config.json"),
    Path("~/.config/web-page-scraper/config.json").expanduser(),
    Path("~/.web-page-scraper.json").expanduser(),
]

DEFAULT_CONFIG_PATH = CONFIG_SEARCH_PATHS[1]

DEFAULT_PROMPT = (
    "Summarize the following web page in 2 to 3 sentences. "
    "Be factual and specific, cover only what the page actually says, "
    "and write plain prose with no preamble, bullet points or headings."
)

# Step two of the two-step pipeline gets a different instruction: it is
# rewriting a keyword-ranked extract, not reading a whole page.
CONDENSE_PROMPT = (
    "You are an expert editor. Below is a raw, filtered extract of a document - "
    "the highest-scoring sentences, pulled out of order-of-importance and "
    "stitched together. Rewrite it into a cohesive, professional, easy-to-read "
    "summary of 2 to 3 sentences. Do not lose critical facts or data. Reply "
    "with the summary itself and nothing else - no preamble, no lead-in "
    "sentence, and no mention that the input was an extract."
)

DEFAULT_MAX_INPUT_CHARS = 12000

# Extractive pre-filter settings.
DEFAULT_CONDENSE = {
    "enabled": False,
    "select_ratio": 0.25,
    "model": "en_core_web_sm",
    "prompt": None,
}

SUPPORTED_APIS = ("openai", "ollama", "anthropic")

# Every setting a provider can carry, with its fallback value.
BUILTIN_PROVIDER = {
    "api": "openai",
    "base_url": "http://localhost:11434/v1",
    "model": "llama3.2:latest",
    "api_key": "",
    "api_key_env": "",
    "temperature": 0.2,
    "max_tokens": 300,
    "timeout": 120,
    "headers": {},
}

BUILTIN_PROVIDER_NAME = "ollama (built-in default)"

# Environment variable -> provider setting it overrides.
ENV_OVERRIDES = {
    "LLM_API": "api",
    "LLM_BASE_URL": "base_url",
    "LLM_MODEL": "model",
    "LLM_API_KEY": "api_key",
}

PROVIDER_ENV_VAR = "LLM_PROVIDER"

# Text-to-speech settings; None means "leave the engine default alone".
DEFAULT_TTS = {
    "voice": None,
    "rate": None,
    "volume": None,
    "output": None,
}

SAMPLE_CONFIG = {
    "provider": "ollama",
    "prompt": DEFAULT_PROMPT,
    "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
    "condense": {
        "enabled": False,
        "select_ratio": 0.25,
        "model": "en_core_web_sm",
        "prompt": CONDENSE_PROMPT,
    },
    "tts": {
        "voice": "Samantha",
        "rate": 175,
        "volume": 1.0,
        "output": None,
    },
    "providers": {
        "ollama": {
            "api": "openai",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3.2:latest",
            "max_tokens": 300,
        },
        "ollama-native": {
            "api": "ollama",
            "base_url": "http://localhost:11434",
            "model": "llama3.2:latest",
        },
        "openai": {
            "api": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "anthropic": {
            "api": "anthropic",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-5",
            "api_key_env": "ANTHROPIC_API_KEY",
            "max_tokens": 300,
        },
        "groq": {
            "api": "openai",
            "base_url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile",
            "api_key_env": "GROQ_API_KEY",
        },
    },
}


def config_candidates(explicit_path=None):
    """The paths that will be tried, in order."""
    if explicit_path:
        return [Path(explicit_path).expanduser()]
    if os.environ.get(CONFIG_ENV_VAR):
        return [Path(os.environ[CONFIG_ENV_VAR]).expanduser()]
    return list(CONFIG_SEARCH_PATHS)


def load_config(explicit_path=None):
    """Load the first config file that exists, or return {} when there is none."""
    for path in config_candidates(explicit_path):
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                config = json.load(handle)
        except (json.JSONDecodeError, OSError) as error:
            raise ConfigError(f"Bad config at {path}: {error}") from error
        if not isinstance(config, dict):
            raise ConfigError(f"Config at {path} must be a JSON object.")
        config["_path"] = str(path)
        return config

    if explicit_path:
        raise ConfigError(f"No config file at {explicit_path}")
    return {}


def _select_provider(config, requested):
    """Pick the named provider block and merge it onto the built-in defaults."""
    providers = config.get("providers") or {}
    name = requested or os.environ.get(PROVIDER_ENV_VAR) or config.get("provider")

    if name and name in providers:
        return name, dict(BUILTIN_PROVIDER, **providers[name])
    if name:
        known = ", ".join(sorted(providers)) or "none"
        raise ConfigError(
            f"Provider {name!r} is not defined in "
            f"{config.get('_path', 'the config')}. Known: {known}"
        )
    if providers:
        name, block = sorted(providers.items())[0]
        return name, dict(BUILTIN_PROVIDER, **block)
    return BUILTIN_PROVIDER_NAME, dict(BUILTIN_PROVIDER)


def _resolve_api_key(settings, key_env):
    key_env = key_env or settings.get("api_key_env")
    if not key_env or settings.get("api_key"):
        return
    settings["api_key"] = os.environ.get(key_env, "")
    if not settings["api_key"]:
        raise ConfigError(f"Environment variable {key_env} is empty or unset.")


def _validate(settings):
    settings["api"] = (settings.get("api") or "openai").lower()
    if settings["api"] not in SUPPORTED_APIS:
        raise ConfigError(
            f"Unknown api {settings['api']!r}; expected "
            f"{', '.join(SUPPORTED_APIS)}."
        )
    for field in ("base_url", "model"):
        if not settings.get(field):
            raise ConfigError(f"No {field} configured for the LLM.")


def resolve_provider(config, overrides=None):
    """Merge config file, environment and caller overrides into one settings dict.

    `overrides` is a plain dict so this stays independent of argparse; keys are
    provider setting names plus "provider" and "api_key_env".
    """
    overrides = {k: v for k, v in (overrides or {}).items() if v}

    name, settings = _select_provider(config, overrides.pop("provider", None))
    key_env = overrides.pop("api_key_env", None)

    for env_var, field in ENV_OVERRIDES.items():
        if os.environ.get(env_var):
            settings[field] = os.environ[env_var]
    settings.update(overrides)

    _resolve_api_key(settings, key_env)
    settings["name"] = name
    _validate(settings)
    return settings


def prompt_for(config, override=None):
    return override or config.get("prompt") or DEFAULT_PROMPT


def max_input_chars_for(config):
    return int(config.get("max_input_chars", DEFAULT_MAX_INPUT_CHARS))


def condense_settings(config, overrides=None):
    """Merge the config's "condense" block with caller overrides."""
    settings = dict(DEFAULT_CONDENSE, **(config.get("condense") or {}))
    settings.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return settings


def tts_settings(config, overrides=None):
    """Merge the config's "tts" block with caller overrides (overrides win)."""
    settings = dict(DEFAULT_TTS, **(config.get("tts") or {}))
    settings.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return settings


def write_sample_config(path=None):
    """Write SAMPLE_CONFIG to `path` (or the default location)."""
    target = Path(path).expanduser() if path else DEFAULT_CONFIG_PATH
    if target.exists():
        raise ConfigError(f"{target} already exists - not overwriting it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(SAMPLE_CONFIG, indent=2) + "\n", encoding="utf-8")
    return target
