"""Downloading pages: headers, transparent decompression, charset sniffing."""

from __future__ import annotations

import gzip
import re
import urllib.error
import urllib.request
import zlib

from .errors import FetchError

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.I)


def normalize_url(url):
    """Add a scheme when the user typed a bare host."""
    return url if re.match(r"^https?://", url, re.I) else "https://" + url


def _decompress(raw, encoding):
    encoding = (encoding or "").lower()
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def fetch(url, timeout=20):
    """Download `url` and return its decoded HTML.

    Raises FetchError for anything the network or server does wrong.
    """
    request = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _decompress(response.read(), response.headers.get("Content-Encoding"))
            charset = response.headers.get_content_charset()
    except urllib.error.HTTPError as error:
        raise FetchError(f"HTTP {error.code} fetching {url}: {error.reason}") from error
    except (urllib.error.URLError, OSError) as error:
        raise FetchError(f"Could not fetch {url}: {error}") from error

    if not charset:
        match = CHARSET_RE.search(raw[:4096])
        charset = match.group(1).decode("ascii", "ignore") if match else "utf-8"
    return raw.decode(charset, errors="replace")
