"""Hiring = roadmap. Pull every open role from the company's public job board feed.

Supports Greenhouse, Lever, Ashby, Workable and SmartRecruiters public endpoints (no keys).
Classifies each role, reads the tools named in the description, and flags roadmap moves:
first hires in a function, new regions, upmarket pushes, reposts.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from urllib.parse import unquote

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from . import fp, net
from .ledger import INFERRED, Ledger

CAREER_PATHS = ["", "/careers", "/jobs", "/company/careers", "/about/careers", "/join", "/join-us",
                "/work-with-us", "/company", "/about"]

DEPT_RULES = [
    ("sales", r"\b(account executive|\bae\b|sdr|bdr|sales|business development|account manager|"
              r"solutions? (?:engineer|consultant)|sales engineer|partnerships?|channel|alliances|"
              r"revenue operations|revops|deal desk|gtm|go-to-market|customer success)\b"),
    ("marketing", r"\b(marketing|growth|demand gen|content|brand|seo|communications|pr\b|"
                  r"community|events|social media|lifecycle|product marketing|pmm|developer relations|devrel)\b"),
    ("engineering", r"\b(engineer|developer|sre|devops|infrastructure|security|ml|machine learning|"
                    r"research|scientist|data)\b"),
    ("product", r"\b(product manager|product design|designer|ux|ui)\b"),
    ("support", r"\b(support|customer experience|cx|onboarding|implementation)\b"),
    ("g&a", r"\b(finance|legal|people|recruit|talent|hr\b|accounting|operations|office|executive assistant)\b"),
]
SALES_SUB = [
    ("SDR/BDR", r"\b(sdr|bdr|sales development|business development rep)"),
    ("AE", r"\b(account executive|\bae\b)"),
    ("Sales Engineer", r"\b(solutions? engineer|sales engineer|solutions? architect|forward deployed)"),
    ("Account Management / CS", r"\b(account manager|customer success|csm)"),
    ("Partnerships", r"\b(partner|channel|alliances)"),
    ("RevOps", r"\b(revenue operations|revops|sales operations|gtm operations|deal desk)"),
    ("Sales Leadership", r"\b(head of sales|vp,? sales|vice president.*sales|director.*sales|cro\b|chief revenue)"),
]
SEGMENT = [
    ("Enterprise", r"\b(enterprise|strategic|global accounts?|large accounts?|fortune)"),
    ("Mid-Market", r"\b(mid[- ]?market|commercial)"),
    ("SMB", r"\b(smb|small business|startup|self[- ]serve)"),
    ("Public Sector", r"\b(public sector|federal|government|gov\b)"),
]
FIRST_HIRE = r"\b(first|founding|1st)\b"
SENIOR = r"\b(head of|vp\b|vice president|director|chief|lead\b|principal|staff)"


def _strip(h: str) -> str:
    if not h:
        return ""
    txt = HTMLParser(html.unescape(h)).text(separator=" ")
    return re.sub(r"\s+", " ", txt).strip()


def detect(domain: str) -> list[tuple[str, str, str]]:
    """Return [(ats, board_token, evidence_url)] found on the company's own site."""
    t = fp.load()["ats"]
    found: dict[tuple[str, str], str] = {}
    with net.client() as c:
        for path in CAREER_PATHS:
            url = f"https://{domain}{path}"
            r = net.get(c, url, retries=0)
            if r is None or r.status_code >= 400:
                continue
            body = r.text
            for ats, pats in t.items():
                for p in pats:
                    for m in re.finditer(p, body):
                        tok = unquote(m.group(1)).strip("/")
                        if tok and tok.lower() not in {"embed", "api", "v1", "jobs"}:
                            found.setdefault((ats, tok), str(r.url))
            if found and path:
                break
    return [(a, tok, u) for (a, tok), u in found.items()]


def _guess_tokens(domain: str) -> list[str]:
    s = net.stem(domain)
    return list(dict.fromkeys([s, s.replace("-", ""), f"{s}hq", f"{s}inc", f"{s}ai", f"{s}-ai"]))


def fetch_board(ats: str, token: str) -> tuple[list[dict], str]:
    with net.client() as c:
        if ats == "greenhouse":
            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
            r = net.get(c, url)
            if r is None or r.status_code != 200:
                return [], url
            jobs = []
            for j in r.json().get("jobs", []):
                jobs.append({
                    "title": j.get("title", ""),
                    "location": (j.get("location") or {}).get("name", ""),
                    "department": ", ".join(d.get("name", "") for d in j.get("departments", [])),
                    "url": j.get("absolute_url", ""),
                    "updated": j.get("updated_at", ""),
                    "published": j.get("first_published", "") or j.get("updated_at", ""),
                    "description": _strip(j.get("content", "")),
                    "comp": "",
                })
            return jobs, url
        if ats == "lever":
            for host in ("api.lever.co", "api.eu.lever.co"):
                url = f"https://{host}/v0/postings/{token}?mode=json"
                r = net.get(c, url)
                if r is not None and r.status_code == 200 and isinstance(r.json(), list):
                    jobs = []
                    for j in r.json():
                        cats = j.get("categories") or {}
                        sal = j.get("salaryRange") or {}
                        comp = ""
                        if sal.get("min"):
                            comp = f"{sal.get('currency', '')} {sal.get('min')}-{sal.get('max')} {sal.get('interval', '')}".strip()
                        desc = j.get("descriptionPlain") or _strip(j.get("description", ""))
                        for lst in j.get("lists", []):
                            desc += " " + lst.get("text", "") + " " + _strip(lst.get("content", ""))
                        jobs.append({
                            "title": j.get("text", ""),
                            "location": cats.get("location", ""),
                            "department": cats.get("team", "") or cats.get("department", ""),
                            "url": j.get("hostedUrl", ""),
                            "published": _ms_to_iso(j.get("createdAt")),
                            "updated": "",
                            "description": desc,
                            "comp": comp,
                        })
                    return jobs, url
            return [], f"https://api.lever.co/v0/postings/{token}?mode=json"
        if ats == "ashby":
            url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
            r = net.get(c, url)
            if r is None or r.status_code != 200:
                return [], url
            jobs = []
            for j in r.json().get("jobs", []):
                comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
                jobs.append({
                    "title": j.get("title", ""),
                    "location": j.get("location", ""),
                    "department": j.get("department", "") or j.get("team", ""),
                    "url": j.get("jobUrl", ""),
                    "published": j.get("publishedAt", ""),
                    "updated": "",
                    "description": j.get("descriptionPlain") or _strip(j.get("descriptionHtml", "")),
                    "comp": comp,
                    "remote": j.get("isRemote"),
                })
            return jobs, url
        if ats == "workable":
            url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
            r = net.get(c, url)
            if r is None or r.status_code != 200:
                return [], url
            jobs = []
            for j in r.json().get("jobs", []):
                jobs.append({
                    "title": j.get("title", ""),
                    "location": ", ".join(filter(None, [j.get("city"), j.get("country")])),
                    "department": j.get("department", ""),
                    "url": j.get("url", ""),
                    "published": j.get("published_on", ""),
                    "updated": "",
                    "description": _strip(j.get("description", "")),
                    "comp": "",
                })
            return jobs, url
        if ats == "smartrecruiters":
            url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"
            r = net.get(c, url)
            if r is None or r.status_code != 200:
                return [], url
            jobs = []
            for j in r.json().get("content", []):
                loc = j.get("location") or {}
                jobs.append({
                    "title": j.get("name", ""),
                    "location": ", ".join(filter(None, [loc.get("city"), loc.get("country")])),
                    "department": (j.get("department") or {}).get("label", ""),
                    "url": f"https://jobs.smartrecruiters.com/{token}/{j.get('id')}",
                    "published": j.get("releasedDate", ""),
                    "updated": "",
                    "description": "",
                    "comp": "",
                })
            return jobs, url
    return [], ""


def _ms_to_iso(ms) -> str:
    import datetime as dt
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def _first(rules, text: str) -> str:
    for name, pat in rules:
        if re.search(pat, text, re.I):
            return name
    return ""


def classify(job: dict) -> dict:
    title = job["title"]
    blob = f"{title} {job.get('department', '')}"
    dept = _first(DEPT_RULES, title) or _first(DEPT_RULES, blob) or "other"
    tools = fp.load()["jd_tools"]
    desc = job.get("description", "")
    named = sorted({tl for tl in tools if re.search(rf"(?<![A-Za-z]){re.escape(tl)}(?![A-Za-z])", desc)})
    return {
        **{k: v for k, v in job.items() if k != "description"},
        "dept": dept,
        "sales_role": _first(SALES_SUB, title) if dept == "sales" else "",
        "segment": _first(SEGMENT, title),  # titles only: descriptions mention "enterprise" too loosely
        "first_hire": bool(re.search(FIRST_HIRE, title, re.I)),
        "senior": bool(re.search(SENIOR, title, re.I)),
        "tools_named": named,
        "desc_chars": len(desc),
    }


def _region(loc: str) -> str:
    l = (loc or "").lower()
    if not l:
        return "Unspecified"
    if "remote" in l and not re.search(r"(us|united states|uk|europe|emea|apac|canada)", l):
        return "Remote"
    for name, pat in [
        ("North America", r"(united states|\busa?\b|new york|san francisco|sf\b|nyc|boston|austin|seattle|"
                          r"chicago|denver|los angeles|miami|atlanta|toronto|canada|vancouver|remote.?-?\s*us|"
                          r"\b[a-z]+, (ca|ny|tx|wa|ma|co|il|ga|fl)\b)"),
        ("Europe", r"(london|uk|united kingdom|dublin|ireland|paris|france|berlin|munich|germany|amsterdam|"
                   r"netherlands|stockholm|sweden|madrid|barcelona|spain|lisbon|portugal|europe|emea|zurich|"
                   r"copenhagen|warsaw|poland|italy|milan|brussels|belgium)"),
        ("APAC", r"(singapore|sydney|melbourne|australia|tokyo|japan|india|bangalore|bengaluru|seoul|korea|"
                 r"hong kong|apac|asia)"),
        ("LATAM", r"(brazil|são paulo|sao paulo|mexico|argentina|buenos aires|colombia|chile|latam)"),
        ("Middle East & Africa", r"(dubai|uae|israel|tel aviv|riyadh|saudi|africa|lagos|cairo)"),
    ]:
        if re.search(pat, l):
            return name
    return "Other"


_SENT = re.compile(r"(?<=[.!?])\s+")


def boilerplate(jobs: list[dict], share: float = 0.4) -> list[str]:
    """Sentences that repeat across most postings: the company blurb, benefits, EEO text.
    Tool names inside them say nothing about the role, so they are matched separately."""
    if len(jobs) < 5:
        return []
    cnt: Counter = Counter()
    for j in jobs:
        cnt.update({s.strip() for s in _SENT.split(j.get("description", "")) if len(s.strip()) > 40})
    need = max(5, int(len(jobs) * share))
    return [s for s, k in cnt.most_common() if k >= need]


def strip_boilerplate(desc: str, boiler: list[str]) -> str:
    for s in boiler:
        desc = desc.replace(s, " ")
    return desc


def analyze(domain: str, led: Ledger) -> dict:
    d = net.normalize_domain(domain)
    boards = detect(d)
    tried: list[str] = []
    jobs: list[dict] = []
    used: tuple[str, str, str] | None = None
    for ats, tok, ev in boards:
        js, url = fetch_board(ats, tok)
        tried.append(url)
        if js:
            jobs, used = js, (ats, tok, url)
            led.add("hiring", f"{d} posts jobs on {ats.title()} (board '{tok}')", ev,
                    "careers page link", value=ats, confidence=0.95)
            break
    if not jobs:  # guess common board names when the careers page renders client-side
        for ats in ("ashby", "greenhouse", "lever", "workable"):
            for tok in _guess_tokens(d):
                js, url = fetch_board(ats, tok)
                tried.append(url)
                if js and _board_matches(js, d):
                    jobs, used = js, (ats, tok, url)
                    led.add("hiring", f"{d} job board found on {ats.title()} (board '{tok}')", url,
                            "board name guess, verified by company links in postings",
                            value=ats, confidence=0.75)
                    break
            if jobs:
                break
    if not jobs:
        return {"ats": None, "tried": tried, "open_roles": 0}

    ats, tok, feed = used
    boiler = boilerplate(jobs)
    if boiler:
        for j in jobs:
            j["description"] = strip_boilerplate(j.get("description", ""), boiler)
        led.add("hiring", "Company blurb repeated in every job post (mine it for customer names and metrics)",
                feed, "sentences shared by >=40% of postings", value=" ".join(boiler)[:1200], confidence=0.95)
    roles = [classify(j) for j in jobs]
    n = len(roles)
    by_dept = Counter(r["dept"] for r in roles)
    sales = [r for r in roles if r["dept"] == "sales"]
    by_sales = Counter(r["sales_role"] or "Other GTM" for r in sales)
    by_region = Counter(_region(r["location"]) for r in roles)
    gtm_by_region = Counter(_region(r["location"]) for r in roles if r["dept"] in ("sales", "marketing"))
    by_segment = Counter(r["segment"] for r in roles if r["segment"])
    own = net.stem(d)
    tools = Counter(t for r in roles for t in r["tools_named"] if t.lower() != own)
    with_comp = [r for r in roles if r.get("comp")]

    led.add("hiring", f"{n} open roles on the public {ats.title()} feed", feed, "ATS public API",
            value=n, confidence=0.98)
    for dept, k in by_dept.most_common():
        led.add("hiring", f"{k} of {n} open roles are {dept}", feed, "title classification",
                value=k, confidence=0.85)
    for role, k in by_sales.most_common():
        led.add("hiring", f"{k} open {role} roles", feed, "title classification", value=k, confidence=0.85)
    for tool, k in tools.most_common(15):
        led.add("hiring", f"{tool} named in {k} job descriptions", feed, "JD text match",
                value=k, confidence=0.9)

    roadmap = []
    firsts = [r for r in roles if r["first_hire"]]
    for r in firsts:
        roadmap.append({"signal": "First / founding hire", "detail": r["title"], "url": r["url"]})
        led.add("roadmap", f"First or founding hire: {r['title']}", r["url"] or feed, "title keyword",
                kind=INFERRED, confidence=0.7)
    if by_segment.get("Enterprise", 0) >= 2:
        roadmap.append({"signal": "Upmarket push", "detail": f"{by_segment['Enterprise']} enterprise-titled roles",
                        "url": feed})
        led.add("roadmap", f"Moving upmarket: {by_segment['Enterprise']} enterprise/strategic roles open",
                feed, "segment keywords", kind=INFERRED, confidence=0.7)
    for region, k in gtm_by_region.items():
        if region not in ("North America", "Unspecified", "Remote", "Other") and k >= 2:
            roadmap.append({"signal": "Regional GTM build-out", "detail": f"{k} sales/marketing roles in {region}",
                            "url": feed})
            led.add("roadmap", f"Building GTM in {region}: {k} sales/marketing roles", feed,
                    "location parse", kind=INFERRED, confidence=0.7)
    if by_sales.get("Sales Leadership"):
        roadmap.append({"signal": "Sales leadership hire", "detail": f"{by_sales['Sales Leadership']} roles",
                        "url": feed})

    recent = sorted([r for r in roles if r.get("published")], key=lambda r: r["published"], reverse=True)
    return {
        "ats": ats,
        "board": tok,
        "feed_url": feed,
        "open_roles": n,
        "by_dept": dict(by_dept.most_common()),
        "gtm_share": round((by_dept.get("sales", 0) + by_dept.get("marketing", 0)) / n, 3),
        "sales_roles": dict(by_sales.most_common()),
        "by_region": dict(by_region.most_common()),
        "gtm_by_region": dict(gtm_by_region.most_common()),
        "by_segment": dict(by_segment.most_common()),
        "tools_in_jds": dict(tools.most_common(25)),
        "roles_with_comp": len(with_comp),
        "comp_samples": [{"title": r["title"], "comp": r["comp"]} for r in with_comp
                         if r["dept"] in ("sales", "marketing")][:12],
        "roadmap": roadmap,
        "company_blurb": " ".join(boiler)[:3000],
        "paid_roles": sum(1 for r in roles if re.search(
            r"\b(performance marketing|paid (media|social|search|acquisition)|growth marketing|user acquisition|"
            r"demand gen(eration)?|media buyer|sem\b|ppc)\b", r["title"], re.I)),
        "newest": [{"title": r["title"], "published": r["published"][:10], "dept": r["dept"],
                    "location": r["location"], "url": r["url"]} for r in recent[:15]],
        "roles": roles,
    }


def _board_matches(jobs: list[dict], domain: str) -> bool:
    """A guessed board name could belong to another company. Require a mention of the domain stem."""
    s = net.stem(domain)
    blob = " ".join(j.get("description", "")[:4000] for j in jobs[:15]).lower()
    return s in blob or net.normalize_domain(domain) in blob
