"""xray: the deterministic half of GTM X-Ray.

Collectors gather SEEN facts into runs/<domain>/<date>/. The Claude Code agents read those
files and write analysis.json. `xray render` turns both into the report.

  xray collect acme.com            # all collectors in parallel -> facts.json + ledger.jsonl
  xray verify-jobs Clay urls.txt     # Displacement Engine: keep job posts that really name the tool
  xray hn Clay                       # HN 'Who is hiring' mentions of a tool
  xray accounts acme.com           # merge displacement evidence -> accounts.json + clay.csv
  xray render acme.com             # report.html (+ social cards with --png)
  xray diff acme.com               # compare the two latest runs (watch mode)
  xray badge acme.com              # leak score SVG badge
  xray queries Clay                  # web-search queries for the Displacement Engine
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
from pathlib import Path

from . import ats, displacement, dns_probe, net, pagesource, scoring, sitemap, wayback, web_xray
from .ledger import Ledger, latest_runs, run_dir

ROOT = Path.cwd() / "runs"
# ledger modules each collector writes (used to merge partial re-runs)
MODULES = {"hiring": {"hiring", "roadmap"}, "dns": {"stack"}, "outbound": {"outbound"}, "sitemap": {"seo"},
           "pagesource": {"stack", "customers", "motion"}, "wayback": {"positioning", "pricing"},
           "web": {"product", "funnel"}}


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _load(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def collect(domain: str, root: Path, skip: set[str], browser: bool = False) -> Path:
    d = net.normalize_domain(domain)
    out = run_dir(root, d)
    jobs = {
        "hiring": ats.analyze,
        "dns": dns_probe.stack_from_dns,
        "outbound": dns_probe.outbound_forensics,
        "sitemap": sitemap.collect,
        "pagesource": pagesource.collect,
        "wayback": wayback.timeline,
        "web": (lambda dom, led: web_xray.browser_scan(dom, led, out / "shots")) if browser else web_xray.static_scan,
    }
    jobs = {k: v for k, v in jobs.items() if k not in skip}
    facts: dict = {"domain": d, "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "errors": {}}
    master = Ledger()
    timings = {}

    def run(name, fn):
        led = Ledger()
        t0 = time.time()
        try:
            res = fn(d, led)
        except Exception as e:  # a failed collector must not kill the run
            res = None
            facts["errors"][name] = f"{type(e).__name__}: {e}"
        timings[name] = round(time.time() - t0, 1)
        return name, res, led

    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        for name, res, led in ex.map(lambda kv: run(*kv), jobs.items()):
            facts[name] = res
            master.extend(led)
            print(f"  [{name:<10}] {'ok' if res is not None else 'FAILED'} in {timings[name]}s", file=sys.stderr)

    if skip:  # partial re-run: keep today's results for the collectors we skipped
        prev = _load(out / "facts.json", {})
        for k in skip:
            if k in prev:
                facts[k] = prev[k]
        rerun = set().union(*(MODULES[k] for k in jobs))
        for r in Ledger.read(out / "ledger.jsonl").rows:
            if r.module not in rerun and not any(x.id == r.id for x in master.rows):
                master.rows.append(r)
    facts["outbound_capacity"] = scoring.outbound_capacity(facts.get("outbound") or {}, master, d)
    facts["motion_radar"] = scoring.motion_radar(facts)
    facts["leak_score"] = scoring.leak_score(facts)
    facts["timings_s"] = timings
    # Keep raw roles in their own file: big, but the agents need them.
    roles = (facts.get("hiring") or {}).pop("roles", None)
    if roles is not None:
        _dump(out / "roles.json", roles)
    _dump(out / "facts.json", facts)
    # Re-collecting the same day keeps evidence the agents added (verified quotes, review themes, ...).
    collector_modules = {r.module for r in master.rows} | {"stack", "outbound", "hiring", "roadmap", "seo",
                                                          "customers", "motion", "positioning", "pricing",
                                                          "product", "funnel"}
    for r in Ledger.read(out / "ledger.jsonl").rows:
        if r.module not in collector_modules or r.method.endswith("verified"):
            if not any(x.id == r.id for x in master.rows):
                master.rows.append(r)
    master.write(out / "ledger.jsonl")
    print(f"\n{d}: {len(master.rows)} evidence rows -> {out}", file=sys.stderr)
    return out


def accounts(domain: str, root: Path, tool: str | None, titles: list[str], exclude: list[str] | None = None) -> Path:
    d = net.normalize_domain(domain)
    runs = latest_runs(root, d, 1)
    if not runs:
        sys.exit(f"No run for {d}. Run: xray collect {d}")
    rd = runs[0]
    facts = _load(rd / "facts.json", {})
    led = Ledger.read(rd / "ledger.jsonl")
    rows = list(_load(rd / "displacement_raw.json", []))
    rows += displacement.from_customer_wall(facts.get("pagesource") or {}, facts.get("sitemap") or {}, led, d)
    drop = {x.strip().lower() for x in (exclude or []) if x.strip()}
    merged = [a for a in displacement.merge(rows) if a["company"].lower() not in drop]
    _dump(rd / "accounts.json", merged)
    displacement.clay_csv(merged, rd / "clay-import.csv", tool or d, titles)
    led.write(rd / "ledger.jsonl")
    print(f"{len(merged)} accounts -> {rd / 'clay-import.csv'}", file=sys.stderr)
    return rd


def fetch_text(url: str) -> str:
    """Public page -> readable text. Raw Wayback captures (id_) avoid the archive toolbar."""
    import re

    from selectolax.lexbor import LexborHTMLParser

    m = re.match(r"https?://web\.archive\.org/web/(\d+)/(.+)", url)
    if m:
        url = f"https://web.archive.org/web/{m.group(1)}id_/{m.group(2)}"
    with net.client() as c:
        r = net.get(c, url)
    if r is None:
        return f"FETCH FAILED: {url}"
    if "html" not in r.headers.get("content-type", "html"):
        return r.text
    t = LexborHTMLParser(r.text)
    for bad in t.css("script, style, noscript, svg"):
        bad.decompose()
    title = t.css_first("title").text(strip=True) if t.css_first("title") else ""
    body = re.sub(r"\s+", " ", t.body.text(separator=" ") if t.body else "")
    return f"URL: {url}\nSTATUS: {r.status_code}\nTITLE: {title}\n\n{body}"


def diff(domain: str, root: Path) -> dict:
    d = net.normalize_domain(domain)
    runs = latest_runs(root, d, 2)
    if len(runs) < 2:
        return {"domain": d, "changes": [], "note": "Need two runs to diff. Run collect again next week."}
    new, old = (_load(r / "facts.json", {}) for r in runs)
    ch = []

    def cmp(label, a, b):
        if a != b:
            ch.append({"what": label, "before": a, "after": b})

    hn, ho = new.get("hiring") or {}, old.get("hiring") or {}
    cmp("Open roles", ho.get("open_roles"), hn.get("open_roles"))
    for k in set(hn.get("sales_roles", {})) | set(ho.get("sales_roles", {})):
        cmp(f"Open {k} roles", ho.get("sales_roles", {}).get(k, 0), hn.get("sales_roles", {}).get(k, 0))
    od = {x["domain"] for x in (old.get("outbound") or {}).get("owned_sending_domains", [])}
    nd = {x["domain"] for x in (new.get("outbound") or {}).get("owned_sending_domains", [])}
    if nd - od:
        ch.append({"what": "New sending domains", "before": sorted(od), "after": sorted(nd - od)})
    ot = set((old.get("pagesource") or {}).get("tools", {}))
    nt = set((new.get("pagesource") or {}).get("tools", {}))
    if nt ^ ot:
        ch.append({"what": "Website tools", "before": sorted(ot - nt), "after": sorted(nt - ot)})
    oc = set((old.get("sitemap") or {}).get("comparison_targets", {}))
    nc = set((new.get("sitemap") or {}).get("comparison_targets", {}))
    if nc - oc:
        ch.append({"what": "New comparison-page targets", "before": [], "after": sorted(nc - oc)})
    cmp("Sitemap URLs", (old.get("sitemap") or {}).get("url_count"), (new.get("sitemap") or {}).get("url_count"))
    op = (old.get("pagesource") or {}).get("pages", {}).get("pricing", {}).get("prices")
    npr = (new.get("pagesource") or {}).get("pages", {}).get("pricing", {}).get("prices")
    cmp("Prices on pricing page", op, npr)
    oldt = {r["url"] for r in _load(runs[1] / "roles.json", [])}
    newroles = [r for r in _load(runs[0] / "roles.json", []) if r["url"] not in oldt]
    if newroles:
        ch.append({"what": "New job posts", "before": None,
                   "after": [f"{r['title']} ({r['location']})" for r in newroles[:25]]})
    res = {"domain": d, "from": runs[1].name, "to": runs[0].name, "changes": ch}
    _dump(runs[0] / "diff.json", res)
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="xray", description="GTM X-Ray collectors")
    ap.add_argument("--root", default=str(ROOT), help="runs folder (default ./runs)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("domain"); c.add_argument("--skip", default="")
    c.add_argument("--browser", action="store_true", help="headless Chromium: network log + screenshots")
    hr = sub.add_parser("har", help="analyze a HAR you recorded of your own session")
    hr.add_argument("domain"); hr.add_argument("har_file")
    st = sub.add_parser("setup", help="register GTM X-Ray with Claude Code / Codex / Cursor / Gemini")
    st.add_argument("--agents", default="claude"); st.add_argument("--yes", action="store_true")
    sub.add_parser("mcp", help="run the MCP server (stdio)")
    v = sub.add_parser("verify-jobs"); v.add_argument("tool"); v.add_argument("urls_file")
    v.add_argument("--competitor", required=True)
    h = sub.add_parser("hn"); h.add_argument("tool"); h.add_argument("--competitor", required=True)
    a = sub.add_parser("accounts"); a.add_argument("domain"); a.add_argument("--tool")
    a.add_argument("--titles", default="Head of Growth;VP Sales;RevOps Lead;GTM Engineer")
    a.add_argument("--exclude", default="", help="';'-separated names the verifier cut (investors, partners, noise)")
    r = sub.add_parser("render"); r.add_argument("domain"); r.add_argument("--png", action="store_true")
    r.add_argument("--audit", action="store_true", help="agency audit styling")
    sub.add_parser("diff").add_argument("domain")
    b = sub.add_parser("badge"); b.add_argument("domain")
    q = sub.add_parser("queries"); q.add_argument("tool")
    fe = sub.add_parser("fetch", help="print a public page as text (works for web.archive.org)")
    fe.add_argument("url"); fe.add_argument("--max", type=int, default=12000)
    n = sub.add_parser("notify"); n.add_argument("domain")
    cm = sub.add_parser("compare"); cm.add_argument("domains", nargs="+")
    args = ap.parse_args(argv)
    root = Path(args.root)

    if args.cmd == "collect":
        collect(args.domain, root, {s for s in args.skip.split(",") if s}, args.browser)
    elif args.cmd == "har":
        d = net.normalize_domain(args.domain)
        rd = latest_runs(root, d, 1)[0]
        led = Ledger.read(rd / "ledger.jsonl")
        res = web_xray.har_scan(Path(args.har_file), d, led)
        _dump(rd / "har.json", res)
        led.write(rd / "ledger.jsonl")
        print(json.dumps({k: res[k] for k in ("bundles_read", "experiment_vendors", "tools_from_network")}, indent=2))
    elif args.cmd == "setup":
        from . import setup
        setup.run([a.strip() for a in args.agents.split(",") if a.strip()], assume_yes=args.yes)
    elif args.cmd == "mcp":
        from . import mcp_server
        mcp_server.main()
    elif args.cmd == "verify-jobs":
        d = net.normalize_domain(args.competitor)
        rd = latest_runs(root, d, 1)[0]
        led = Ledger.read(rd / "ledger.jsonl")
        urls = [u.strip() for u in Path(args.urls_file).read_text().splitlines() if u.strip().startswith("http")]
        rows = displacement.verify_job_urls(args.tool, urls, led, d)
        prev = _load(rd / "displacement_raw.json", [])
        _dump(rd / "displacement_raw.json", prev + rows)
        led.write(rd / "ledger.jsonl")
        print(json.dumps({"checked": len(urls), "confirmed": len(rows),
                          "companies": sorted({x["company"] for x in rows})}, indent=2))
    elif args.cmd == "hn":
        d = net.normalize_domain(args.competitor)
        rd = latest_runs(root, d, 1)[0]
        led = Ledger.read(rd / "ledger.jsonl")
        rows = displacement.hn_hiring(args.tool, led)
        _dump(rd / "displacement_raw.json", _load(rd / "displacement_raw.json", []) + rows)
        led.write(rd / "ledger.jsonl")
        print(json.dumps({"hn_mentions": len(rows), "companies": [x["company"] for x in rows]}, indent=2))
    elif args.cmd == "accounts":
        accounts(args.domain, root, args.tool, [t for t in args.titles.split(";") if t], args.exclude.split(";"))
    elif args.cmd == "render":
        from . import render
        render.render(args.domain, root, png=args.png, audit=args.audit)
    elif args.cmd == "diff":
        print(json.dumps(diff(args.domain, root), indent=2, default=str))
    elif args.cmd == "badge":
        from . import render
        print(render.badge(args.domain, root))
    elif args.cmd == "queries":
        print("\n".join(displacement.search_queries(args.tool)))
    elif args.cmd == "fetch":
        print(fetch_text(args.url)[: args.max])
    elif args.cmd == "notify":
        from . import notify
        notify.send(diff(args.domain, root))
    elif args.cmd == "compare":
        from . import render
        render.compare(args.domains, root)


if __name__ == "__main__":
    main()
