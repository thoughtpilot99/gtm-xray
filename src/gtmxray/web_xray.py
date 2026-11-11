"""Funnel X-Ray: reverse-engineer the public website the way a browser sees it.

Structure, scripts, network observations and screenshots, pointed at GTM questions:
- Network: every third-party host the public pages call -> tools, experiment platforms, ad pixels
- JS bundles: analytics event names, feature-flag / experiment keys, pricing constants,
  integration names, all read from the JavaScript the site ships to every visitor
- Funnel: the public steps from homepage -> signup / demo form (fields asked = qualification)
- Screenshots: hero, pricing, signup, for the report and social cards

Static fallback (no browser): fetch the HTML and its <script src> bundles with httpx.
Optional HAR import: analyze a capture YOU recorded of your OWN session (e.g. your own trial).
Never logs in, never submits forms, never calls private APIs.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from . import fp, net
from .ledger import INFERRED, Ledger

EVENT_PATTERNS = [
    r"""(?:track|capture|logEvent|analytics\.track|posthog\.capture|mixpanel\.track|amplitude\.track|gtag\(\s*['"]event['"])\s*\(\s*['"]([A-Za-z][\w .:/-]{2,60})['"]""",
    r"""event(?:Name)?\s*[:=]\s*['"]((?:[a-z]+_){1,5}[a-z]+)['"]""",
]
FLAG_PATTERNS = [
    r"""(?:useFeatureFlag|isFeatureEnabled|getFeatureFlag|useFlag|variation|useGate|checkGate|getExperiment|useExperiment)\s*\(\s*['"]([\w.:/-]{3,60})['"]""",
]
EXPERIMENT_VENDORS = {
    "launchdarkly": "LaunchDarkly", "statsig": "Statsig", "growthbook": "GrowthBook", "optimizely": "Optimizely",
    "vwo.com": "VWO", "split.io": "Split", "eppo": "Eppo", "posthog": "PostHog", "abtasty": "AB Tasty",
    "convert.com": "Convert", "unbounce": "Unbounce", "mutiny": "Mutiny",
}
FUNNEL_WORDS = re.compile(r"\b(sign ?up|get started|start (?:for )?free|try (?:it )?free|book a demo|request a demo|"
                          r"get a demo|contact sales|talk to sales|download)\b", re.I)
MAX_BUNDLES = 25
MAX_BUNDLE_BYTES = 6_000_000


def _scan_js(js: str, out: dict) -> None:
    for p in EVENT_PATTERNS:
        for m in re.finditer(p, js):
            out["events"][m.group(1)] += 1
    for p in FLAG_PATTERNS:
        for m in re.finditer(p, js):
            out["flags"][m.group(1)] += 1
    low = js.lower()
    for k, v in EXPERIMENT_VENDORS.items():
        if k in low:
            out["experiment_vendors"].add(v)
    for tl in fp.load()["jd_tools"]:
        if len(tl) > 4 and re.search(rf"['\"]{re.escape(tl)}['\"]", js):
            out["integration_strings"][tl] += 1
    if "sourceMappingURL=" in js:
        out["source_maps"] += 1


def static_scan(domain: str, led: Ledger, paths=("", "/pricing", "/signup", "/demo")) -> dict:
    d = net.normalize_domain(domain)
    out = {"events": Counter(), "flags": Counter(), "experiment_vendors": set(), "integration_strings": Counter(),
           "source_maps": 0, "third_party_hosts": Counter(), "bundles_read": 0, "funnel": [], "forms": []}
    seen_js: set[str] = set()
    with net.client() as c:
        for path in paths:
            r = net.get(c, f"https://{d}{path}", retries=0)
            if r is None or r.status_code >= 400:
                continue
            tree = HTMLParser(r.text)
            for s in tree.css("script[src]"):
                src = urljoin(str(r.url), s.attributes.get("src") or "")
                host = urlparse(src).hostname or ""
                if host and not net.same_site(src, d):
                    out["third_party_hosts"][host] += 1
                if src not in seen_js and len(seen_js) < MAX_BUNDLES:
                    seen_js.add(src)
            for s in tree.css("script:not([src])"):
                _scan_js(s.text() or "", out)
            for a in tree.css("a[href]"):
                t = a.text(strip=True)
                if FUNNEL_WORDS.search(t or ""):
                    out["funnel"].append({"page": path or "/", "cta": t[:40],
                                          "to": urljoin(str(r.url), a.attributes.get("href") or "")})
            for f in tree.css("form"):
                fields = [i.attributes.get("name") or i.attributes.get("placeholder") or i.attributes.get("type")
                          for i in f.css("input, select, textarea")]
                fields = [x for x in fields if x and x not in ("hidden", "submit")]
                if fields:
                    out["forms"].append({"page": path or "/", "fields": fields[:20]})
        for src in seen_js:
            r = net.get(c, src, retries=0)
            if r is None or r.status_code != 200 or len(r.content) > MAX_BUNDLE_BYTES:
                continue
            out["bundles_read"] += 1
            _scan_js(r.text, out)
    return _finish(d, out, led, "static")


def browser_scan(domain: str, led: Ledger, shots_dir: Path | None = None) -> dict:
    """Headless Chromium: real network log + screenshots. Needs `uv sync --extra render` +
    `uv run playwright install chromium`. Falls back to static_scan if unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return static_scan(domain, led)
    d = net.normalize_domain(domain)
    out = {"events": Counter(), "flags": Counter(), "experiment_vendors": set(), "integration_strings": Counter(),
           "source_maps": 0, "third_party_hosts": Counter(), "bundles_read": 0, "funnel": [], "forms": [],
           "screenshots": []}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900}, user_agent=net.USER_AGENT)
        js_bodies: list[str] = []

        def on_resp(resp):
            u = resp.url
            host = urlparse(u).hostname or ""
            if host and not net.same_site(u, d):
                out["third_party_hosts"][host] += 1
            if resp.request.resource_type == "script" and len(js_bodies) < MAX_BUNDLES:
                try:
                    body = resp.text()
                    if len(body) <= MAX_BUNDLE_BYTES:
                        js_bodies.append(body)
                except Exception:
                    pass

        pg.on("response", on_resp)
        for path in ("", "/pricing"):
            try:
                pg.goto(f"https://{d}{path}", wait_until="networkidle", timeout=45000)
            except Exception:
                continue
            if shots_dir:
                shots_dir.mkdir(parents=True, exist_ok=True)
                f = shots_dir / f"{(path.strip('/') or 'home')}.png"
                pg.screenshot(path=str(f), full_page=False)
                out["screenshots"].append(str(f.name))
            for a in pg.query_selector_all("a"):
                try:
                    t = (a.inner_text() or "").strip()
                except Exception:
                    continue
                if FUNNEL_WORDS.search(t):
                    out["funnel"].append({"page": path or "/", "cta": t[:40], "to": a.get_attribute("href") or ""})
        b.close()
    for js in js_bodies:
        out["bundles_read"] += 1
        _scan_js(js, out)
    return _finish(d, out, led, "browser")


def har_scan(har_path: Path, domain: str, led: Ledger) -> dict:
    """Analyze a HAR you recorded of your own session (e.g. your own free trial signup)."""
    d = net.normalize_domain(domain)
    har = json.loads(Path(har_path).read_text(encoding="utf-8"))
    out = {"events": Counter(), "flags": Counter(), "experiment_vendors": set(), "integration_strings": Counter(),
           "source_maps": 0, "third_party_hosts": Counter(), "bundles_read": 0, "funnel": [], "forms": [],
           "first_party_paths": Counter()}
    for e in har.get("log", {}).get("entries", []):
        u = e.get("request", {}).get("url", "")
        host = urlparse(u).hostname or ""
        if net.same_site(u, d):
            out["first_party_paths"][re.sub(r"/[0-9a-f-]{8,}", "/:id", urlparse(u).path)] += 1
        elif host:
            out["third_party_hosts"][host] += 1
        txt = (e.get("response", {}).get("content", {}) or {}).get("text") or ""
        if "javascript" in (e.get("response", {}).get("content", {}).get("mimeType") or "") and txt:
            out["bundles_read"] += 1
            _scan_js(txt, out)
        post = (e.get("request", {}).get("postData") or {}).get("text") or ""
        for m in re.finditer(r'"(?:event|name)"\s*:\s*"([A-Za-z][\w .:/-]{2,60})"', post):
            out["events"][m.group(1)] += 1
    res = _finish(d, out, led, "har", source=str(Path(har_path).name))
    res["first_party_paths"] = dict(out["first_party_paths"].most_common(40))
    return res


def _finish(d: str, out: dict, led: Ledger, mode: str, source: str = "") -> dict:
    src = source or f"https://{d}"
    t = fp.load()["page_source"]
    tools_from_hosts = sorted({tool for host in out["third_party_hosts"] for pat, (tool, _) in t.items()
                               if pat.split("/")[0].lower() in host.lower()})
    for v in sorted(out["experiment_vendors"]):
        led.add("product", f"Runs experiments / flags with {v}", src, f"{mode} JS scan", confidence=0.7)
    if out["events"]:
        top = ", ".join(e for e, _ in out["events"].most_common(8))
        led.add("product", f"{len(out['events'])} analytics event names in public JS (e.g. {top})", src,
                f"{mode} JS scan", value=dict(out["events"].most_common(60)), confidence=0.8)
    if out["flags"]:
        led.add("product", f"{len(out['flags'])} feature-flag / experiment keys in public JS", src, f"{mode} JS scan",
                value=dict(out["flags"].most_common(60)), confidence=0.75)
    for f in out["forms"]:
        led.add("funnel", f"Form on {f['page']} asks: {', '.join(f['fields'][:8])}", f"https://{d}{f['page']}",
                "form field read", kind=INFERRED, confidence=0.8)
    return {
        "mode": mode,
        "bundles_read": out["bundles_read"],
        "third_party_hosts": dict(out["third_party_hosts"].most_common(60)),
        "tools_from_network": tools_from_hosts,
        "experiment_vendors": sorted(out["experiment_vendors"]),
        "analytics_events": dict(out["events"].most_common(80)),
        "feature_flags": dict(out["flags"].most_common(80)),
        "integration_strings": dict(out["integration_strings"].most_common(40)),
        "source_maps_exposed": out["source_maps"],
        "funnel_ctas": out["funnel"][:40],
        "forms": out["forms"][:10],
        "screenshots": out.get("screenshots", []),
        "limitations": [
            "Public pages only; logged-in product surfaces are not visible.",
            "Event and flag names show instrumentation exists, not how often it fires.",
            "Minified bundles can rename strings; absence of a match is not proof of absence.",
        ],
    }
