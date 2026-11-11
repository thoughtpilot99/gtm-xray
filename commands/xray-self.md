---
description: X-ray your own company - GTM leak score, what competitors can read about you, and the fix list
argument-hint: <your-domain>
---
Run GTM X-Ray on our own domain: $ARGUMENTS

1. `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray collect $ARGUMENTS`, then `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray badge $ARGUMENTS`.
2. Explain the leak score line by line: what a competitor learns from each item (quote the actual data found).
3. Sort fixes into: fix now (cheap, high exposure), accept (exposure that is worth it, e.g. SEO pages), and
   watch. Never suggest hiding anything that is legally required to be public (e.g. pay ranges where mandated).
4. Render the report and print the badge markdown: ![GTM leak score](runs/<domain>/<date>/leak-badge.svg)
