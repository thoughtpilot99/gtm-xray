"""Page-source forensics: martech stack, GTM motion and the public customer wall.

Reads the homepage, pricing page and customers page as any browser would. Finds:
- tools embedded in the source (visitor ID, chat, meeting routers, ad pixels, analytics)
- motion signals: self-serve CTAs vs 'book a demo', free plan, enterprise tier, partner program
- customer logos and names shown publicly
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from . import fp, net
from .ledger import INFERRED, Ledger

PAGES = {"home": "", "pricing": "/pricing", "customers": "/customers", "enterprise": "/enterprise",
         "partners": "/partners", "affiliates": "/affiliates"}
SELF_SERVE = r"\b(start (?:for )?free|try (?:it )?(?:for )?free|get started(?: for free)?|sign up|download(?: for)?|" \
             r"create (?:a )?free account|start building|try now)\b"
SALES_LED = r"\b(book a demo|request a demo|get a demo|talk to sales|contact sales|schedule a demo|talk to us)\b"
LOGO_HINT = re.compile(r"(logo|customer|client|trusted|brand|partner)", re.I)
BAD_ALT = re.compile(r"^(logo|image|icon|img|arrow|close|menu|avatar|photo|picture|background|hero|"
                     r"screenshot|\d+|.{0,1})$|background|illustration|abstract|pattern|gradient|"
                     r"decorative|placeholder|headshot|portrait", re.I)


def _logos(tree: HTMLParser, own: str) -> list[str]:
    names: list[str] = []
    for img in tree.css("img, svg[aria-label]"):
        alt = (img.attributes.get("alt") or img.attributes.get("aria-label") or "").strip()
        src = img.attributes.get("src") or ""
        cls = " ".join(filter(None, [img.attributes.get("class"), src]))
        parent_txt = ""
        p = img.parent
        for _ in range(4):
            if p is None:
                break
            parent_txt += " " + (p.attributes.get("class") or "") + " " + (p.attributes.get("id") or "")
            p = p.parent
        if not alt or BAD_ALT.match(alt):
            continue
        if LOGO_HINT.search(cls + parent_txt) or re.search(r"\blogo\b", alt, re.I):
            n = re.sub(r"\s*(logo|logotype|wordmark|icon)\s*$", "", alt, flags=re.I).strip(" -|")
            looks_like_person = re.search(r"\s(-|–|at|@|,)\s|\b(ceo|cto|founder|head of|vp|director)\b", n, re.I)
            if n and own not in n.lower() and len(n) <= 40 and not looks_like_person:
                names.append(n)
    return list(dict.fromkeys(names))


def collect(domain: str, led: Ledger) -> dict:
    d = net.normalize_domain(domain)
    t = fp.load()["page_source"]
    pages: dict[str, dict] = {}
    tools: dict[str, dict] = {}
    with net.client() as c:
        for key, path in PAGES.items():
            url = f"https://{d}{path}"
            r = net.get(c, url, retries=1)
            if r is None or r.status_code >= 400:
                continue
            if key != "home" and net.normalize_domain(str(r.url)) == d and (r.url.path in ("", "/")):
                continue  # redirected to homepage, page does not exist
            html = r.text
            tree = HTMLParser(html)
            for pat, (tool, cat) in t.items():
                if pat.lower() in html.lower():
                    tools.setdefault(tool, {"category": cat, "pages": [], "pattern": pat})
                    if key not in tools[tool]["pages"]:
                        tools[tool]["pages"].append(key)
            text_tree = HTMLParser(html)
            for bad in text_tree.css("script, style, noscript"):
                bad.decompose()
            text = re.sub(r"\s+", " ", text_tree.body.text(separator=" ") if text_tree.body else "")
            links = [urljoin(str(r.url), a.attributes.get("href") or "") for a in tree.css("a[href]")]
            pages[key] = {
                "url": str(r.url),
                "self_serve_ctas": len(re.findall(SELF_SERVE, text, re.I)),
                "sales_ctas": len(re.findall(SALES_LED, text, re.I)),
                "logos": _logos(tree, net.stem(d)),
                "chars": len(text),
                "text_sample": text[:4000],
                "prices": sorted({p for p in re.findall(r"(?:\$|€|£)\s?(\d{1,5}(?:[.,]\d{2})?)", text)},
                                 key=lambda x: float(x.replace(",", ".")))[:20],
                "has_free_plan": bool(re.search(r"(\bfree (plan|tier|forever)\b|\$0(?![\d.,])|\bhobby\b)",
                                                text, re.I)),
                "has_enterprise_tier": bool(re.search(r"\benterprise\b", text, re.I)),
                "contact_sales_on_pricing": key == "pricing" and bool(re.search(SALES_LED, text, re.I)),
                "mentions_soc2": bool(re.search(r"\bsoc ?2\b", text, re.I)),
                "outbound_links": sorted({l for l in links if l.startswith("http") and not net.same_site(l, d)})[:60],
            }

    for tool, info in tools.items():
        led.add("stack", f"{tool} ({info['category']}) embedded on {', '.join(info['pages'])} page",
                pages.get(info["pages"][0], {}).get("url", f"https://{d}"), "page source fingerprint",
                value=info["pattern"], confidence=0.85)

    logos = []
    for key in ("home", "customers", "enterprise", "pricing"):
        logos += pages.get(key, {}).get("logos", [])
    logos = list(dict.fromkeys(logos))
    if logos:
        led.add("customers", f"{len(logos)} customer logos shown publicly", pages.get("home", {}).get("url", ""),
                "img alt text in logo sections", value=logos[:40], confidence=0.75)

    ss = sum(p.get("self_serve_ctas", 0) for p in pages.values())
    sl = sum(p.get("sales_ctas", 0) for p in pages.values())
    cats = Counter(i["category"] for i in tools.values())
    motion = {
        "self_serve_ctas": ss,
        "sales_ctas": sl,
        "free_plan": any(p.get("has_free_plan") for p in pages.values()),
        "enterprise_tier": pages.get("pricing", {}).get("has_enterprise_tier", False),
        "contact_sales_on_pricing": pages.get("pricing", {}).get("contact_sales_on_pricing", False),
        "visitor_id_tools": [k for k, v in tools.items() if v["category"] == "visitor-id"],
        "abm_tools": [k for k, v in tools.items() if v["category"] == "abm"],
        "meeting_routing": [k for k, v in tools.items() if v["category"] == "meeting-routing"],
        "ad_pixels": [k for k, v in tools.items() if v["category"] == "paid-ads"],
        "partner_page": "partners" in pages,
        "affiliate_page": "affiliates" in pages,
    }
    lean = "product-led" if ss > sl * 1.5 else "sales-led" if sl > ss * 1.5 else "hybrid"
    led.add("motion", f"Website CTA mix leans {lean}: {ss} self-serve vs {sl} sales CTAs",
            pages.get("home", {}).get("url", f"https://{d}"), "CTA count across key pages", kind=INFERRED,
            value={"self_serve": ss, "sales": sl}, confidence=0.7)
    if motion["visitor_id_tools"]:
        led.add("motion", f"De-anonymizes website visitors with {', '.join(motion['visitor_id_tools'])}",
                pages["home"]["url"], "page source fingerprint", kind=INFERRED, confidence=0.75)
    return {"pages": pages, "tools": tools, "tool_categories": dict(cats), "motion": motion,
            "motion_lean": lean, "logos": logos}
