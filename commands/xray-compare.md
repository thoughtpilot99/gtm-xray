---
description: Side-by-side GTM X-Ray of several companies - who is winning which motion
argument-hint: <domain> <domain> [domain...]
---
Compare the go-to-market of: $ARGUMENTS

1. For each domain without a run from the last 7 days, run `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray collect <domain>` (in parallel, one Bash call each).
2. `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray compare $ARGUMENTS` writes runs/compare-*.html.
3. Launch one motion-classifier agent per domain in parallel, then write a 10-line verdict: who is moving upmarket,
   who runs real outbound, who owns SEO, who is entering which region, and the gap none of them covers.
   Every line cites a number from the runs.
