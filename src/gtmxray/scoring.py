"""Outbound capacity estimate, GTM motion radar and the GTM Leak Score.

Everything here is arithmetic on SEEN facts. Each output carries its assumptions so a
reader can redo the math.
"""

from __future__ import annotations

from .ledger import INFERRED, Ledger

# Assumptions are stated, not hidden. Change them and the estimate changes with them.
INBOXES_PER_DOMAIN = (2, 3)        # common cold-email setup: 2-3 mailboxes per sending domain
SENDS_PER_INBOX_PER_DAY = (20, 30)  # conservative deliverability cap used by most outbound teams
SENDING_DAYS_PER_MONTH = 21


def outbound_capacity(forensics: dict, led: Ledger, domain: str) -> dict:
    n = len([x for x in forensics.get("owned_sending_domains", [])
             if x.get("kind", "").startswith("lookalike") and x.get("wired_for_email", True)])
    if n == 0:
        return {"secondary_domains": 0, "monthly_low": 0, "monthly_high": 0, "assumptions": None}
    lo = n * INBOXES_PER_DOMAIN[0] * SENDS_PER_INBOX_PER_DAY[0] * SENDING_DAYS_PER_MONTH
    hi = n * INBOXES_PER_DOMAIN[1] * SENDS_PER_INBOX_PER_DAY[1] * SENDING_DAYS_PER_MONTH
    assumptions = {"inboxes_per_domain": INBOXES_PER_DOMAIN, "sends_per_inbox_per_day": SENDS_PER_INBOX_PER_DAY,
                   "sending_days_per_month": SENDING_DAYS_PER_MONTH}
    led.add("outbound", f"ESTIMATE: {n} lookalike sending domains could carry {lo:,}-{hi:,} cold emails/month",
            f"dns:MX {domain} lookalikes", "domains x inboxes x daily cap x days (assumptions shown)",
            kind=INFERRED, value=assumptions, confidence=0.5)
    return {"secondary_domains": n, "monthly_low": lo, "monthly_high": hi, "assumptions": assumptions,
            "note": "Capacity, not observed volume. Real sends can be lower."}


def motion_radar(facts: dict) -> dict:
    """0-100 per motion, from SEEN signals only."""
    h = facts.get("hiring") or {}
    p = facts.get("pagesource") or {}
    m = p.get("motion", {})
    s = facts.get("sitemap") or {}
    o = facts.get("outbound") or {}
    n = max(h.get("open_roles", 0), 1)
    sales_share = (h.get("by_dept", {}).get("sales", 0)) / n
    mkt_share = (h.get("by_dept", {}).get("marketing", 0)) / n
    ic = s.get("intent_counts", {})

    def clamp(x: float) -> int:
        return int(max(0, min(100, round(x))))

    ss, sl = m.get("self_serve_ctas", 0), m.get("sales_ctas", 0)
    return {
        "Product-led": clamp((ss / max(ss + sl, 1)) * 70 + (30 if m.get("free_plan") else 0)),
        "Sales-led": clamp(sales_share * 160 + (sl / max(ss + sl, 1)) * 30
                           + (15 if m.get("contact_sales_on_pricing") else 0)
                           + h.get("sales_roles", {}).get("AE", 0) * 3
                           + (h.get("by_segment") or {}).get("Enterprise", 0) * 2),
        "Outbound": clamp(len([x for x in o.get("owned_sending_domains", [])
                               if x.get("kind", "").startswith("lookalike") and x.get("wired_for_email", True)]) * 15
                          + len(o.get("sending_tools_detected", [])) * 15
                          + h.get("sales_roles", {}).get("SDR/BDR", 0) * 8
                          + len(m.get("visitor_id_tools", [])) * 15),
        "Content & SEO": clamp((s.get("url_count", 0) ** 0.5) * 1.2 + ic.get("comparison", 0) * 0.6
                               + mkt_share * 80),
        "Partner-led": clamp(min(ic.get("integrations", 0), 300) / 3 + (25 if s.get("has_partner_program") else 0)
                             + h.get("sales_roles", {}).get("Partnerships", 0) * 10),
        "Paid": clamp(len(m.get("ad_pixels", [])) * 18 + len(m.get("abm_tools", [])) * 20
                      + h.get("paid_roles", 0) * 15),
    }


def leak_score(facts: dict) -> dict:
    """How much of the GTM a company exposes publicly. Higher = easier to X-ray."""
    h = facts.get("hiring") or {}
    s = facts.get("sitemap") or {}
    p = facts.get("pagesource") or {}
    d = facts.get("dns") or {}
    o = facts.get("outbound") or {}
    w = facts.get("wayback") or {}
    parts = [
        ("Public job feed with full descriptions", 20 if h.get("open_roles") else 0, 20,
         "Use an ATS that hides the public JSON feed, or strip tool names from job descriptions."),
        ("Compensation published", min(10, h.get("roles_with_comp", 0)), 10,
         "Pay ranges reveal seniority and segment. Often legally required; accept it."),
        ("Sitemap exposes page inventory", min(15, s.get("url_count", 0) // 200), 15,
         "Split sensitive sections out of the public sitemap."),
        ("Comparison pages name targets", min(10, len(s.get("comparison_targets", {}))), 10,
         "Expected for SEO, but it tells rivals exactly who you attack."),
        ("Tools visible in DNS", min(10, len(d.get("tools_from_txt", [])) * 2), 10,
         "Remove stale verification TXT records after setup."),
        ("Tools visible in page source", min(10, len(p.get("tools", {}))), 10,
         "Load GTM scripts through a server-side tag manager."),
        ("Secondary sending domains discoverable", min(15, len(o.get("owned_sending_domains", [])) * 5), 15,
         "Do not 301 cold domains to the main site; use a neutral landing page."),
        ("Positioning history archived", min(10, len(w.get("snapshots", {}).get("/", []))), 10,
         "Nothing to do. The archive is public; just know rivals read it."),
    ]
    score = sum(x[1] for x in parts)
    return {"score": int(score), "max": 100,
            "breakdown": [{"item": a, "points": b, "of": c, "fix": f} for a, b, c, f in parts]}
