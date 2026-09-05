"""Env-driven configuration, including the RETENTION_DAYS TTL knob."""

import paper_prism.config as config_mod
from paper_prism.config import load_config


def _clear_env(monkeypatch):
    for key in (
        "PROFILE_AIML",
        "PROFILE_NLP",
        "PROFILE_CV",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "SINK",
        "WINDOW_DAYS",
        "TOP_K",
        "RETENTION_DAYS",
        "ARXIV_PAGE_SIZE",
        "ARXIV_THROTTLE_SECONDS",
        "ARXIV_MAX_PAGES",
        "OUTPUT_DIR",
        "GOOGLE_CLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)
    # load_config() calls load_dotenv(); neutralize it so a local .env can't leak in.
    monkeypatch.setattr(config_mod, "load_dotenv", lambda *a, **k: None)


def test_defaults(monkeypatch):
    _clear_env(monkeypatch)
    cfg = load_config()
    assert cfg.retention_days == 45
    assert cfg.window_days == 7
    assert cfg.top_k == 3
    assert cfg.sink == "local"
    assert cfg.gemini_api_key is None
    assert cfg.summaries_enabled is False
    # unset profiles fall back to placeholders (one per lens)
    assert set(cfg.profiles) == {"AIML", "NLP", "CV"}


def test_env_overrides(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RETENTION_DAYS", "90")
    monkeypatch.setenv("TOP_K", "5")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("PROFILE_AIML", "my aiml interests")
    cfg = load_config()
    assert cfg.retention_days == 90
    assert cfg.top_k == 5
    assert cfg.summaries_enabled is True
    assert cfg.profiles["AIML"] == "my aiml interests"
