"""Displacement Engine: who uses the competitor, and why they might leave.

Free public evidence only:
1. Job posts at OTHER companies that ask for experience with the competitor's product
   (a company hiring 'Clay experience required' runs Clay). The agent finds candidate URLs
   with web search (queries from `search_queries`); `verify_job_urls` fetches each one and
   keeps it only if the tool really appears in the text.
2. Hacker News 'Who is hiring' comments naming the tool (Algolia API, no key).
3. The competitor's own customer wall and case studies (from pagesource + sitemap).
Every account carries its evidence URLs and a 'why now' line.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from . import net
from .ledger import INFERRED, Ledger

ATS_HOSTS = ["boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
             "apply.workable.com", "jobs.smartrecruiters.com"]


def search_queries(tool: str) -> list[str]:
    q = [f'"{tool}" site:{h}' for h in ATS_HOSTS]
    q += [f'"experience with {tool}" job', f'"{tool}" "nice to have" job description',
          f'"{tool}" required "account executive" OR "sdr" OR "revops" OR "growth" job']
    return q


def _company_from_url(u: str) -> str:
    p = urlparse(u)
    parts = [x for x in p.path.split("/") if x]
    if any(h in (p.hostname or "") for h in ATS_HOSTS) and parts:
        return parts[0].replace("-", " ").replace("_", " ").title()
    host = net.normalize_domain(u)
    return host.split(".")[0].title() if host else ""


def verify_job_urls(tool: str, urls: list[str], led: Ledger, competitor_domain: str = "") -> list[dict]:
    pat = re.compile(rf"(?<![A-Za-z]){re.escape(tool)}(?![A-Za-z])", re.I)
    out = []
    comp_stem = net.stem(competitor_domain) if competitor_domain else ""
    with net.client() as c:
        for u in dict.fromkeys(urls):
            r = net.get(c, u, retries=1)
            if r is None or r.status_code != 200:
                continue
            tree = HTMLParser(r.text)
            for bad in tree.css("script, style, noscript"):
                bad.decompose()
            text = re.sub(r"\s+", " ", tree.body.text(separator=" ") if tree.body else "")
            m = pat.search(text)
            if not m:
                continue
            company = _company_from_url(u)
            if comp_stem and comp_stem in company.lower().replace(" ", ""):
                continue  # the competitor's own job post, not a customer
            title = tree.css_first("h1").text(strip=True) if tree.css_first("h1") else ""
            snip = text[max(0, m.start() - 140): m.end() + 140]
            row = {"company": company, "job_title": title, "url": u, "evidence": snip,
                   "source": "job post names the tool", "why_now": f"Hiring a '{title}' who will run {tool}"}
            out.append(row)
            led.add("displacement", f"{company} job post requires {tool}", u, "job description text match",
                    value=snip, confidence=0.85)
    return out


def hn_hiring(tool: str, led: Ledger, months: int = 12) -> list[dict]:
    since = int((dt.datetime.now() - dt.timedelta(days=30 * months)).timestamp())
    url = "https://hn.algolia.com/api/v1/search_by_date"
    params = {"query": f'"{tool}"', "tags": "comment", "numericFilters": f"created_at_i>{since}",
              "hitsPerPage": 200}
    with net.client() as c:
        r = net.get(c, url, params=params)
    if r is None or r.status_code != 200:
        return []
    out = []
    pat = re.compile(rf"(?<![A-Za-z]){re.escape(tool)}(?![A-Za-z])", re.I)
    for h in r.json().get("hits", []):
        story = (h.get("story_title") or "").lower()
        if "who is hiring" not in story and "who's hiring" not in story:
            continue
        txt = HTMLParser(h.get("comment_text") or "").text(separator=" ")
        if not pat.search(txt):
            continue
        first = txt.split("|")[0].strip()[:60]
        if tool.lower() in first.lower()[: len(tool) + 12]:
            continue  # the competitor's own hiring post, not a customer
        link = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        out.append({"company": first, "job_title": "", "url": link, "evidence": txt[:280],
                    "source": "HN Who is hiring", "why_now": f"Hiring and lists {tool} in their stack"})
        led.add("displacement", f"{first} lists {tool} in an HN hiring post", link, "HN Algolia search",
                value=txt[:200], confidence=0.7)
    return out


def from_customer_wall(pages: dict, sitemap: dict, led: Ledger, competitor: str) -> list[dict]:
    rows = []
    where = {}
    for pg in (pages.get("pages") or {}).values():
        for n in pg.get("logos", []):
            where.setdefault(n, pg.get("url", ""))
    for name in pages.get("logos", [])[:200]:
        rows.append({"company": name, "job_title": "", "url": where.get(name) or f"https://{competitor}",
                     "evidence": "logo on competitor site", "source": "competitor customer wall",
                     "why_now": f"Named {competitor} customer"})
    for name in sitemap.get("customer_story_names", [])[:300]:
        url = next((u for u in sitemap.get("customer_story_urls", [])
                    if name.replace(" ", "-") in u.lower()), f"https://{competitor}")
        rows.append({"company": name.title(), "job_title": "", "url": url, "evidence": "customer story page",
                     "source": "competitor case study", "why_now": f"Public {competitor} case study"})
    if rows:
        led.add("displacement", f"{len(rows)} named accounts from {competitor}'s own site",
                f"https://{competitor}", "logo wall + case study slugs", kind=INFERRED, value=len(rows),
                confidence=0.7)
    return rows


def merge(rows: list[dict]) -> list[dict]:
    """One row per company, evidence stacked; more independent sources = higher rank."""
    acc: dict[str, dict] = {}
    for r in rows:
        key = re.sub(r"[^a-z0-9]", "", r["company"].lower())
        if not key or len(key) < 2:
            continue
        a = acc.setdefault(key, {"company": r["company"], "sources": [], "evidence_urls": [], "why_now": [],
                                 "job_titles": []})
        if r["source"] not in a["sources"]:
            a["sources"].append(r["source"])
        if r["url"] and r["url"] not in a["evidence_urls"]:
            a["evidence_urls"].append(r["url"])
        if r["why_now"] not in a["why_now"]:
            a["why_now"].append(r["why_now"])
        if r.get("job_title"):
            a["job_titles"].append(r["job_title"])
    out = list(acc.values())
    for a in out:
        a["score"] = len(a["sources"]) * 3 + len(a["evidence_urls"]) + (2 if a["job_titles"] else 0)
    return sorted(out, key=lambda a: -a["score"])


def clay_csv(accounts: list[dict], path: Path, competitor: str, buyer_titles: list[str]) -> Path:
    """Clay-ready import: one row per account, columns map 1:1 to a Clay table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Company Name", "Company Domain", "Competitor Used", "Evidence Sources", "Evidence URL",
                    "Why Now", "Hiring For", "Target Titles", "Priority Score"])
        for a in accounts:
            w.writerow([a["company"], a.get("domain", ""), competitor, "; ".join(a["sources"]),
                        (a["evidence_urls"] or [""])[0], " | ".join(a["why_now"]),
                        "; ".join(a["job_titles"][:3]), "; ".join(buyer_titles), a["score"]])
    return path
