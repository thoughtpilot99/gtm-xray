---
description: Full GTM X-Ray of a company domain - teardown, displacement list, attack plan, battlecard, report
argument-hint: <domain> [--browser]
---
Run a full GTM X-Ray on: $ARGUMENTS

Follow the gtm-xray skill workflow exactly:
1. Collect: `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray collect $ARGUMENTS`. Report the per-collector timings and any errors.
2. Understand: in ONE message launch in parallel the agents hiring-analyst, outbound-forensics, stack-detective,
   content-seo-mapper, messaging-historian, motion-classifier, customer-mapper, voice-of-customer and ads-intel,
   each pointed at the run folder from step 1 (and the product name for customer-mapper / voice-of-customer).
3. Verify: pass all findings to the verifier agent.
4. Attack: pass the verifier's kept findings to the strategist agent; it writes analysis.json and renders.
5. Finish with: the headline, the 3 strongest SEEN numbers, the top 5 displacement accounts, the path to
   report.html and clay-import.csv. Offer /xray-content next.
