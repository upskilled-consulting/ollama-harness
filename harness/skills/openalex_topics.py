"""
harness/skills/openalex_topics.py -- Curated OpenAlex topic registry.

OpenAlex replaced deprecated Concept IDs (C*) with Topics (T*) organized
in a 4-level hierarchy: domain > field > subfield > topic.

Works can carry multiple topics; primary_topic is the highest-scoring one.
Filter syntax:  primary_topic.id:T10047
Broader filter: primary_topic.subfield.id:subfields/2003  (all Finance topics)

Refresh topic lists with:
    python -m harness.skills.openalex_topics --domain finance
    python -m harness.skills.openalex_topics --list-subfields

Schema per entry:
    topic_id     str   -- OpenAlex short ID, e.g. "T10047"
    name         str   -- display name
    subfield     str   -- subfield display name
    field        str   -- field display name
    domain       str   -- research domain grouping used by this harness
    group        str   -- thematic cluster within the domain
    works_count  int   -- approximate works in OpenAlex (at time of curation)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOPICS: list[dict] = [

    # -----------------------------------------------------------------------
    # FINANCE domain
    # -----------------------------------------------------------------------

    # Core equity / factor / portfolio
    {   "topic_id": "T10047", "name": "Financial Markets and Investment Strategies",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "equity_factor", "works_count": 154117  },
    {   "topic_id": "T10282", "name": "Financial Risk and Volatility Modeling",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "risk_quant", "works_count": 58300  },
    {   "topic_id": "T10067", "name": "Stochastic Processes and Financial Applications",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "derivatives_quant", "works_count": 119964  },
    {   "topic_id": "T11976", "name": "Capital Investment and Risk Analysis",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "equity_factor", "works_count": 42903  },
    {   "topic_id": "T11326", "name": "Stock Market Forecasting Methods",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "ml_trading", "works_count": 82620  },

    # Credit / banking / regulation
    {   "topic_id": "T11496", "name": "Credit Risk and Financial Regulations",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "credit_banking", "works_count": 50228  },
    {   "topic_id": "T10127", "name": "Banking Stability, Regulation, Efficiency",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "credit_banking", "works_count": 168629  },

    # Sustainable / ESG
    {   "topic_id": "T13146", "name": "Sustainable Finance and Green Bonds",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "finance", "group": "esg", "works_count": 36323  },

    # Valuation / accounting
    {   "topic_id": "T12675", "name": "Financial Reporting and Valuation Research",
        "subfield": "Strategy and Management", "field": "Business, Management and Accounting",
        "domain": "finance", "group": "valuation", "works_count": 107626  },

    # -----------------------------------------------------------------------
    # MACRO domain
    # -----------------------------------------------------------------------

    {   "topic_id": "T10007", "name": "Monetary Policy and Economic Impact",
        "subfield": "Economics and Econometrics", "field": "Economics, Econometrics and Finance",
        "domain": "macro", "group": "monetary", "works_count": 150249  },
    {   "topic_id": "T14166", "name": "European Monetary and Fiscal Policies",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "macro", "group": "monetary", "works_count": 91704  },
    {   "topic_id": "T11770", "name": "Fiscal Policy and Economic Growth",
        "subfield": "Applied Economics", "field": "Economics, Econometrics and Finance",
        "domain": "macro", "group": "fiscal", "works_count": 169197  },
    {   "topic_id": "T10503", "name": "Global Financial Crisis and Policies",
        "subfield": "Finance", "field": "Economics, Econometrics and Finance",
        "domain": "macro", "group": "systemic_risk", "works_count": 186007  },

]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def by_domain(domain: str) -> list[dict]:
    """Return all topics for a given harness domain."""
    return [t for t in TOPICS if t["domain"] == domain]


def by_group(group: str) -> list[dict]:
    """Return all topics for a given thematic group."""
    return [t for t in TOPICS if t["group"] == group]


def topic_ids(domain: str, groups: list[str] | None = None) -> list[str]:
    """Return bare topic IDs for a domain, optionally filtered by group."""
    entries = by_domain(domain)
    if groups:
        entries = [t for t in entries if t["group"] in groups]
    return [t["topic_id"] for t in entries]


def openalex_filter(domain: str, groups: list[str] | None = None,
                    primary_only: bool = True) -> str:
    """
    Build an OpenAlex OR filter string for a domain's topic IDs.
    primary_only=True uses primary_topic.id (faster, more precise).
    primary_only=False uses topics.id (catches non-primary topic tags too).
    """
    ids = topic_ids(domain, groups)
    if not ids:
        return ""
    field = "primary_topic.id" if primary_only else "topics.id"
    # OpenAlex supports pipe-separated OR within a single filter value
    return f"{field}:{'|'.join(ids)}"


# ---------------------------------------------------------------------------
# CLI -- refresh / explore
# ---------------------------------------------------------------------------

def _search_topics(query: str, n: int = 10) -> list[dict]:
    import requests
    r = requests.get("https://api.openalex.org/topics",
        params={"search": query, "per-page": n, "mailto": "nickmccarty0@gmail.com"},
        timeout=15)
    return r.json().get("results", []) if r.ok else []


def _list_subfield(subfield_id: str, n: int = 30) -> list[dict]:
    import time

    import requests
    results = []
    for page in range(1, 5):
        r = requests.get("https://api.openalex.org/topics",
            params={"filter": f"subfield.id:{subfield_id}", "per-page": 50,
                    "page": page, "mailto": "nickmccarty0@gmail.com"}, timeout=15)
        batch = r.json().get("results", [])
        if not batch:
            break
        results.extend(batch)
        time.sleep(0.25)
    return sorted(results, key=lambda x: -x.get("works_count", 0))[:n]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="OpenAlex topic registry explorer")
    ap.add_argument("--domain",         help="Show topics for harness domain (finance, macro, health)")
    ap.add_argument("--search",         help="Search OpenAlex topics by keyword")
    ap.add_argument("--subfield",       help="List all topics for a subfield ID (e.g. subfields/2003)")
    ap.add_argument("--filter",         help="Print OpenAlex filter string for a domain",
                    metavar="DOMAIN")
    ap.add_argument("--n", type=int,    default=20)
    args = ap.parse_args()

    if args.domain:
        entries = by_domain(args.domain)
        print(f"\n{args.domain} topics ({len(entries)}):")
        print(f"  {'ID':<8} {'Group':<20} {'Works':>8}  Name")
        print("  " + "-"*80)
        for t in entries:
            print(f"  {t['topic_id']:<8} {t['group']:<20} {t['works_count']:>8}  {t['name']}")

    if args.filter:
        filt = openalex_filter(args.filter)
        print(f"\nOpenAlex filter for domain={args.filter!r}:")
        print(f"  {filt}")

    if args.search:
        results = _search_topics(args.search, args.n)
        print(f"\nSearch results for {args.search!r}:")
        print(f"  {'ID':<8} {'Subfield':<30} {'Works':>8}  Name")
        print("  " + "-"*80)
        for t in results:
            tid = t["id"].split("/")[-1]
            sf  = t.get("subfield", {}).get("display_name", "")
            print(f"  {tid:<8} {sf:<30} {t['works_count']:>8}  {t['display_name']}")

    if args.subfield:
        results = _list_subfield(args.subfield, args.n)
        print(f"\nSubfield {args.subfield} topics (top {args.n}):")
        print(f"  {'ID':<8} {'Works':>8}  Name")
        print("  " + "-"*70)
        for t in results:
            tid = t["id"].split("/")[-1]
            print(f"  {tid:<8} {t['works_count']:>8}  {t['display_name']}")


if __name__ == "__main__":
    main()
