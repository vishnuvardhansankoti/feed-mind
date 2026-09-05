"""The YAML loader's validation rules.

Every ConfigError here is a failure that would otherwise be invisible: a
service with no feeds, or feeds with no category, looks exactly like "nothing
new today" in the run summary. Failing the cold start instead is the whole
point of validating on load.
"""

import pytest
from feedmind_core import serviceconfig

VALID = """
service: test-svc
kind: rss
summarize: sumy
deliver_telegram: true
feeds:
  - name: Example
    url: https://example.com/feed
    category: industry
"""


def _write(tmp_path, text):
    p = tmp_path / "feeds.yaml"
    p.write_text(text)
    return p


def test_loads_a_valid_config(tmp_path):
    cfg = serviceconfig.load(_write(tmp_path, VALID))
    assert cfg.service == "test-svc"
    assert cfg.kind == serviceconfig.KIND_RSS
    assert cfg.deliver_telegram is True
    assert cfg.categories == ("industry",)


def test_flags_default_to_off(tmp_path):
    """Both defaults are the quiet ones.

    A config that forgets deliver_telegram produces articles the notifier
    ignores, rather than an unannounced Telegram flood.
    """
    cfg = serviceconfig.load(_write(tmp_path, """
service: quiet
feeds:
  - {name: A, url: "https://a.com/f", category: cloud}
"""))
    assert cfg.deliver_telegram is False
    assert cfg.content_ready is False
    assert cfg.kind == serviceconfig.KIND_RSS
    assert cfg.summarize == serviceconfig.SUMMARIZE_SUMY


@pytest.mark.parametrize("body,fragment", [
    ("feeds: []\nservice: s", "non-empty list"),
    ("service: s\nkind: carrier-pigeon\nfeeds: [{name: A, url: 'http://a', category: cloud}]", "kind must be"),
    ("service: s\nsummarize: vibes\nfeeds: [{name: A, url: 'http://a', category: cloud}]", "summarize must be"),
    ("kind: rss\nfeeds: [{name: A, url: 'http://a', category: cloud}]", "'service' is required"),
    ("service: s\nfeeds: [{name: A, url: 'http://a'}]", "needs a 'category'"),
    ("service: s\nfeeds: [{name: A}]", "needs both 'name' and 'url'"),
    ("- just\n- a\n- list", "must be a mapping"),
])
def test_rejects_malformed_configs(tmp_path, body, fragment):
    with pytest.raises(serviceconfig.ConfigError) as exc:
        serviceconfig.load(_write(tmp_path, body))
    assert fragment in str(exc.value)


def test_youtube_feeds_need_no_category(tmp_path):
    """Videos are never grouped into a digest section, so nothing needs one."""
    cfg = serviceconfig.load(_write(tmp_path, """
service: yt
kind: youtube
summarize: none
feeds:
  - {name: Chan, url: "https://www.youtube.com/feeds/videos.xml?channel_id=X"}
"""))
    assert cfg.feeds[0].category == ""
    assert cfg.categories == ()


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(serviceconfig.ConfigError, match="config not found"):
        serviceconfig.load(tmp_path / "nope.yaml")


def test_invalid_yaml_is_a_config_error(tmp_path):
    with pytest.raises(serviceconfig.ConfigError, match="not valid YAML"):
        serviceconfig.load(_write(tmp_path, "service: [unclosed"))


def test_categories_preserves_first_seen_order(tmp_path):
    """Order drives nothing today, but a set would make it unstable if it did."""
    cfg = serviceconfig.load(_write(tmp_path, """
service: s
feeds:
  - {name: A, url: "https://a", category: cloud}
  - {name: B, url: "https://b", category: academic}
  - {name: C, url: "https://c", category: cloud}
"""))
    assert cfg.categories == ("cloud", "academic")
