"""
harness/osint_tool.py — OSINT enrichment layer for research tasks.

Layers (degrade gracefully when keys / deps are absent):

  Zero-config   DNS records, HTTP headers, robots.txt, security.txt,
                RDAP registration, crt.sh subdomains, Wayback first-seen,
                Shodan internetdb (free, no key)
  IPINFO_TOKEN  Richer IP geo / ASN (free tier works without key too)
  URLSCAN_API_KEY  Tech-stack fingerprinting via Wappalyzer, screenshot URL
  OTX_API_KEY   Passive DNS history, AlienVault threat pulse count

Citation format: [OSINT:{SOURCE}:{target}:{YYYY-MM-DD}]

Usage (smoke-test):
    python -m harness.osint_tool example.com
    python -m harness.osint_tool 1.1.1.1
    python -m harness.osint_tool --dorks "open source LLM security benchmarks"
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

_TIMEOUT = 10  # seconds per HTTP call
_TODAY   = ""  # filled lazily


def _today() -> str:
    global _TODAY
    if not _TODAY:
        _TODAY = datetime.now(UTC).strftime("%Y-%m-%d")
    return _TODAY


# ---------------------------------------------------------------------------
# Key helpers — same pattern as fred_tool
# ---------------------------------------------------------------------------

_KEYS: dict[str, str] = {}


def _key(env_var: str) -> str:
    if env_var in _KEYS:
        return _KEYS[env_var]
    try:
        from harness.config import ROOT as _ROOT
        _env = _ROOT / ".env"
        if _env.exists():
            for line in _env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == env_var:
                        _KEYS[env_var] = v.strip()
                        return _KEYS[env_var]
    except Exception:
        pass
    val = os.environ.get(env_var, "")
    _KEYS[env_var] = val
    return val


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str, headers: dict[str, str] | None = None,
         timeout: int = _TIMEOUT) -> dict | str:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                return json.loads(body)
            return body
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {url}") from e
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {url}") from e


# ---------------------------------------------------------------------------
# Target detection
# ---------------------------------------------------------------------------

_IP_RE     = re.compile(r'\b((?:\d{1,3}\.){3}\d{1,3})\b')
_EMAIL_RE  = re.compile(r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b')
# Domain: looks like a hostname with a known-ish TLD, not an IP
_DOMAIN_RE = re.compile(
    r'\b((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)'
    r'+(?:com|org|net|io|co|gov|edu|uk|de|fr|jp|au|ca|nl|se|'
    r'dev|ai|tech|app|info|biz|me|tv|us|eu|xyz|online|site|'
    r'cloud|data|finance|research|media))\b'
)
# Person name: two consecutive title-case words (avoid org-name false positives)
_NAME_RE   = re.compile(r'\b([A-Z][a-z]{1,20})\s+([A-Z][a-z]{1,30})\b')
_NAME_STOP = frozenset({"Inc", "Ltd", "Corp", "Llc", "Publishing", "Company", "Group",
                        "Institute", "University", "College", "Department", "School"})

_OSINT_KEYWORDS = frozenset({
    "domain", "website", "whois", "registrar", "subdomain", "dns",
    "ip address", "infrastructure", "server", "hosting", "network",
    "security", "vulnerability", "breach", "threat", "malware",
    "certificate", "ssl", "tls", "company", "organization", "org",
    "corporate", "founded", "headquarters", "registered",
})


def _detect_targets(text: str) -> dict[str, list[str]]:
    """Extract unique IPs, domains, emails, and person names from free text."""
    ips     = list(dict.fromkeys(_IP_RE.findall(text)))
    emails  = list(dict.fromkeys(_EMAIL_RE.findall(text)))
    raw_domains = _DOMAIN_RE.findall(text)
    ip_set  = set(ips)
    domains = list(dict.fromkeys(
        d for d in raw_domains
        if d not in ip_set and not d.startswith("192.") and len(d) > 4
    ))
    for em in emails:
        domain = em.split("@", 1)[1]
        if domain not in domains:
            domains.append(domain)
    # Person names: title-case bigrams, excluding org-name stop words
    names = list(dict.fromkeys(
        f"{a} {b}" for a, b in _NAME_RE.findall(text)
        if b not in _NAME_STOP and a not in _NAME_STOP
    ))
    return {"domains": domains[:5], "ips": ips[:5], "emails": emails[:5], "names": names[:3]}


def _osint_themes(query: str) -> list[str]:
    """Return matched OSINT theme keywords — used as intent gate in gather_research."""
    lower = query.lower()
    found = [kw for kw in _OSINT_KEYWORDS if kw in lower]
    # Always fires if a URL / domain / IP is detectable
    targets = _detect_targets(query)
    if targets["domains"] or targets["ips"]:
        if "domain" not in found:
            found.append("domain")
    return found


# ---------------------------------------------------------------------------
# Layer 1: DNS records (stdlib socket + optional dnspython)
# ---------------------------------------------------------------------------

def _dns_lookup(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "DNS"}
    # A record via stdlib (always available)
    try:
        infos = socket.getaddrinfo(domain, None)
        ips = list(dict.fromkeys(i[4][0] for i in infos))
        result["a_records"] = ips
    except Exception:
        result["a_records"] = []

    # MX / NS / TXT via dnspython (optional)
    try:
        import dns.resolver as _res  # type: ignore[import-not-found]
        for rtype in ("MX", "NS", "TXT"):
            try:
                answers = _res.resolve(domain, rtype, lifetime=5)
                if rtype == "MX":
                    result["mx"] = [str(r.exchange).rstrip(".") for r in answers]
                elif rtype == "NS":
                    result["ns"] = [str(r).rstrip(".") for r in answers]
                elif rtype == "TXT":
                    txts = [b"".join(r.strings).decode("utf-8", errors="replace")
                            for r in answers]
                    result["txt"] = txts
                    # Parse security flags from TXT
                    all_txt = " ".join(txts).lower()
                    result["spf"]   = "v=spf1"  in all_txt
                    result["dmarc"] = "v=dmarc1" in all_txt
            except Exception:
                pass
    except ImportError:
        pass  # dnspython not installed — A record only

    return result


# ---------------------------------------------------------------------------
# Layer 2: HTTP metadata — headers, robots.txt, security.txt
# ---------------------------------------------------------------------------

def _http_meta(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "HTTP"}
    base = f"https://{domain}"

    # HEAD request for response headers
    try:
        req = urllib.request.Request(base, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            h = dict(resp.headers)
            result["server"]  = h.get("Server") or h.get("server", "")
            result["powered"] = h.get("X-Powered-By") or h.get("x-powered-by", "")
            result["hsts"]    = bool(h.get("Strict-Transport-Security") or
                                     h.get("strict-transport-security"))
            result["csp"]     = bool(h.get("Content-Security-Policy") or
                                     h.get("content-security-policy"))
            result["status"]  = resp.status
    except Exception:
        pass

    # robots.txt
    try:
        robots = _get(f"{base}/robots.txt", timeout=6)
        if isinstance(robots, str) and "user-agent" in robots.lower():
            disallowed = re.findall(r"(?i)^Disallow:\s*(.+)$", robots, re.MULTILINE)
            result["robots_disallowed"] = disallowed[:10]
    except Exception:
        pass

    # security.txt
    for path in ("/.well-known/security.txt", "/security.txt"):
        try:
            sec = _get(f"{base}{path}", timeout=5)
            if isinstance(sec, str) and "contact:" in sec.lower():
                result["security_txt"] = True
                contacts = re.findall(r"(?i)^Contact:\s*(.+)$", sec, re.MULTILINE)
                result["security_contact"] = contacts[:2]
                break
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Layer 3: RDAP (modern WHOIS replacement — JSON, free, no key)
# ---------------------------------------------------------------------------

def _rdap_lookup(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "RDAP"}
    try:
        data = _get(f"https://rdap.org/domain/{urllib.parse.quote(domain)}")
        if not isinstance(data, dict):
            return result

        result["status"] = data.get("status", [])

        # Registrant name / org
        for entity in data.get("entities", []):
            roles = entity.get("roles", [])
            vcard = entity.get("vcardArray", [None, []])[1]
            name  = next((v[3] for v in vcard if v[0] == "fn"),  "") if vcard else ""
            org   = next((v[3] for v in vcard if v[0] == "org"), "") if vcard else ""
            if "registrant" in roles:
                result["registrant"] = name or org
            if "registrar" in roles:
                result["registrar"] = name or org

        # Events: registration / expiration / last changed
        for ev in data.get("events", []):
            action = ev.get("eventAction", "")
            date   = ev.get("eventDate", "")[:10]
            if action == "registration":
                result["registered"] = date
            elif action == "expiration":
                result["expires"] = date
            elif action == "last changed":
                result["updated"] = date

        # Name servers
        result["nameservers"] = [
            ns.get("ldhName", "").lower()
            for ns in data.get("nameservers", [])
        ]
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Layer 4: Certificate Transparency — crt.sh (free, no key)
# ---------------------------------------------------------------------------

def _crt_sh(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "crt.sh"}
    try:
        url  = f"https://crt.sh/?q=%.{urllib.parse.quote(domain)}&output=json"
        data = _get(url, timeout=15)
        if not isinstance(data, list):
            return result

        result["cert_count"] = len(data)

        # Unique subdomains from common_name + name_value
        subs: set[str] = set()
        orgs: set[str] = set()
        dates = []
        for cert in data:
            for field in ("common_name", "name_value"):
                val = cert.get(field, "")
                for name in val.split("\n"):
                    name = name.strip().lstrip("*.")
                    if name.endswith(f".{domain}") or name == domain:
                        subs.add(name)
            org = cert.get("issuer_o") or ""
            if org:
                orgs.add(org)
            issued = cert.get("not_before", "")[:10]
            if issued:
                dates.append(issued)

        result["subdomains"]   = sorted(subs)[:20]
        result["issuers"]      = sorted(orgs)
        result["first_cert"]   = min(dates) if dates else ""
        result["latest_cert"]  = max(dates) if dates else ""

        # Org name from subject (often the legal entity name)
        orgs_sub: set[str] = set()
        for cert in data[:50]:
            o = cert.get("subject_o") or ""
            if o and len(o) > 2:
                orgs_sub.add(o)
        result["subject_orgs"] = sorted(orgs_sub)[:5]

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Layer 5: Wayback Machine CDX API (free, no key)
# ---------------------------------------------------------------------------

def _wayback(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "Wayback"}
    try:
        # First snapshot
        url_first = (
            f"http://web.archive.org/cdx/search/cdx"
            f"?url={urllib.parse.quote(domain)}&output=json"
            f"&limit=1&fl=timestamp&from=&to="
        )
        data = _get(url_first, timeout=10)
        if isinstance(data, list) and len(data) > 1:
            ts = data[1][0]  # data[0] is the header row
            result["first_seen"] = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"

        # Snapshot count
        url_count = (
            f"http://web.archive.org/cdx/search/cdx"
            f"?url={urllib.parse.quote(domain)}&output=json&fl=timestamp&limit=5000"
        )
        count_data = _get(url_count, timeout=12)
        if isinstance(count_data, list):
            result["snapshot_count"] = max(0, len(count_data) - 1)

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Layer 6: IP info — ipinfo.io (free tier works without key; IPINFO_TOKEN unlocks more)
# ---------------------------------------------------------------------------

def _ip_info(ip: str) -> dict:
    result: dict[str, Any] = {"ip": ip, "source": "ipinfo.io"}
    token = _key("IPINFO_TOKEN")
    url   = f"https://ipinfo.io/{ip}/json"
    if token:
        url += f"?token={token}"
    try:
        data = _get(url, timeout=8)
        if not isinstance(data, dict):
            return result
        result.update({
            "hostname": data.get("hostname", ""),
            "city":     data.get("city", ""),
            "region":   data.get("region", ""),
            "country":  data.get("country", ""),
            "org":      data.get("org", ""),      # "AS13335 Cloudflare, Inc."
            "asn":      data.get("org", "").split()[0] if data.get("org") else "",
            "timezone": data.get("timezone", ""),
        })
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Layer 7: Shodan internetdb — completely free, no key required
# ---------------------------------------------------------------------------

def _shodan_free(ip: str) -> dict:
    result: dict[str, Any] = {"ip": ip, "source": "Shodan-free"}
    try:
        data = _get(f"https://internetdb.shodan.io/{ip}", timeout=8)
        if not isinstance(data, dict):
            return result
        result["ports"]     = data.get("ports", [])
        result["vulns"]     = data.get("vulns", [])
        result["hostnames"] = data.get("hostnames", [])
        result["tags"]      = data.get("tags", [])
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Layer 8: urlscan.io — tech stack / Wappalyzer (URLSCAN_API_KEY required)
# ---------------------------------------------------------------------------

def _urlscan(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "urlscan.io"}
    api_key = _key("URLSCAN_API_KEY")
    if not api_key:
        return result
    try:
        url  = f"https://urlscan.io/api/v1/search/?q=domain:{urllib.parse.quote(domain)}&size=1"
        data = _get(url, headers={"API-Key": api_key}, timeout=12)
        if not isinstance(data, dict):
            return result
        results = data.get("results", [])
        if not results:
            return result
        hit  = results[0]
        page = hit.get("page", {})
        task = hit.get("task", {})
        result["screenshot_url"] = task.get("screenshotURL", "")
        result["scan_url"]       = hit.get("result", "")
        result["server"]         = page.get("server", "")
        result["country"]        = page.get("country", "")
        result["ip"]             = page.get("ip", "")
        result["asn"]            = page.get("asn", "")
        result["asnname"]        = page.get("asnname", "")
        # Tech stack from Wappalyzer
        tech = hit.get("stats", {}).get("wappalyzerCounts", {})
        result["technologies"]   = list(tech.keys()) if tech else []
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Layer 9: OTX AlienVault — passive DNS, threat pulses (OTX_API_KEY required)
# ---------------------------------------------------------------------------

def _otx(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "OTX"}
    api_key = _key("OTX_API_KEY")
    if not api_key:
        return result
    headers = {"X-OTX-API-KEY": api_key}
    try:
        base = f"https://otx.alienvault.com/api/v1/indicators/domain/{urllib.parse.quote(domain)}"
        gen  = _get(f"{base}/general", headers=headers, timeout=10)
        if isinstance(gen, dict):
            result["pulse_count"]  = gen.get("pulse_info", {}).get("count", 0)
            result["malicious"]    = gen.get("pulse_info", {}).get("count", 0) > 0
            result["industry"]     = gen.get("industry", "")
            result["alexa_rank"]   = gen.get("alexa", "")
            result["whois_org"]    = gen.get("whois", {}).get("Organization", "") if isinstance(gen.get("whois"), dict) else ""
        # Passive DNS — last 5 resolutions
        pdns = _get(f"{base}/passive_dns", headers=headers, timeout=10)
        if isinstance(pdns, dict):
            entries = pdns.get("passive_dns", [])[:5]
            result["passive_dns"] = [
                {"address": e.get("address", ""), "first": e.get("first", "")[:10]}
                for e in entries
            ]
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Layer 10: Semantic Scholar person search (free, no key required)
# ---------------------------------------------------------------------------

def _semantic_scholar_person(name: str) -> dict:
    result: dict[str, Any] = {"name": name, "source": "SemanticScholar"}
    try:
        from harness.config import settings as _s
        api_key = _s.semantic_scholar_api_key or os.environ.get("S2_API_KEY", "")
        headers: dict[str, str] = {}
        if api_key:
            headers["x-api-key"] = api_key
        url = (
            "https://api.semanticscholar.org/graph/v1/author/search"
            f"?query={urllib.parse.quote(name)}"
            "&fields=name,affiliations,paperCount,citationCount,papers.title,papers.year"
            "&limit=3"
        )
        data = _get(url, headers=headers, timeout=10)
        if not isinstance(data, dict):
            return result
        authors = data.get("data", [])
        if not authors:
            result["found"] = False
            return result
        top = authors[0]
        result["found"]        = True
        result["s2_name"]      = top.get("name", "")
        result["paper_count"]  = top.get("paperCount", 0)
        result["citation_count"] = top.get("citationCount", 0)
        affs = top.get("affiliations", [])
        result["affiliations"] = [a.get("name", "") for a in affs if a.get("name")]
        papers = top.get("papers", [])
        result["recent_papers"] = [
            {"title": p.get("title", ""), "year": p.get("year")}
            for p in sorted(papers, key=lambda p: p.get("year") or 0, reverse=True)[:5]
        ]
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Layer 11: HaveIBeenPwned domain breach check (HIBP_API_KEY required)
# ---------------------------------------------------------------------------

def _hibp_domain(domain: str) -> dict:
    result: dict[str, Any] = {"domain": domain, "source": "HIBP"}
    api_key = _key("HIBP_API_KEY")
    if not api_key:
        return result
    try:
        url  = f"https://haveibeenpwned.com/api/v3/breacheddomain/{urllib.parse.quote(domain)}"
        data = _get(url, headers={"hibp-api-key": api_key, "User-Agent": "harness-osint/1.0"},
                    timeout=10)
        if isinstance(data, dict):
            result["breach_count"] = len(data)
            result["breaches"] = [
                {"name": k, "emails": v[:3]} for k, v in list(data.items())[:5]
            ]
        elif isinstance(data, list):
            result["breach_count"] = len(data)
    except RuntimeError as e:
        if "HTTP 404" in str(e):
            result["breach_count"] = 0  # clean domain
        # other errors fall through silently
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def _fmt_dns(d: dict, domain: str) -> list[str]:
    lines = []
    if d.get("a_records"):
        lines.append(f"A: {', '.join(d['a_records'][:4])}")
    if d.get("mx"):
        lines.append(f"MX: {', '.join(d['mx'][:3])}")
    if d.get("ns"):
        lines.append(f"NS: {', '.join(d['ns'][:3])}")
    if d.get("spf") is not None:
        flags = []
        if d.get("spf"):   flags.append("SPF ✓")
        else:              flags.append("SPF ✗")
        if d.get("dmarc"): flags.append("DMARC ✓")
        else:              flags.append("DMARC ✗")
        lines.append("Email auth: " + "  ".join(flags))
    return lines


def _fmt_brief(target: str, results: dict, is_domain: bool) -> str:
    today   = _today()
    def cite(src): return f"[OSINT:{src}:{target}:{today}]"
    blocks  = [f"### OSINT Brief: `{target}`\n"]

    if is_domain:
        # --- Registration ---
        rdap = results.get("rdap", {})
        if rdap.get("registrant") or rdap.get("registered"):
            parts = []
            if rdap.get("registrant"):
                parts.append(f"Registrant: **{rdap['registrant']}**")
            if rdap.get("registrar"):
                parts.append(f"Registrar: {rdap['registrar']}")
            if rdap.get("registered"):
                parts.append(f"Registered: {rdap['registered']}")
            if rdap.get("expires"):
                parts.append(f"Expires: {rdap['expires']}")
            blocks.append("**Registration** " + cite("RDAP") + "  \n" + "  \n".join(parts))

        # --- DNS ---
        dns = results.get("dns", {})
        dns_lines = _fmt_dns(dns, target)
        if dns_lines:
            blocks.append("**DNS** " + cite("DNS") + "  \n" + "  \n".join(dns_lines))

        # --- HTTP metadata ---
        http = results.get("http", {})
        if http:
            parts = []
            if http.get("server"):
                parts.append(f"Server: `{http['server']}`")
            if http.get("powered"):
                parts.append(f"X-Powered-By: `{http['powered']}`")
            flags = []
            if http.get("hsts"): flags.append("HSTS ✓")
            if http.get("csp"):  flags.append("CSP ✓")
            if flags:
                parts.append("Security headers: " + "  ".join(flags))
            if http.get("security_txt"):
                parts.append(f"security.txt: ✓  ({', '.join(http.get('security_contact', []))})")
            if http.get("robots_disallowed"):
                parts.append(f"robots.txt disallowed: {', '.join(http['robots_disallowed'][:5])}")
            if parts:
                blocks.append("**HTTP / Web** " + cite("HEADERS") + "  \n" + "  \n".join(parts))

        # --- Certificates ---
        crt = results.get("crt", {})
        if crt.get("cert_count"):
            parts = [f"{crt['cert_count']} certs issued"]
            if crt.get("first_cert"):
                parts.append(f"first: {crt['first_cert']}")
            if crt.get("subject_orgs"):
                parts.append(f"Org in cert: {', '.join(crt['subject_orgs'][:2])}")
            if crt.get("subdomains"):
                parts.append(f"Subdomains found ({len(crt['subdomains'])}): "
                             f"{', '.join(crt['subdomains'][:8])}"
                             + (" ..." if len(crt['subdomains']) > 8 else ""))
            blocks.append("**Certificates (crt.sh)** " + cite("CRTS") + "  \n" + "  \n".join(parts))

        # --- Wayback ---
        wb = results.get("wayback", {})
        if wb.get("first_seen") or wb.get("snapshot_count"):
            parts = []
            if wb.get("first_seen"):
                parts.append(f"First indexed: {wb['first_seen']}")
            if wb.get("snapshot_count"):
                parts.append(f"Total snapshots: {wb['snapshot_count']:,}")
            blocks.append("**Web Archive** " + cite("WAYBACK") + "  \n" + "  \n".join(parts))

        # --- urlscan.io ---
        us = results.get("urlscan", {})
        if us.get("technologies") or us.get("asnname"):
            parts = []
            if us.get("technologies"):
                parts.append(f"Tech stack: {', '.join(us['technologies'][:10])}")
            if us.get("asnname"):
                parts.append(f"Hosted on: {us['asnname']}")
            if us.get("country"):
                parts.append(f"Server country: {us['country']}")
            if us.get("screenshot_url"):
                parts.append(f"Screenshot: {us['screenshot_url']}")
            blocks.append("**Tech Stack (urlscan.io)** " + cite("URLSCAN") + "  \n" + "  \n".join(parts))

        # --- OTX ---
        otx = results.get("otx", {})
        if otx.get("pulse_count") is not None:
            parts = []
            pc = otx.get("pulse_count", 0)
            parts.append(f"Threat pulses: {pc} {'⚠ flagged by threat feeds' if pc else '(clean)'}")
            if otx.get("alexa_rank"):
                parts.append(f"Alexa rank: {otx['alexa_rank']}")
            if otx.get("passive_dns"):
                pdns = otx["passive_dns"]
                parts.append(f"Passive DNS ({len(pdns)} recent): "
                             f"{', '.join(e['address'] for e in pdns)}")
            blocks.append("**Threat Intel (OTX)** " + cite("OTX") + "  \n" + "  \n".join(parts))

        # --- HIBP domain breach ---
        hibp = results.get("hibp", {})
        if "breach_count" in hibp:
            bc = hibp["breach_count"]
            parts = [f"Domain breach exposure: {bc} breach(es) {'⚠' if bc else '(clean)'}"]
            for b in hibp.get("breaches", []):
                parts.append(f"  • {b['name']}: {len(b['emails'])} sample address(es)")
            blocks.append("**Breach Check (HIBP)** " + cite("HIBP") + "  \n" + "  \n".join(parts))

        # --- Semantic Scholar (per name associated with domain) ---
        s2 = results.get("s2_person", {})
        if s2.get("found") is not None:
            if s2["found"]:
                parts = [f"Author: **{s2.get('s2_name', '')}**  "
                         f"({s2.get('paper_count', 0)} papers, "
                         f"{s2.get('citation_count', 0)} citations)"]
                if s2.get("affiliations"):
                    parts.append(f"Affiliations: {', '.join(s2['affiliations'][:3])}")
                for p in s2.get("recent_papers", [])[:3]:
                    parts.append(f"  • ({p.get('year', '?')}) {p['title'][:80]}")
                blocks.append("**Academic Profile (Semantic Scholar)** " + cite("S2") + "  \n" + "  \n".join(parts))
            else:
                blocks.append("**Academic Profile (Semantic Scholar)** " + cite("S2") + "  \n"
                              + f"No author record found for '{s2.get('name', '')}'")

    else:
        # IP target
        ipi = results.get("ipinfo", {})
        if ipi:
            parts = []
            if ipi.get("org"):
                parts.append(f"Org/ASN: {ipi['org']}")
            loc = ", ".join(filter(None, [ipi.get("city"), ipi.get("region"), ipi.get("country")]))
            if loc:
                parts.append(f"Location: {loc}")
            if ipi.get("hostname"):
                parts.append(f"Hostname: {ipi['hostname']}")
            if parts:
                blocks.append("**IP Info** " + cite("IPINFO") + "  \n" + "  \n".join(parts))

        sh = results.get("shodan", {})
        if sh.get("ports") or sh.get("vulns"):
            parts = []
            if sh.get("ports"):
                parts.append(f"Open ports: {sh['ports']}")
            if sh.get("vulns"):
                parts.append(f"Known CVEs: {', '.join(sh['vulns'][:5])}")
            if sh.get("tags"):
                parts.append(f"Tags: {', '.join(sh['tags'])}")
            blocks.append("**Port / Vuln Scan (Shodan free)** " + cite("SHODAN") + "  \n" + "  \n".join(parts))

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Dork query generation (LLM call)
# ---------------------------------------------------------------------------

def generate_dork_queries(task: str, model: str | None = None, n: int = 3) -> list[str]:
    """
    Use the producer model to generate n targeted search queries with
    advanced operators (site:, filetype:, intitle:, "exact phrase").
    Returns [] if the model call fails.
    """
    try:
        import ollama as _ollama  # type: ignore[import-not-found]
    except ImportError:
        return []

    if model is None:
        model = os.environ.get("HARNESS_PRODUCER_MODEL", "")
    if not model:
        return []

    prompt = (
        f"Generate {n} targeted web search queries for the following research task.\n"
        "Use advanced search operators where useful: site:, filetype:pdf, intitle:, "
        'inurl:, "exact phrase". Focus on authoritative primary sources, official '
        "documentation, datasets, and recent publications.\n\n"
        f"Task: {task}\n\n"
        "Output ONLY the queries, one per line, no numbering, no explanation."
    )
    try:
        resp = _ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_predict": 128},
        )
        raw = resp["message"].get("content", "").strip()
        queries = [q.strip().strip('"') for q in raw.splitlines() if q.strip()]
        return queries[:n]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def query_osint(
    task: str,
    *,
    max_domains: int = 2,
    max_ips: int = 2,
) -> tuple[str, list[str]]:
    """
    Detect targets in `task`, fetch all available OSINT layers in parallel,
    format as a markdown block, and return (enrichment_block, dork_queries).

    enrichment_block is "" when no targets are found or all fetches fail.
    dork_queries is always [] (caller must separately invoke generate_dork_queries).
    """
    targets = _detect_targets(task)
    domains = targets["domains"][:max_domains]
    ips     = targets["ips"][:max_ips]
    names   = targets.get("names", [])

    if not domains and not ips:
        return "", []

    sections: list[str] = []
    today    = _today()

    with ThreadPoolExecutor(max_workers=10) as pool:
        for domain in domains:
            futs = {
                "rdap":    pool.submit(_rdap_lookup, domain),
                "dns":     pool.submit(_dns_lookup,  domain),
                "http":    pool.submit(_http_meta,   domain),
                "crt":     pool.submit(_crt_sh,      domain),
                "wayback": pool.submit(_wayback,     domain),
                "urlscan": pool.submit(_urlscan,     domain),
                "otx":     pool.submit(_otx,         domain),
                "hibp":    pool.submit(_hibp_domain, domain),
            }
            # Semantic Scholar person search — use first detected name
            if names:
                futs["s2_person"] = pool.submit(_semantic_scholar_person, names[0])
            results: dict[str, dict] = {}
            for name, fut in futs.items():
                try:
                    results[name] = fut.result(timeout=25)
                except Exception:
                    results[name] = {}

            # Resolve A records → enrich first IP with ipinfo + shodan
            a_records = results.get("dns", {}).get("a_records", [])
            if a_records:
                ip = a_records[0]
                ip_futs = {
                    "ipinfo": pool.submit(_ip_info,     ip),
                    "shodan": pool.submit(_shodan_free, ip),
                }
                for name, fut in ip_futs.items():
                    try:
                        results[name] = fut.result(timeout=12)
                    except Exception:
                        results[name] = {}

            brief = _fmt_brief(domain, results, is_domain=True)
            if brief.strip():
                sections.append(brief)

        for ip in ips:
            ip_results = {}
            ip_futs = {
                "ipinfo": pool.submit(_ip_info,     ip),
                "shodan": pool.submit(_shodan_free, ip),
            }
            for name, fut in ip_futs.items():
                try:
                    ip_results[name] = fut.result(timeout=12)
                except Exception:
                    ip_results[name] = {}

            brief = _fmt_brief(ip, ip_results, is_domain=False)
            if brief.strip():
                sections.append(brief)

    if not sections:
        return "", []

    header = f"## OSINT Enrichment  *(retrieved {today})*\n"
    block  = header + "\n---\n".join(sections)
    return block, []


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OSINT tool smoke-test")
    parser.add_argument("target", nargs="?", help="Domain or IP to query")
    parser.add_argument("--dorks", metavar="TASK",
                        help="Generate dork queries for a task string")
    args = parser.parse_args()

    if args.dorks:
        model = os.environ.get("HARNESS_PRODUCER_MODEL", "")
        qs    = generate_dork_queries(args.dorks, model=model, n=4)
        print("Dork queries:")
        for q in qs:
            print(f"  {q}")
        sys.exit(0)

    if not args.target:
        parser.print_help()
        sys.exit(1)

    print(f"[osint] querying: {args.target}\n")
    t0    = time.monotonic()
    block, _ = query_osint(args.target)
    elapsed  = round(time.monotonic() - t0, 1)
    print(block or "(no data returned)")
    print(f"\n[osint] done in {elapsed}s")
