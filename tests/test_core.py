"""Offline tests: no network. Live smoke test is marked `live`."""

import json

import httpx
import pytest
import respx

from gtmxray import ats, displacement, dns_probe, fp, net, scoring, sitemap, wayback
from gtmxray.ledger import INFERRED, SEEN, Ledger


def test_normalize_and_stem():
    assert net.normalize_domain("https://www.Acme.com/pricing") == "acme.com"
    assert net.stem("acme.io") == "acme"
    assert net.same_site("https://docs.acme.com/x", "acme.com")
    assert not net.same_site("https://notacme.com", "acme.com")


def test_generic_txt_vendor():
    assert fp.generic_txt_vendor("figma-domain-verification=abc") == "figma"
    assert fp.generic_txt_vendor("v=spf1 include:_spf.google.com ~all") is None
    assert fp.generic_txt_vendor("domain-verification=xyz") is None


def test_lookalikes_cover_common_patterns():
    c = dns_probe.lookalike_candidates("acme.com")
    for want in ["tryacme.com", "getacme.com", "acmehq.com", "acme.io", "joinacme.co"]:
        assert want in c
    assert "acme.com" not in c


def test_classify_sales_roles_and_tools():
    job = {"title": "Enterprise Account Executive, APAC", "location": "Singapore", "department": "Sales",
           "description": "You will run Salesforce and Gong. Experience with Clay is a plus.", "url": "u"}
    r = ats.classify(job)
    assert r["dept"] == "sales" and r["sales_role"] == "AE" and r["segment"] == "Enterprise"
    assert {"Salesforce", "Gong", "Clay"} <= set(r["tools_named"])
    assert ats._region("Singapore") == "APAC"
    assert ats.classify({"title": "Founding SDR", "description": ""})["first_hire"]


def test_boilerplate_is_stripped_before_tool_matching():
    blurb = "Teams at companies like Adidas and Zendesk build on Acme every single day of the week."
    jobs = [{"title": f"Engineer {i}", "description": blurb + f" Role {i} uses Python."} for i in range(8)]
    b = ats.boilerplate(jobs)
    assert blurb in b
    cleaned = ats.strip_boilerplate(jobs[0]["description"], b)
    assert "Zendesk" not in cleaned


@respx.mock
def test_sitemap_counts_and_comparison_targets():
    respx.get("https://acme.com/robots.txt").mock(return_value=httpx.Response(200, text="Sitemap: https://acme.com/sm.xml"))
    urls = ["https://acme.com/blog/a", "https://acme.com/blog/b", "https://acme.com/compare/hubspot",
            "https://acme.com/acme-vs-salesforce", "https://acme.com/t/vs-code-is-broken",
            "https://acme.com/customers/big-co", "https://acme.com/de/blog/a"]
    xml = "<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>"
    respx.get("https://acme.com/sm.xml").mock(return_value=httpx.Response(200, text=xml))
    led = Ledger()
    res = sitemap.collect("acme.com", led)
    assert res["url_count"] == 7
    assert set(res["comparison_targets"]) == {"hubspot", "salesforce"}  # forum thread ignored
    assert res["locales"] == {"de": 1}
    assert "big co" in res["customer_story_names"]
    assert any(r.module == "seo" for r in led.rows)


def test_wayback_extract_prices_need_a_billing_period():
    html = """<html><head><title>Acme</title></head><body><h1>AI for sales</h1>
      <p>Pro $49/mo</p><p>Team $99 per month</p><p>Credits $0.10 per credit</p><a>Book a demo</a></body></html>"""
    e = wayback.extract(html)
    assert e["prices"] == [49.0, 99.0]
    assert e["mentions_ai"] and "book a demo" in e["ctas"]


def test_capacity_counts_only_lookalikes():
    led = Ledger()
    f = {"owned_sending_domains": [{"domain": "acme.io", "kind": "brand / legacy domain"},
                                   {"domain": "tryacme.com", "kind": "lookalike (cold-email pattern)"},
                                   {"domain": "getacme.com", "kind": "lookalike (cold-email pattern)"}]}
    cap = scoring.outbound_capacity(f, led, "acme.com")
    assert cap["secondary_domains"] == 2
    assert cap["monthly_low"] == 2 * 2 * 20 * 21 and cap["monthly_high"] == 2 * 3 * 30 * 21
    assert led.rows[0].kind == INFERRED


def test_leak_score_and_radar_bounds():
    facts = {"hiring": {"open_roles": 50, "by_dept": {"sales": 20}, "sales_roles": {"SDR/BDR": 3}, "roles_with_comp": 4},
             "sitemap": {"url_count": 5000, "comparison_targets": {"a": 1, "b": 2}, "intent_counts": {"comparison": 10}},
             "pagesource": {"tools": {"HubSpot": {}}, "motion": {"self_serve_ctas": 5, "sales_ctas": 5}},
             "dns": {"tools_from_txt": ["Slack"]}, "outbound": {"owned_sending_domains": []}, "wayback": {}}
    s = scoring.leak_score(facts)
    assert 0 <= s["score"] <= 100 and len(s["breakdown"]) == 8
    assert all(0 <= v <= 100 for v in scoring.motion_radar(facts).values())


def test_displacement_merge_ranks_multi_source_first():
    rows = [{"company": "Foo Inc", "source": "job post names the tool", "url": "u1", "why_now": "a", "job_title": "AE"},
            {"company": "foo inc", "source": "competitor case study", "url": "u2", "why_now": "b"},
            {"company": "Bar", "source": "competitor customer wall", "url": "u3", "why_now": "c"}]
    m = displacement.merge(rows)
    assert m[0]["company"] == "Foo Inc" and len(m[0]["sources"]) == 2


def test_ledger_roundtrip(tmp_path):
    led = Ledger()
    led.add("x", "claim", "https://a", "m")
    led.add("x", "claim", "https://a", "m")  # dedup
    led.write(tmp_path / "l.jsonl")
    back = Ledger.read(tmp_path / "l.jsonl")
    assert len(back.rows) == 1 and back.rows[0].kind == SEEN


def test_render_embeds_data(tmp_path):
    from gtmxray import render
    rd = tmp_path / "acme.com" / "2026-01-01"
    rd.mkdir(parents=True)
    (rd / "facts.json").write_text(json.dumps({"domain": "acme.com", "leak_score": {"score": 42}}))
    (rd / "analysis.json").write_text(json.dumps({"headline": "Acme </script> test"}))
    out = render.render("acme.com", tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "__DATA__" not in html and "<\\/script>" in html
    assert render.badge("acme.com", tmp_path).read_text().count("42/100") == 2


@pytest.mark.live
def test_live_collect_small_domain(tmp_path):
    from gtmxray import cli
    rd = cli.collect("example.com", tmp_path, {"wayback", "outbound"})
    assert (rd / "facts.json").exists()
