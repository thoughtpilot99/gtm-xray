---
name: gtm-xray
description: Reverse-engineer any company's go-to-market from public data and turn it into a plan to win their customers. Use when asked to X-ray, tear down, reverse-engineer, spy on, audit or analyze a competitor's or prospect's GTM, sales motion, hiring, outbound setup, tool stack, SEO/content engine, pricing history or positioning; to find who uses a competitor; to build a battlecard or displacement list; to compare competitors or map a market; to watch a competitor weekly; to score how much your own site leaks; or to turn a teardown into posts.
---

# GTM X-Ray

Two halves. **Collectors** (Python, `xray` CLI or the `gtm-xray` MCP server) gather public facts into
`runs/<domain>/<date>/` with an evidence ledger. **Agents** (this plugin, Claude Fable 5.2) read those
files, reason, verify, and write `analysis.json`. `xray render` turns both into `report.html`.

**Tool access, in order of preference** (subagents often run with tighter permissions than the main session):
1. The `gtm-xray` MCP tools (`xray_collect`, `xray_facts`, `xray_ledger`, `xray_verify_jobs`, `xray_hn_hiring`,
   `xray_accounts`, `xray_fetch`, `xray_render`, ...). The plugin starts this server automatically.
2. The CLI: `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray <cmd>`, or `uv run xray <cmd>` inside the repo.
3. If a site blocks WebFetch (web.archive.org often does), read it with `xray_fetch` / `xray fetch <url>`.
If an agent has neither MCP nor shell, it must say which steps it could not run, never fill the gap by guessing.

## The workflow (collect, understand, verify, attack, publish)

1. **Collect** `xray collect <domain>` (add `--browser` for a real network log + screenshots). ~30 s, runs
   hiring, dns, outbound, sitemap, pagesource, wayback and web collectors in parallel.
2. **Understand** In ONE message, launch the investigator agents in parallel, each on its own slice of
   `facts.json` / `roles.json` / `ledger.jsonl`: `hiring-analyst`, `outbound-forensics`, `stack-detective`,
   `content-seo-mapper`, `messaging-historian`, `customer-mapper`, `voice-of-customer`, `ads-intel`.
   Each returns findings in the shape below.
3. **Verify** `verifier` checks every finding against the ledger and the live source. Two independent
   sources or it ships as INFERRED with a confidence. No source = cut.
4. **Attack** `strategist` writes `analysis.json`: verdict, attack plan, battlecard, predictions, unknowns,
   social cards. Then `xray accounts <domain>` builds `accounts.json` + `clay-import.csv`.
5. **Publish** `xray render <domain> [--png]`. Optional: `content-writer` turns the run into posts.

## Finding shape (every agent returns a JSON list of these)

```json
{"claim": "Cursor is building an APAC sales team", "kind": "SEEN|INFERRED|ESTIMATE",
 "confidence": 0.0, "evidence": ["ev_ab12cd34ef"], "sources": ["https://..."],
 "so_what": "One line: why a seller should care", "limits": "What this does not prove"}
```
`evidence` holds ledger ids from `ledger.jsonl`. New facts an agent finds with WebSearch/WebFetch must be
added with their URL in `sources`. The verifier rejects any claim with neither.

## analysis.json contract (written by strategist, read by the report)

```json
{
  "headline": "Cursor is quietly building an enterprise sales machine in APAC",
  "verdict": "2-3 sentences. The single most useful read of their GTM.",
  "predictions": [{"text": "...", "evidence": ["ev_..."]}],
  "attack_plan": [{
     "name": "Play name", "why": "evidence-based reason it works now", "evidence": ["ev_..."],
     "who": "accounts + titles", "trigger": "signal that fires it",
     "steps": ["...", "..."],
     "sequence": [{"subject": "...", "body": "..."}, {"subject": "", "body": "..."}, {"subject": "", "body": "..."}]
  }],
  "battlecard": {"they_win_when": [], "they_lose_when": [], "landmines": [],
                 "objections": [{"q": "", "a": ""}]},
  "unknowns": [{"text": "What we could not see", "next_probe": "How to find out"}],
  "cards": [{"kicker": "", "big": "", "h": "", "s": "", "rows": []}]
}
```

## Evidence rules (non-negotiable)

- Public data only: public pages, public job feeds, public DNS, public archives, public ad libraries.
  No logins, no form submissions, no private APIs, no scraping behind auth, no personal data beyond
  what a company itself publishes. HAR files are only ones the user recorded of their OWN session.
- Every number in a report traces to a ledger row or a cited URL. Estimates say ESTIMATE and show the math.
- DNS tokens prove a tool was connected, not that it is used heavily. A script tag can be a leftover.
- Lookalike domains that redirect to the company are counted as theirs; others are not.
- Old Wayback captures may belong to a previous owner of the domain: check `wayback.limitations`.
- Job-post boilerplate is stripped before counting tools; the blurb itself is kept in `hiring.company_blurb`
  and is a good source of customer names and headline metrics.
- Never invent a customer, a person, a number or a quote. If the data is thin, say so in `unknowns`.

## Modes

| Command | What it does |
|---|---|
| `/xray <domain>` | Full teardown + attack plan |
| `/xray-compare <a> <b> [...]` | Side-by-side matrix + who is winning which motion |
| `/xray-market "<category>"` | Find the top players, X-ray all, rank them |
| `/xray-self <your-domain>` | Leak score + fix list: what your site tells competitors |
| `/xray-audit <prospect>` | Agency mode: client-ready GTM audit before a sales call |
| `/xray-watch <domain>` | Re-run and diff vs last week (pair with the GitHub Action) |
| `/xray-content <domain>` | Turn a run into posts, a thread, an article and carousel text |
| `/xray-recreate <domain>` | Rebuild their winning playbook for YOUR company |
