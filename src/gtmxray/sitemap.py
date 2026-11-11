"""Content & SEO map: robots.txt -> every sitemap -> page counts per folder.

Also pulls out the pages that reveal GTM intent: comparison / alternative pages (who they
attack), integration pages (partner motion), customer stories (who they sell to), templates
and programmatic pages (SEO engine), and localized folders (regions).
"""

from __future__ import annotations

import gzip
import re
from collections import Counter
from urllib.parse import urlparse

from . import net
from .ledger import INFERRED, Ledger

MAX_SITEMAPS = 60
MAX_URLS = 60000

COMMUNITY = {"t", "forum", "forums", "community", "discussions", "questions", "threads", "u", "users", "profile",
             "c", "tag", "tags", "topic", "topics", "answers"}
COMPARISON = re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:compare|comparison|vs|versus|alternatives?)(?:/|$)"
                        r"|/[a-z0-9]+(?:-[a-z0-9]+){0,2}-vs-[a-z0-9]+(?:-[a-z0-9]+){0,2}/?$"
                        r"|/[a-z0-9]+(?:-[a-z0-9]+){0,2}-alternatives?/?$", re.I)
NON_MARKETING = {"docs", "documentation", "help", "support", "kb", "changelog", "api", "reference", "learn",
                 "academy", "release-notes", "status", "legal", "marketplace", "integrations", "apps"} | COMMUNITY
NOT_A_RIVAL = {"compare", "vs", "versus", "alternatives", "alternative", "enterprise", "growth", "pro", "team",
               "teams", "business", "starter", "free", "basic", "plus", "premium", "ultra", "annual", "monthly",
               "json", "hash", "billing", "raw-billing", "plans", "pricing", "features", "on-demand", "centralised",
               "decentralised", "manual", "automatic", "data-enrichment", "data-enhancement"}
INTENT = {
    "community": r"^/(t|forum|forums|community|discussions|questions)/",
    "integrations": r"/(integrations?|apps|marketplace|connectors?|partners?/apps)/",
    "customers": r"/(customers?|case-stud(y|ies)|stories|success-stories|testimonials)/",
    "templates": r"/(templates?|examples?|gallery|recipes|playbooks?)/",
    "use_cases": r"/(use-cases?|solutions?|industries|for)/",
    "docs": r"/(docs|documentation|help|support|kb|guides?|learn|academy)/",
    "blog": r"/(blog|articles?|resources|insights|news|posts)/",
    "careers": r"/(careers|jobs)/",
    "pricing": r"/pricing",
    "partners": r"/(partners?|affiliates?|referral|experts?|agencies)/?",
    "changelog": r"/(changelog|release-notes|updates|whats-new)",
}
LOCALE = re.compile(r"^/([a-z]{2}(?:-[a-z]{2})?)/", re.I)
LOCALES_OK = {"de", "fr", "es", "it", "pt", "nl", "ja", "ko", "zh", "pt-br", "es-mx", "en-gb", "fr-ca",
              "de-de", "fr-fr", "es-es", "ja-jp", "zh-cn", "ru", "pl", "sv", "tr", "id", "vi", "th", "hi", "ar", "he",
              "uk", "cs", "da", "fi", "no", "nb", "ro", "hu", "el", "zh-tw", "zh-hans", "zh-hant"}


def _fetch(c, url: str) -> str:
    r = net.get(c, url, retries=1)
    if r is None or r.status_code != 200:
        return ""
    data = r.content
    if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except OSError:
            pass
    return data.decode("utf-8", "replace")


def collect(domain: str, led: Ledger) -> dict:
    d = net.normalize_domain(domain)
    with net.client() as c:
        robots = _fetch(c, f"https://{d}/robots.txt")
        sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
        if not sitemaps:
            sitemaps = [f"https://{d}/sitemap.xml", f"https://{d}/sitemap_index.xml"]
        seen: set[str] = set()
        queue = list(dict.fromkeys(sitemaps))
        urls: list[str] = []
        fetched = 0
        while queue and fetched < MAX_SITEMAPS and len(urls) < MAX_URLS:
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            xml = _fetch(c, sm)
            fetched += 1
            if not xml:
                continue
            locs = re.findall(r"<loc>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</loc>", xml, re.S)
            if "<sitemapindex" in xml:
                queue.extend(l.strip() for l in locs)
            else:
                urls.extend(l.strip() for l in locs)

    urls = list(dict.fromkeys(urls))[:MAX_URLS]
    folders = Counter()
    intent: dict[str, list[str]] = {k: [] for k in [*INTENT, "comparison"]}
    locales = Counter()
    for u in urls:
        p = urlparse(u).path or "/"
        lm = LOCALE.match(p)
        if lm and lm.group(1).lower() in LOCALES_OK:
            locales[lm.group(1).lower()] += 1
            p = p[len(lm.group(0)) - 1:]
        seg = p.strip("/").split("/")[0] if p.strip("/") else "(root)"
        folders[seg] += 1
        if seg.lower() not in COMMUNITY and COMPARISON.search(p):
            intent["comparison"].append(u)
        for k, pat in INTENT.items():
            if re.search(pat, p, re.I):
                intent[k].append(u)

    src = f"https://{d}/robots.txt"
    if urls:
        led.add("seo", f"{len(urls)} URLs across {len(seen)} sitemaps", src, "robots.txt -> sitemaps",
                value=len(urls), confidence=0.95)
    for seg, k in folders.most_common(8):
        led.add("seo", f"/{seg}/ holds {k} pages", src, "sitemap folder count", value=k, confidence=0.95)
    comp_targets = Counter()
    for u in intent["comparison"]:
        slug = urlparse(u).path.lower()
        last = slug.rstrip("/").split("/")[-1]
        names: list[str] = []
        if "-vs-" in last:
            names = last.split("-vs-")
        elif re.search(r"-alternatives?$", last):
            names = [re.sub(r"-alternatives?$", "", last)]
        elif re.search(r"/(compare|vs|versus|alternatives?)/", slug):
            names = [last]
        first = slug.strip("/").split("/")[0]
        if first in NON_MARKETING:
            continue  # docs/help/changelog "x-vs-y" pages compare features, not competitors
        for name in names:
            name = re.sub(r"-(comparison|review|reviews|pricing)$", "", name.strip("-"))
            if (name and name != net.stem(d) and name not in NOT_A_RIVAL and not name.isdigit()
                    and name.count("-") <= 2 and not name.startswith(net.stem(d))):
                comp_targets[name] += 1
    if intent["comparison"]:
        led.add("seo", f"{len(intent['comparison'])} comparison / alternative pages", src,
                "URL pattern", value=len(intent["comparison"]), confidence=0.9)
    if comp_targets:
        top = ", ".join(n for n, _ in comp_targets.most_common(8))
        led.add("seo", f"Competitors they target with pages: {top}", src, "comparison slugs",
                kind=INFERRED, value=dict(comp_targets.most_common(20)), confidence=0.75)
    if locales:
        led.add("seo", f"Localized into {len(locales)} languages: {', '.join(sorted(locales))}", src,
                "locale folders", value=dict(locales), confidence=0.9)

    customer_slugs = sorted({_slug_name(u) for u in intent["customers"] if _slug_name(u)})
    integ = sorted({_slug_name(u) for u in intent["integrations"] if _slug_name(u)})
    return {
        "sitemaps_read": len(seen),
        "url_count": len(urls),
        "top_folders": dict(folders.most_common(25)),
        "intent_counts": {k: len(v) for k, v in intent.items()},
        "comparison_targets": dict(comp_targets.most_common(30)),
        "community_pages": len(intent["community"]),
        "comparison_urls": intent["comparison"][:80],
        "locales": dict(locales.most_common()),
        "customer_story_names": customer_slugs[:300],
        "customer_story_urls": intent["customers"][:300],
        "integration_names": integ[:400],
        "has_partner_program": bool(intent["partners"]),
        "has_changelog": bool(intent["changelog"]),
        "changelog_pages": len(intent["changelog"]),
    }


def _slug_name(u: str) -> str:
    parts = [p for p in urlparse(u).path.strip("/").split("/") if p]
    if len(parts) < 2:
        return ""
    s = parts[-1].lower()
    if s in {"customers", "case-studies", "stories", "integrations", "apps", "page", "all"} or s.isdigit():
        return ""
    s = re.sub(r"-(case-study|customer-story|story|integration|case|success)$", "", s)
    return s.replace("-", " ").strip()
