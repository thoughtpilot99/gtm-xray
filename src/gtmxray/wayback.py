"""Positioning & pricing time machine (Internet Archive CDX API).

First capture of every year for the homepage and the pricing page. From each: page title,
meta description, H1/H2 headlines, CTAs, and every price on the pricing page. Then a
year-over-year diff: when did the headline change, when did 'AI' enter the pitch, when did
the cheapest plan move.
"""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from . import net
from .ledger import Ledger

CDX = "https://web.archive.org/cdx/search/cdx"
# Plan prices only: a currency amount followed by a billing period ("$20/mo", "$134 per month").
# Per-credit or per-unit prices ("$0.10 per credit") are ignored.
PRICE = re.compile(r"(?:\$|€|£)\s?(\d{1,4}(?:[.,]\d{2})?)\s*(?:usd|eur)?\s*(?:/|per|a)\s*"
                   r"(?:mo\b|month|user\s*/\s*mo|seat\s*/\s*mo|user per month|seat per month)", re.I)
CTA = re.compile(r"\b(start (?:for )?free|try (?:it )?(?:for )?free|get started|sign up|book a demo|"
                 r"request a demo|talk to sales|contact sales|get a demo|download|join (?:the )?waitlist)\b", re.I)


def snapshots(url: str, start_year: int = 2015) -> list[tuple[str, str]]:
    params = {"url": url, "output": "json", "fl": "timestamp,original,statuscode",
              "filter": "statuscode:200", "collapse": "timestamp:4", "from": str(start_year)}
    with net.client() as c:
        r = net.get(c, CDX, params=params, retries=2)
    if r is None or r.status_code != 200:
        return []
    try:
        rows = r.json()
    except ValueError:
        return []
    return [(row[0], row[1]) for row in rows[1:]]


def extract(html: str) -> dict:
    tree = HTMLParser(html)
    for bad in tree.css("script, style, noscript"):
        bad.decompose()
    title = (tree.css_first("title").text(strip=True) if tree.css_first("title") else "")
    md = tree.css_first('meta[name="description"]')
    desc = md.attributes.get("content", "") if md else ""
    h1 = [n.text(strip=True) for n in tree.css("h1")][:3]
    h2 = [n.text(strip=True) for n in tree.css("h2")][:8]
    body = tree.body.text(separator=" ") if tree.body else ""
    body = re.sub(r"\s+", " ", body)
    prices = sorted({float(p.replace(",", ".")) for p in PRICE.findall(body)})
    ctas = sorted({m.lower() for m in CTA.findall(body)})
    return {"title": title, "description": desc, "h1": h1, "h2": h2, "prices": prices[:30],
            "ctas": ctas, "mentions_ai": bool(re.search(r"\b(ai|a\.i\.|artificial intelligence|agent(s|ic)?)\b",
                                                         f"{title} {desc} {' '.join(h1)}", re.I))}


def timeline(domain: str, led: Ledger, pages: tuple[str, ...] = ("", "/pricing")) -> dict:
    d = net.normalize_domain(domain)
    out: dict[str, list[dict]] = {}
    with net.client() as c:
        for page in pages:
            key = page or "/"
            out[key] = []
            for ts, orig in snapshots(f"{d}{page}"):
                raw = f"https://web.archive.org/web/{ts}id_/{orig}"
                r = net.get(c, raw, retries=1)
                if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
                    continue
                e = extract(r.text)
                e.update({"year": ts[:4], "timestamp": ts,
                          "archive_url": f"https://web.archive.org/web/{ts}/{orig}"})
                out[key].append(e)

    changes = []
    home = out.get("/", [])
    for prev, cur in zip(home, home[1:]):
        a = (prev["h1"][:1] or [prev["title"]])[0]
        b = (cur["h1"][:1] or [cur["title"]])[0]
        if a and b and a.strip().lower() != b.strip().lower() and d not in b.lower():
            changes.append({"year": cur["year"], "from": a, "to": b, "url": cur["archive_url"]})
            led.add("positioning", f"{cur['year']}: homepage headline changed to \"{b[:90]}\"",
                    cur["archive_url"], "Wayback first capture of year", value={"from": a, "to": b},
                    confidence=0.9)
    first_ai = next((s for s in home if s["mentions_ai"]), None)
    if first_ai and home and not home[0]["mentions_ai"]:
        led.add("positioning", f"AI entered the homepage pitch in {first_ai['year']}", first_ai["archive_url"],
                "Wayback keyword scan", value=first_ai["year"], confidence=0.8)
    price_moves = []
    pr = [s for s in out.get("/pricing", []) if s["prices"]]
    for prev, cur in zip(pr, pr[1:]):
        lo_a = min([p for p in prev["prices"] if p > 0] or [0])
        lo_b = min([p for p in cur["prices"] if p > 0] or [0])
        if lo_a and lo_b and lo_a != lo_b:
            price_moves.append({"year": cur["year"], "from": lo_a, "to": lo_b, "url": cur["archive_url"]})
            led.add("pricing", f"{cur['year']}: cheapest listed paid price moved {lo_a:g} -> {lo_b:g}",
                    cur["archive_url"], "Wayback pricing page", value={"from": lo_a, "to": lo_b}, confidence=0.75)
    limitations = ["Only the first capture per year is read, so short-lived experiments are missed."]
    if len(home) > 2:
        def words(snaps):
            return set(re.findall(r"[a-z]{4,}", " ".join((s["title"] + " " + " ".join(s["h1"])).lower()
                                                         for s in snaps)))
        if not ((words(home[:2]) & words(home[-2:])) - {net.stem(d)}):
            limitations.append(f"Captures from {home[0]['year']} share no words with today's pitch: the domain may "
                               "have belonged to a different company then. Check before quoting old history.")
    return {"limitations": limitations, "snapshots": out, "headline_changes": changes, "price_moves": price_moves,
            "first_ai_year": first_ai["year"] if first_ai else None,
            "first_capture_year": home[0]["year"] if home else None}
