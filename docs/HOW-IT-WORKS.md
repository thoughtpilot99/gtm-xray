# How GTM X-Ray works

```
 you: /xray acme.com
        │
        ▼
 ┌──────────────── COLLECT (python, ~30s, zero API keys) ────────────────┐
 │ hiring      Ashby/Greenhouse/Lever/Workable/SmartRecruiters public feeds │
 │ dns         TXT verification tokens, SPF senders, MX, DMARC              │
 │ outbound    ~100 lookalike domains → MX → redirect check → tracking CNAME │
 │ sitemap     robots.txt → every sitemap → pages per folder, locales,       │
 │             comparison targets, integrations, customer stories           │
 │ pagesource  homepage/pricing/customers: tools, CTAs, logos, free plan     │
 │ wayback     first capture per year: headline + pricing history           │
 │ web         public JS bundles: analytics events, feature flags,          │
 │             experiment vendors, funnel CTAs, form fields (+ --browser)    │
 └────────────── facts.json · roles.json · ledger.jsonl ─────────────────┘
        │
        ▼
 ┌──────────── UNDERSTAND (Claude Fable 5.2 agents, in parallel) ────────┐
 │ hiring-analyst · outbound-forensics · stack-detective ·               │
 │ content-seo-mapper · messaging-historian · motion-classifier ·        │
 │ customer-mapper (Displacement Engine) · voice-of-customer · ads-intel  │
 └──────────────────────────── findings ────────────────────────────────┘
        │
        ▼
 VERIFY   verifier: 2 sources or INFERRED, no source = cut, classic traps checked
        │
        ▼
 ATTACK   strategist → analysis.json (verdict, plays + emails, battlecard, unknowns)
          xray accounts → accounts.json + clay-import.csv
        │
        ▼
 PUBLISH  xray render → report.html (+ social cards PNG, leak badge)
          content-writer → x-post, thread, article, LinkedIn, carousel
```

## The evidence ledger

Every collector writes rows like this to `ledger.jsonl`:

```json
{"id": "ev_3f9a1c0b2d", "module": "outbound", "kind": "SEEN",
 "claim": "tryacme.com is wired for email and redirects to acme.com",
 "source_url": "https://tryacme.com", "method": "MX lookup + HTTP redirect",
 "confidence": 0.9, "collected_at": "2026-11-11T10:02:11+00:00"}
```

Agents cite ledger ids. The report links every claim to its row. `SEEN` = read off a public source.
`INFERRED` = a conclusion from SEEN rows. `ESTIMATE` = arithmetic with the assumptions printed next to it.

## Why the Displacement Engine works

Companies write the tools they use into their job posts ("experience with Clay required"). Those posts sit on
public ATS pages that search engines index. So a search across ATS hosts for a product name, followed by a
check that the product is really named in the post, gives you a list of companies running that product right
now, with a hiring reason to talk to them this month. Add the competitor's own logo wall and case studies,
merge, rank by number of independent sources, export to Clay.

## Funnel X-Ray

A website gives away a lot through the artifacts it ships to every visitor: the JavaScript a marketing site sends to every
visitor names its analytics events, its experiment platform and often its feature flags. The network calls
name its tools. The forms name its qualification criteria. `--browser` adds a real network log and screenshots;
`xray har` reads a capture you recorded of your own session (for example your own free trial).

## Cost and speed

Collectors: about 30 seconds per company, no keys, no paid data. A full `/xray` with all agents typically uses
Claude Fable 5.2 for 10-20 minutes of agent time (web searches and fetches included).
