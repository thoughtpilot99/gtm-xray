"""Render report.html, compare.html, social-card PNGs and the leak-score badge."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import net
from .ledger import Ledger, latest_runs

TPL = Path(__file__).with_name("templates")


def _load(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _embed(obj) -> str:
    # Safe inside <script type="application/json">
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def render(domain: str, root: Path, png: bool = False, audit: bool = False) -> Path:
    d = net.normalize_domain(domain)
    runs = latest_runs(root, d, 1)
    if not runs:
        raise SystemExit(f"No run for {d}. Run: xray collect {d}")
    rd = runs[0]
    facts = _load(rd / "facts.json", {})
    # keep the page light: snapshots are big and only the derived timeline is shown
    if facts.get("wayback"):
        facts["wayback"] = {k: v for k, v in facts["wayback"].items() if k != "snapshots"}
    if facts.get("pagesource"):
        for p in facts["pagesource"].get("pages", {}).values():
            p.pop("text_sample", None)
            p.pop("outbound_links", None)
    data = {
        "facts": facts,
        "analysis": _load(rd / "analysis.json", {}),
        "accounts": _load(rd / "accounts.json", []),
        "ledger": [asdict(r) for r in Ledger.read(rd / "ledger.jsonl").rows],
        "audit": audit,
    }
    html = (TPL / "report.html").read_text(encoding="utf-8").replace("__DATA__", _embed(data))
    out = rd / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"report -> {out}")
    if png:
        cards(out)
    return out


def cards(report: Path) -> list[Path]:
    """Screenshot each 1200x675 social card. Needs: uv sync --extra render && uv run playwright install chromium"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("PNG cards need Playwright: uv sync --extra render && uv run playwright install chromium")
        return []
    outs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 675}, device_scale_factor=2)
        pg.goto(report.resolve().as_uri() + "?cards=1")
        pg.wait_for_timeout(800)
        for el in pg.query_selector_all(".social"):
            f = report.parent / f"{el.get_attribute('id')}.png"
            el.screenshot(path=str(f))
            outs.append(f)
        b.close()
    print(f"{len(outs)} social cards -> {report.parent}")
    return outs


def badge(domain: str, root: Path) -> Path:
    d = net.normalize_domain(domain)
    rd = latest_runs(root, d, 1)[0]
    score = _load(rd / "facts.json", {}).get("leak_score", {}).get("score", 0)
    color = "#dc2626" if score >= 70 else "#d97706" if score >= 40 else "#059669"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="196" height="20" role="img" aria-label="GTM leak score: {score}/100">
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="196" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="128" height="20" fill="#0d1117"/><rect x="128" width="68" height="20" fill="{color}"/><rect width="196" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
<text x="64" y="14">GTM leak score</text><text x="162" y="14">{score}/100</text></g></svg>"""
    out = rd / "leak-badge.svg"
    out.write_text(svg, encoding="utf-8")
    return out


def compare(domains: list[str], root: Path) -> Path:
    rows = []
    for dom in domains:
        d = net.normalize_domain(dom)
        runs = latest_runs(root, d, 1)
        if not runs:
            continue
        f = _load(runs[0] / "facts.json", {})
        h, s, o = f.get("hiring") or {}, f.get("sitemap") or {}, f.get("outbound") or {}
        rows.append({
            "domain": d,
            "open_roles": h.get("open_roles", 0),
            "gtm_share": h.get("gtm_share", 0),
            "sales_roles": h.get("sales_roles", {}),
            "enterprise_roles": (h.get("by_segment") or {}).get("Enterprise", 0),
            "gtm_by_region": h.get("gtm_by_region", {}),
            "sending_domains": len([x for x in o.get("owned_sending_domains", [])
                                    if x.get("kind", "").startswith("lookalike") and x.get("wired_for_email", True)]),
            "sending_tools": o.get("sending_tools_detected", []),
            "capacity_high": (f.get("outbound_capacity") or {}).get("monthly_high", 0),
            "sitemap_urls": s.get("url_count", 0),
            "comparison_pages": (s.get("intent_counts") or {}).get("comparison", 0),
            "comparison_targets": list((s.get("comparison_targets") or {}).keys())[:8],
            "integrations": (s.get("intent_counts") or {}).get("integrations", 0),
            "tools": sorted(set((f.get("dns") or {}).get("tools_from_txt", [])) |
                            set(((f.get("pagesource") or {}).get("tools") or {}).keys())),
            "radar": f.get("motion_radar", {}),
            "leak": (f.get("leak_score") or {}).get("score", 0),
            "motion_lean": (f.get("pagesource") or {}).get("motion_lean", ""),
        })
    html = (TPL / "compare.html").read_text(encoding="utf-8").replace("__DATA__", _embed(rows))
    out = root / ("compare-" + "-vs-".join(r["domain"].split(".")[0] for r in rows) + ".html")
    out.write_text(html, encoding="utf-8")
    print(f"compare -> {out}")
    return out
