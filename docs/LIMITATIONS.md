# Limitations (read before you quote a number)

| Area | What it can't tell you | What to do |
|---|---|---|
| Hiring | Companies without a public ATS feed (or with a custom careers site) return 0 roles. Open roles are not hires. Reposts can inflate counts. | Read the careers page by hand; watch over several weeks. |
| Job-post tools | A tool named in a job post may be "nice to have". Boilerplate is stripped, but templates vary. | Treat as SEEN mention, INFERRED usage. |
| DNS tokens | A verification record proves someone connected the tool once. Not usage, not today. | Cross-check with page source and job posts. |
| Lookalike domains | Only domains that redirect to the company are counted. Domains with a neutral landing page are missed. Capacity is an ESTIMATE of what the setup could send, not what it sends. | Say "capacity", never "volume". |
| Tracking CNAMEs | Only known patterns (Instantly, Smartlead, lemlist). Others show as no tool. | Add fingerprints via PR. |
| Sitemaps | Not every page is in a sitemap; some sitemaps are partial or capped (we read up to 60 sitemaps / 60,000 URLs). | Counts are floors. |
| Comparison targets | Slug parsing can pick up non-companies from blog posts. | The content-seo-mapper agent filters them; check the list. |
| Wayback | First capture per year only. Old captures may belong to a previous owner of the domain (flagged automatically). Regex pricing can misread. | Open the archive link before quoting. |
| Page source / JS | Client-rendered pages can hide content from the static scan; minified bundles rename strings. | Use `--browser`. Absence is not proof. |
| Logos | Alt text can be decorative. | The verifier checks logo names. |
| Ad libraries | Render client-side; may need a browser tool or a paste from you. | ads-intel prints the URLs to check. |
| Reviews | Public reviews skew negative and small. | Use themes, not counts. |
| Small companies | Leak less. DNS, sitemap and archive still work. | Expect thinner reports. |
