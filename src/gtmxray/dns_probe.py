"""DNS forensics: the company's tool stack (TXT/SPF/MX) and its hidden cold-email domains.

Public DNS only. Plain UDP lookups often time out on large TXT answers, so every query
retries over TCP.
"""

from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, field

import dns.exception
import dns.resolver

from . import fp, net
from .ledger import INFERRED, Ledger

PREFIXES = ["try", "get", "join", "go", "use", "meet", "with", "hello", "hey", "team", "the", "hi", "my"]
SUFFIXES = ["hq", "app", "team", "mail", "labs", "inc", "now", "online", "ai", "io", "email", "sales", "growth"]
TLDS_PREFIXED = ["com", "co", "io"]
TLDS_SUFFIXED = ["com", "co"]
ALT_TLDS = ["com", "co", "io", "ai", "net", "dev", "so", "app"]
TRACKING_SUBS = ["track", "tracking", "link", "links", "click", "open", "email", "inst", "t", "go", "trk"]


def _resolver() -> dns.resolver.Resolver:
    r = dns.resolver.Resolver()
    r.timeout = 4
    r.lifetime = 8
    return r


def query(name: str, rtype: str) -> list[str]:
    r = _resolver()
    for tcp in (False, True):
        try:
            ans = r.resolve(name, rtype, tcp=tcp, raise_on_no_answer=False)
            out = []
            for rd in ans:
                if rtype == "TXT":
                    out.append(b"".join(rd.strings).decode("utf-8", "replace"))
                elif rtype == "MX":
                    host = str(rd.exchange).rstrip(".").lower()
                    if host:  # RFC 7505 null MX ("0 .") means the domain accepts no mail
                        out.append(host)
                else:
                    out.append(str(rd).rstrip(".").lower())
            return out
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return []
        except (dns.exception.Timeout, dns.resolver.LifetimeTimeout):
            continue
        except dns.exception.DNSException:
            return []
    return []


@dataclass
class DomainMail:
    domain: str
    mx: list[str] = field(default_factory=list)
    spf: str = ""
    dmarc: str = ""
    mailbox_provider: str = ""
    senders: list[str] = field(default_factory=list)
    tracking: dict[str, str] = field(default_factory=dict)  # subdomain -> tool


def mail_profile(domain: str, probe_tracking: bool = False) -> DomainMail:
    t = fp.load()
    dm = DomainMail(domain=domain)
    dm.mx = query(domain, "MX")
    txt = query(domain, "TXT")
    dm.spf = next((x for x in txt if x.lower().startswith("v=spf1")), "")
    dmarc = query(f"_dmarc.{domain}", "TXT")
    dm.dmarc = next((x for x in dmarc if x.lower().startswith("v=dmarc1")), "")
    for host in dm.mx:
        hit = fp.match_substr(host, t["mx"])
        if hit:
            dm.mailbox_provider = str(hit[0][1])
            break
    dm.senders = sorted({str(v) for _, v in fp.match_substr(dm.spf, t["spf_include"])})
    if probe_tracking:
        for sub in TRACKING_SUBS:
            cn = query(f"{sub}.{domain}", "CNAME")
            for target in cn:
                hit = fp.match_substr(target, t["tracking_cname"])
                if hit:
                    dm.tracking[f"{sub}.{domain}"] = str(hit[0][1])
    return dm


def stack_from_dns(domain: str, led: Ledger) -> dict:
    """TXT verification tokens + SPF + MX -> tools the company connected to its domain."""
    t = fp.load()
    txt = query(domain, "TXT")
    src = f"dns:TXT {domain}"
    tools: dict[str, str] = {}
    for rec in txt:
        for _, tool in fp.match_substr(rec, t["dns_txt"]):
            tools[str(tool)] = rec[:80]
        g = fp.generic_txt_vendor(rec)
        if g and not any(g in k.lower().replace(" ", "") for k in tools):
            tools[g.title()] = rec[:80]
    for tool, rec in tools.items():
        led.add("stack", f"{tool} verification token in DNS", src, "dig TXT (tcp fallback)",
                value=rec, confidence=0.85)
    prof = mail_profile(domain)
    if prof.mailbox_provider:
        led.add("stack", f"Mailbox provider: {prof.mailbox_provider}", f"dns:MX {domain}", "dig MX",
                value=prof.mx, confidence=0.95)
    for s in prof.senders:
        led.add("stack", f"Sends email through {s} (SPF include)", src, "SPF parse",
                value=prof.spf, confidence=0.9)
    return {
        "txt_records": len(txt),
        "tools_from_txt": sorted(tools),
        "mailbox_provider": prof.mailbox_provider,
        "spf_senders": prof.senders,
        "spf": prof.spf,
        "dmarc": prof.dmarc,
    }


def lookalike_candidates(domain: str) -> list[str]:
    d = net.normalize_domain(domain)
    s = net.stem(d)
    out: set[str] = set()
    for p in PREFIXES:
        for tld in TLDS_PREFIXED:
            out.add(f"{p}{s}.{tld}")
    for suf in SUFFIXES:
        for tld in TLDS_SUFFIXED:
            out.add(f"{s}{suf}.{tld}")
            out.add(f"{s}-{suf}.{tld}")
    for tld in ALT_TLDS:
        out.add(f"{s}.{tld}")
    out.discard(d)
    return sorted(out)


def _redirect_target(c, dom: str) -> str:
    for scheme in ("https", "http"):
        r = net.get(c, f"{scheme}://{dom}", retries=0)
        if r is not None:
            return net.normalize_domain(str(r.url))
    return ""


def outbound_forensics(domain: str, led: Ledger, workers: int = 24) -> dict:
    """Find lookalike domains that accept mail AND point back at the company."""
    d = net.normalize_domain(domain)
    cands = lookalike_candidates(d)
    with cf.ThreadPoolExecutor(workers) as ex:
        mx_map = dict(zip(cands, ex.map(lambda x: query(x, "MX"), cands)))
    with_mx = [x for x, mx in mx_map.items() if mx]

    owned: list[dict] = []
    with net.client() as c, cf.ThreadPoolExecutor(12) as ex:
        targets = dict(zip(with_mx, ex.map(lambda x: _redirect_target(c, x), with_mx)))
    for dom in with_mx:
        tgt = targets.get(dom, "")
        if tgt and (tgt == d or tgt.endswith("." + d)):
            prof = mail_profile(dom, probe_tracking=True)
            kind = "brand / legacy domain" if net.stem(dom) == net.stem(d) else "lookalike (cold-email pattern)"
            wired = bool(prof.mailbox_provider or prof.tracking)
            row = {
                "domain": dom,
                "kind": kind,
                "redirects_to": tgt,
                "mailbox_provider": prof.mailbox_provider,
                "spf_senders": prof.senders,
                "dmarc": bool(prof.dmarc),
                "tracking": prof.tracking,
                "wired_for_email": wired,
            }
            owned.append(row)
            what = "is wired for email" if wired else "has MX but no known mailbox provider"
            led.add("outbound", f"{dom} {what} and redirects to {d}", f"https://{dom}",
                    "MX lookup + HTTP redirect", value=row, confidence=0.9 if wired else 0.6)
            for sub, tool in prof.tracking.items():
                led.add("outbound", f"{sub} is a tracking domain for {tool}", f"dns:CNAME {sub}",
                        "CNAME fingerprint", value=tool, confidence=0.85)

    tools = sorted({tool for o in owned for tool in o["tracking"].values()})
    provider_counts: dict[str, int] = {}
    for o in owned:
        k = o["mailbox_provider"] or "unknown"
        provider_counts[k] = provider_counts.get(k, 0) + 1
    if owned:
        led.add("outbound", f"{len(owned)} secondary sending domains found for {d}",
                f"dns:MX {', '.join(o['domain'] for o in owned[:5])}", "aggregate",
                kind=INFERRED, value=len(owned), confidence=0.8)
    return {
        "candidates_checked": len(cands),
        "candidates_with_mx": len(with_mx),
        "owned_sending_domains": owned,
        "sending_tools_detected": tools,
        "mailbox_providers": provider_counts,
        "unowned_with_mx": [x for x in with_mx if x not in {o["domain"] for o in owned}],
    }
