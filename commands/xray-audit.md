---
description: Agency mode - a client-ready GTM audit of a prospect, for the sales call
argument-hint: <prospect-domain>
---
Prepare a GTM audit of the prospect: $ARGUMENTS

Frame: we are an agency/consultant preparing for a sales call with this company. The goal is a respectful,
useful teardown of THEIR go-to-market that shows exactly where we would help.

1. Run the /xray workflow on the prospect (collect, investigator agents, verifier).
2. The strategist writes analysis.json with: headline = their biggest GTM opportunity; attack_plan = the 3-5
   plays WE would run for THEM (not against them); battlecard = their competitors' strengths vs theirs.
3. `uv run --project "${CLAUDE_PLUGIN_ROOT}" xray render $ARGUMENTS --audit` (adds audit styling). Then print a 6-bullet call prep: 3 things they do
   well (compliment with numbers), 3 gaps, 1 question that opens the conversation.
