"""Shared HTTP helpers: one polite client, small retry, no logins, public pages only."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

USER_AGENT = (
    "Mozilla/5.0 (compatible; gtm-xray/0.1; +https://github.com/thoughtpilot99/gtm-xray)"
)
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def client(follow_redirects: bool = True) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=follow_redirects,
        http2=False,
    )


def get(c: httpx.Client, url: str, retries: int = 2, **kw) -> httpx.Response | None:
    """GET with a short backoff. Returns None on network failure (never raises)."""
    for attempt in range(retries + 1):
        try:
            r = c.get(url, **kw)
            if r.status_code in (429, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return r
        except (httpx.HTTPError, ValueError):
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None
    return None


def normalize_domain(value: str) -> str:
    """'https://www.Acme.com/pricing' -> 'acme.com'."""
    v = value.strip().lower()
    if "://" not in v:
        v = "https://" + v
    host = urlparse(v).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def stem(domain: str) -> str:
    """'acme.io' -> 'acme'."""
    return normalize_domain(domain).split(".")[0]


def same_site(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    d = normalize_domain(domain)
    return host == d or host.endswith("." + d)
