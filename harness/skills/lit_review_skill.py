"""
lit_review_skill.py — /lit-review standalone skill.

Pipeline
--------
  1. Fetch       arxiv_fetch.py         -> raw paper CSV
  2. Enrich      semantic_scholar.py    -> add hub_score, ref_count, gap_candidates
  3. Curate      curator.py             -> persona filter (drop weak papers)
  4. Annotate    nanda-annotator-v2-q4km:latest per paper + wiggum_annotate_loop
  5. Cluster     LLM groups papers into 3-5 thematic clusters
  6. Synthesize  LLM writes cluster summaries + cross-cluster synthesis + open questions
  7. Render      Jinja2 template -> .md output

Usage (via agent.py)
--------------------
    python agent.py "/lit-review agentic LLM harness engineering save to review.md"
    python agent.py "/lit-review --after 2024-06-01 --max-fetch 200 --max-annotate 30 prompt injection save to review.md"
    python agent.py "/lit-review --template gaps --csv existing.csv save to gaps.md"
    python agent.py "/lit-review --template executive --no-fetch --csv papers.csv save to exec.md"

Standalone
----------
    python lit_review_skill.py "agentic LLM" --max-annotate 20 --out review.md
    python lit_review_skill.py --csv arxiv_agentic_papers.csv --no-fetch --out review.md
    python lit_review_skill.py --csv papers.csv --no-fetch --no-curate --max-annotate 10 --out review.md

Options
-------
    --max-fetch N       Papers to fetch from arXiv (default: 100)
    --max-annotate N    Papers to annotate, after curation (default: 20)
    --after DATE        arXiv date filter YYYY-MM-DD
    --before DATE       arXiv date filter YYYY-MM-DD
    --csv FILE          Use existing CSV instead of fetching (skips fetch step)
    --no-fetch          Alias for --csv with an existing file
    --no-curate         Skip persona curation step
    --no-wiggum         Skip wiggum evaluation on annotations
    --no-s2             Skip Semantic Scholar enrichment
    --template NAME     Jinja template name: survey (default), gaps, executive
    --producer MODEL    Ollama model for annotation (default: PRODUCER_MODEL env var)
    --evaluator MODEL   Ollama model for wiggum eval (default: EVALUATOR_MODEL env var)
    --out FILE          Output markdown path
    --checkpoint DIR    Directory for per-paper annotation checkpoints (default: .lit_review_cache/)
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from harness.inference import chat as _llm_chat

HERE             = Path(__file__).parent

from contextlib import contextmanager


@contextmanager
def _nullctx():
    yield
TEMPLATES_DIR    = HERE / "templates"
CHECKPOINT_DIR   = HERE / ".lit_review_cache"

DEFAULT_MAX_FETCH      = 100
DEFAULT_MAX_ANNOTATE   = 20
DEFAULT_AFTER_YEARS    = 2      # default recency window; pass after="" to disable
DEFAULT_MAX_KEEP       = 60     # TF-IDF top-N after fetching DEFAULT_MAX_FETCH
DEFAULT_ANNOTATE_PARALLEL = 2   # match llama-server --parallel N
DEFAULT_TEMPLATE     = "survey"
DEFAULT_PRODUCER     = os.environ.get("PRODUCER_MODEL", "pi-qwen-32b")
DEFAULT_EVALUATOR    = os.environ.get("EVALUATOR_MODEL", "Qwen3-Coder:30b")
DEFAULT_CLUSTER_MODEL = os.environ.get("PLANNER_MODEL", "glm4:9b")
KEEP_ALIVE           = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))

ANNOTATE_MODEL = "nanda-annotator-v2-q4km:latest"


# ---------------------------------------------------------------------------
# Step 1: Fetch
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or",
    "is", "are", "be", "as", "by", "from", "that", "this", "using", "use",
    "relative", "merits", "local", "agentic", "how", "what", "why", "which",
    "we", "our", "their", "its", "via", "versus", "vs",
})


def _arxiv_query(natural: str) -> str:
    """Extract key terms from a natural-language query for arXiv keyword search."""
    words = re.sub(r"[^a-zA-Z0-9\s\-]", " ", natural).split()
    keywords = [w for w in words if len(w) > 2 and w.lower() not in _STOPWORDS]
    if not keywords:
        return natural
    # Keep up to 8 most informative (longer) tokens
    keywords.sort(key=lambda w: -len(w))
    return " ".join(keywords[:8])


def _tfidf_rank(query: str, rows: list[dict], max_keep: int) -> list[dict]:
    """Return the top-max_keep rows most relevant to query by TF-IDF cosine similarity.

    Scores title (weight 3×) + abstract against the query vector.
    Falls back to returning rows unchanged if sklearn is unavailable or corpus is tiny.
    """
    if len(rows) <= max_keep:
        return rows
    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        return rows[:max_keep]

    corpus = [
        (r.get("title", "") + " ") * 3 + (r.get("summary", "") or "")
        for r in rows
    ]
    docs = [query] + corpus
    try:
        mat   = TfidfVectorizer(stop_words="english", max_features=20_000).fit_transform(docs)
        sims  = cosine_similarity(mat[0:1], mat[1:]).flatten()
        top_i = np.argsort(sims)[::-1][:max_keep]
        kept  = [rows[i] for i in sorted(top_i)]  # preserve original order
    except Exception:
        return rows[:max_keep]

    dropped = len(rows) - len(kept)
    print(f"[lit-review] TF-IDF re-rank: kept {len(kept)}/{len(rows)} papers (dropped {dropped} least relevant)")
    return kept


def step_fetch(
    query:     str,
    max_fetch: int,
    after:     str | None,
    before:    str | None,
    field:     str  = "abs",
    max_keep:  int  = DEFAULT_MAX_KEEP,
    _trace=None,
) -> list[dict]:
    from harness.skills.arxiv_fetch import _parse_date, fetch_cached

    arxiv_q = _arxiv_query(query) if len(query.split()) > 5 else query
    if arxiv_q != query:
        print(f"\n[lit-review] Step 1: fetching up to {max_fetch} papers")
        print(f"  query : {query!r}")
        print(f"  arxiv : {arxiv_q!r}")
    else:
        print(f"\n[lit-review] Step 1: fetching up to {max_fetch} papers for {query!r}...")

    # Default recency window: last DEFAULT_AFTER_YEARS years unless caller overrides.
    # Pass after="all" (or --all-time flag) to fetch across all time.
    if after is None:
        cutoff  = datetime.now(UTC) - timedelta(days=DEFAULT_AFTER_YEARS * 365)
        after_dt: datetime | None = cutoff
        print(f"  date  : {cutoff.date()} -> now  (default {DEFAULT_AFTER_YEARS}-year window; pass --all-time to disable)")
    elif after in ("all", "any", "all-time"):
        after_dt = None
        print("  date  : all time (no recency filter)")
    else:
        after_dt = _parse_date(after)

    before_dt = _parse_date(before) if before else None

    with (_trace.span("fetch", query=arxiv_q, max_fetch=max_fetch) if _trace else _nullctx()):
        rows = fetch_cached(
            query=arxiv_q,
            max_results=max_fetch,
            batch_size=100,
            field=field,
            sort_by=False,
            after=after_dt,
            before=before_dt,
            sleep_s=5.0,
        )

    # Retry with field=all when abs search returns nothing
    if not rows and field != "all":
        print("  [lit-review] abs search returned 0 — retrying with field=all")
        with (_trace.span("fetch_retry", query=arxiv_q, max_fetch=max_fetch) if _trace else _nullctx()):
            rows = fetch_cached(
                query=arxiv_q, max_results=max_fetch, batch_size=100,
                field="all", sort_by=False, after=after_dt, before=before_dt, sleep_s=5.0,
            )

    print(f"[lit-review] fetched {len(rows)} papers")

    # Re-rank by TF-IDF relevance and trim to max_keep before expensive enrichment
    rows = _tfidf_rank(query, rows, max_keep)

    return rows


# ---------------------------------------------------------------------------
# Step 2: Semantic Scholar enrichment
# ---------------------------------------------------------------------------

def step_enrich(papers: list[dict], skip: bool = False) -> tuple[list[dict], object]:
    """Returns (enriched_papers, graph_result). If skip, returns papers unchanged + None."""
    if skip or not papers:
        return papers, None
    from harness.semantic_scholar import build_citation_graph
    print(f"\n[lit-review] Step 2: enriching {len(papers)} papers via Semantic Scholar...")
    graph = build_citation_graph(papers, sleep_s=1.0, verbose=True)
    # Inject hub_score into each paper dict
    for p in papers:
        aid = (p.get("arxiv_id") or "").split("v")[0]
        p["hub_score"] = graph.hub_scores.get(aid, 0)
        p["ref_count"] = len(graph.all_refs.get(aid, []))
    print(f"[lit-review] enrichment done — {graph.stats['total_edges']} in-corpus edges")
    return papers, graph


# ---------------------------------------------------------------------------
# Step 3: Curate
# ---------------------------------------------------------------------------

def step_curate(papers: list[dict], max_annotate: int, query: str = "",
                skip: bool = False, producer_model: str = DEFAULT_PRODUCER,
                mean_threshold: float = 3.0, _trace=None) -> list[dict]:
    if skip or not papers:
        return papers[:max_annotate]
    from harness.curator import score_paper
    print(f"\n[lit-review] Step 3: curating {len(papers)} papers (target: {max_annotate})...")
    passed: list[dict] = []
    _ctx = _trace.span("curate", papers=len(papers), target=max_annotate) if _trace else _nullctx()
    with _ctx:
        for i, p in enumerate(papers):
            if len(passed) >= max_annotate:
                break
            aid        = p.get("arxiv_id", f"paper-{i}")
            title      = p.get("title", "")
            abstract   = p.get("summary", "")
            annotation = f"**Topic**: {title}\n\n{abstract}"
            print(f"  [{i+1}/{len(papers)}] curating {aid}: {title}")
            result = score_paper(
                arxiv_id=aid,
                title=title,
                annotation=annotation,
                model=producer_model,
                query=query,
                mean_threshold=mean_threshold,
                _trace=_trace,
            )
            result["_paper"] = p
            if result["passed"]:
                passed.append(p)
                print(f"    PASS  mean={result['mean']:.2f}")
                for s in result.get("scores", []):
                    print(f"      {s['persona']:<22} {s['score']}  {s['reason']}")
            else:
                veto_str = f"  veto={result['veto_by']}" if result.get("veto_by") else ""
                print(f"    FAIL  mean={result['mean']:.2f}{veto_str}")
                for s in result.get("scores", []):
                    print(f"      {s['persona']:<22} {s['score']}  {s['reason']}")
    # Sort surviving papers by hub_score descending so hubs get annotated first
    passed.sort(key=lambda p: p.get("hub_score", 0), reverse=True)
    print(f"[lit-review] curation: {len(passed)}/{len(papers)} passed")
    return passed


# ---------------------------------------------------------------------------
# Step 4: Annotate + wiggum
# ---------------------------------------------------------------------------

def _checkpoint_path(arxiv_id: str, checkpoint_dir: Path) -> Path:
    return checkpoint_dir / f"{arxiv_id.replace('/', '_')}.json"


def step_annotate(
    papers:          list[dict],
    producer_model:  str,
    evaluator_model: str,
    use_wiggum:      bool,
    checkpoint_dir:  Path,
    parallel:        int  = DEFAULT_ANNOTATE_PARALLEL,
    _trace=None,
) -> list[dict]:
    """Annotate each paper in parallel. Checkpoints per paper so crashes are recoverable."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from harness.logger import RunTrace
    from harness.skills import run_annotate_standalone

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    total   = len(papers)
    _lock   = threading.Lock()   # guards _trace rollup + progress counter
    _done   = [0]

    print(f"\n[lit-review] Step 4: annotating {total} papers"
          f"  (parallel={parallel}, wiggum={'on' if use_wiggum else 'off'})...")

    def _annotate_one(i: int, paper: dict) -> dict:
        aid   = paper.get("arxiv_id", f"paper-{i}")
        title = paper.get("title", "")
        cp    = _checkpoint_path(aid, checkpoint_dir)

        if cp.exists():
            try:
                cached = json.loads(cp.read_text(encoding="utf-8"))
                paper  = {**paper, **cached}
                with _lock:
                    _done[0] += 1
                    print(f"  [{_done[0]}/{total}] {aid} (checkpoint)", flush=True)
                return paper
            except Exception:
                pass

        context = f"# {title}\n\n{paper.get('summary', '')}"
        sub_trace = RunTrace(
            task=f"/lit-review /annotate {aid}",
            producer_model=producer_model,
            evaluator_model=evaluator_model,
            _is_sub=True,
        )
        sub_trace.data["task_type"] = "annotate"

        with _lock:
            _done[0] += 1
            print(f"  [{_done[0]}/{total}] annotating {aid}: {title[:60]}", flush=True)

        annotation_text = run_annotate_standalone(
            paper_context=context,
            producer_model=producer_model,
            max_retries=3,
            _trace=sub_trace,
        )

        wiggum_score = None
        if use_wiggum and annotation_text:
            from harness.wiggum import loop_annotate as wiggum_annotate_loop
            tmp = checkpoint_dir / f"{aid}_ann.md"
            tmp.write_text(annotation_text, encoding="utf-8")
            try:
                w_result = wiggum_annotate_loop(
                    task=f"Annotate paper: {title}",
                    output_path=str(tmp),
                    paper_context=context,
                    producer_model=producer_model,
                    evaluator_model=evaluator_model,
                )
                sub_trace.log_wiggum(w_result)
                wiggum_score = w_result.get("rounds", [{}])[-1].get("score")
                annotation_text = tmp.read_text(encoding="utf-8")
            except Exception as e:
                print(f"    [warn] wiggum failed for {aid}: {e}", flush=True)
            finally:
                if tmp.exists():
                    tmp.unlink()

        sub_trace.data["output_bytes"] = len(annotation_text.encode())
        sub_trace.finish("PASS" if annotation_text else "FAIL")

        # Roll sub-trace tokens into main trace (lock required — concurrent writes)
        if _trace is not None:
            with _lock:
                _trace.data["input_tokens"]  += sub_trace.data["input_tokens"]
                _trace.data["output_tokens"] += sub_trace.data["output_tokens"]
                for stage, vals in sub_trace.data.get("tokens_by_stage", {}).items():
                    s = _trace.data["tokens_by_stage"].setdefault(
                        stage, {"input": 0, "output": 0, "thinking_chars": 0,
                                "calls": 0, "total_ms": 0, "eval_ms": 0, "prompt_ms": 0})
                    for k in ("input", "output", "thinking_chars", "calls",
                              "total_ms", "eval_ms", "prompt_ms"):
                        s[k] = s.get(k, 0) + vals.get(k, 0)
                offset = sub_trace._t0_us - _trace._t0_us
                _trace._events.extend(
                    {**ev, "ts": ev["ts"] + offset} if "ts" in ev else ev
                    for ev in sub_trace._events
                )

        annotation      = _parse_annotation_sections(annotation_text)
        checkpoint_data = {
            "annotation":     annotation,
            "annotation_raw": annotation_text,
            "wiggum_score":   wiggum_score,
        }
        cp.write_text(json.dumps(checkpoint_data, ensure_ascii=False), encoding="utf-8")
        return {**paper, **checkpoint_data}

    results: list[dict | None] = [None] * total
    _ann_ctx = _trace.span("annotate", papers=total) if _trace else _nullctx()
    with _ann_ctx:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {pool.submit(_annotate_one, i, p): i for i, p in enumerate(papers)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    aid = papers[idx].get("arxiv_id", f"paper-{idx}")
                    print(f"  [error] annotation failed for {aid}: {e}", flush=True)

    annotated = [r for r in results if r is not None]
    print(f"[lit-review] annotated {len(annotated)}/{total} papers")
    return annotated


def _parse_annotation_sections(text: str) -> dict:
    """Parse Nanda 8-section annotation into a column dict."""
    section_map = {
        "**Topic**":                     "topic",
        "**Motivation**":                "motivation",
        "**Contribution**":              "contribution",
        "**Detail / Nuance**":           "detail_nuance",
        "**Evidence / Contribution 2**": "evidence_contribution_2",
        "**Weaker result**":             "weaker_result",
        "**Narrow impact**":             "narrow_impact",
        "**Broad impact**":              "broad_impact",
    }
    parts   = re.split(r"(\*\*[^*]+\*\*)", text)
    result  = {v: "" for v in section_map.values()}
    current = None
    for part in parts:
        part = part.strip()
        if part in section_map:
            current = section_map[part]
        elif current:
            result[current] = re.sub(r'^:\s*', '', part)
    return result


# ---------------------------------------------------------------------------
# Step 5: Cluster
# ---------------------------------------------------------------------------

_CLUSTER_SYSTEM = """\
You are a research synthesis assistant. Given a list of paper titles and their Contribution sentences,
group them into 3-5 thematic clusters. Each cluster should represent a coherent research direction.

Output ONLY valid JSON in this exact format:
{
  "clusters": [
    {
      "name": "Cluster name (5-7 words)",
      "paper_ids": ["arxiv_id_1", "arxiv_id_2", ...]
    }
  ]
}

Do not include any text outside the JSON block."""


def step_cluster(papers: list[dict], model: str = DEFAULT_CLUSTER_MODEL, _trace=None) -> list[dict]:
    """
    Group papers into thematic clusters using an LLM.
    Returns list of cluster dicts: {name, paper_ids}.
    """
    print(f"\n[lit-review] Step 5: clustering {len(papers)} papers...")

    paper_list = "\n".join(
        f"- {p.get('arxiv_id','?')}: {p.get('title','?')} | "
        f"{p.get('annotation', {}).get('contribution','')}"
        for p in papers
    )
    prompt = f"Papers to cluster:\n{paper_list}"

    with (_trace.span("cluster", papers=len(papers)) if _trace else _nullctx()):
        resp = _llm_chat(
            model=model,
            messages=[
                {"role": "system", "content": _CLUSTER_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            options={"temperature": 0.1, "num_predict": 1024},
            keep_alive=KEEP_ALIVE,
        )
        if _trace:
            _trace.log_usage(resp, stage="cluster")
    raw = resp["message"]["content"].strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

    try:
        data = json.loads(raw)
        clusters = data.get("clusters", [])
    except json.JSONDecodeError:
        print("  [warn] cluster LLM returned invalid JSON — putting all papers in one cluster")
        clusters = [{"name": "All Papers", "paper_ids": [p.get("arxiv_id","") for p in papers]}]

    print(f"[lit-review] {len(clusters)} clusters")
    for c in clusters:
        print(f"  {c['name']}: {len(c.get('paper_ids', []))} papers")
    return clusters


# ---------------------------------------------------------------------------
# Step 6: Synthesize
# ---------------------------------------------------------------------------

_SYNTH_CLUSTER_SYSTEM = """\
You are a research synthesis assistant. Given a cluster of annotated research papers,
write a coherent 2-3 sentence paragraph that describes the common theme, key findings,
and how the papers relate to each other. Be specific — name techniques, not just topics.
Output ONLY the paragraph, no preamble."""

_SYNTH_CROSS_SYSTEM = """\
You are a research synthesis assistant. Given cluster summaries from a literature review,
write:
1. A 3-4 sentence overview paragraph synthesizing across all clusters
2. 3-5 open research questions the literature has not fully answered

Output in this format:
OVERVIEW:
<paragraph>

OPEN QUESTIONS:
- <question 1>
- <question 2>
..."""


def step_synthesize(papers: list[dict], clusters: list[dict],
                    model: str = DEFAULT_CLUSTER_MODEL, _trace=None) -> dict:
    """
    Write cluster summaries and cross-cluster synthesis.
    Returns {cluster_summaries: {cluster_name: str}, synthesis: str, open_questions: [str]}.
    """
    print("\n[lit-review] Step 6: synthesizing...")
    id_to_paper = {p.get("arxiv_id", "").split("v")[0]: p for p in papers}

    cluster_summaries = {}
    for cluster in clusters:
        cluster_papers: list[dict] = [
            p for pid in cluster.get("paper_ids", [])
            if (p := id_to_paper.get(pid.split("v")[0])) is not None
        ]
        if not cluster_papers:
            cluster_summaries[cluster["name"]] = ""
            continue

        paper_blurbs = "\n\n".join(
            f"Title: {p.get('title','')}\n"
            f"Contribution: {(p.get('annotation') or {}).get('contribution','')}\n"
            f"Evidence: {(p.get('annotation') or {}).get('evidence_contribution_2','')}"
            for p in cluster_papers
        )

        resp = _llm_chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYNTH_CLUSTER_SYSTEM},
                {"role": "user",   "content": paper_blurbs},
            ],
            options={"temperature": 0.2, "num_predict": 512},
            keep_alive=KEEP_ALIVE,
        )
        if _trace:
            _trace.log_usage(resp, stage="synthesize")
        cluster_summaries[cluster["name"]] = resp["message"]["content"].strip()
        print(f"  cluster '{cluster['name']}': synthesized")

    # Cross-cluster synthesis
    all_summaries = "\n\n".join(
        f"Cluster: {name}\n{summary}"
        for name, summary in cluster_summaries.items()
        if summary
    )
    with (_trace.span("synthesize", clusters=len(clusters)) if _trace else _nullctx()):
        resp = _llm_chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYNTH_CROSS_SYSTEM},
                {"role": "user",   "content": all_summaries},
            ],
            options={"temperature": 0.2, "num_predict": 1024},
            keep_alive=KEEP_ALIVE,
        )
        if _trace:
            _trace.log_usage(resp, stage="synthesize")
    cross_raw = resp["message"]["content"].strip()

    overview_m = re.search(r"OVERVIEW:\s*\n(.*?)(?=OPEN QUESTIONS:|$)", cross_raw, re.DOTALL)
    questions_m = re.search(r"OPEN QUESTIONS:\s*\n(.*)", cross_raw, re.DOTALL)

    synthesis = overview_m.group(1).strip() if overview_m else cross_raw
    open_questions = []
    if questions_m:
        for line in questions_m.group(1).splitlines():
            line = re.sub(r"^[-*]\s*", "", line.strip())
            if line:
                open_questions.append(line)

    return {
        "cluster_summaries": cluster_summaries,
        "synthesis":         synthesis,
        "open_questions":    open_questions,
    }


# ---------------------------------------------------------------------------
# Step 7: Render
# ---------------------------------------------------------------------------

def step_render(papers: list[dict], clusters: list[dict], synthesis_data: dict,
                graph, query: str, after: str | None, before: str | None,
                template_name: str, out_path: Path) -> None:
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        print("[lit-review] jinja2 not installed: pip install jinja2")
        sys.exit(1)

    print(f"\n[lit-review] Step 7: rendering with template '{template_name}'...")

    id_to_paper = {p.get("arxiv_id", "").split("v")[0]: p for p in papers}

    # Build cluster objects for template
    template_clusters = []
    for cluster in clusters:
        cluster_papers: list[dict] = [
            p for pid in cluster.get("paper_ids", [])
            if (p := id_to_paper.get(pid.split("v")[0])) is not None
        ]

        hub_paper = None
        if cluster_papers:
            best = max(cluster_papers, key=lambda p: p.get("hub_score", 0))
            if best.get("hub_score", 0) > 0:
                hub_paper = {
                    "title":     best.get("title", ""),
                    "arxiv_id":  best.get("arxiv_id", ""),
                    "arxiv_url": best.get("arxiv_url", ""),
                    "hub_score": best.get("hub_score", 0),
                }

        template_clusters.append({
            "name":     cluster["name"],
            "summary":  synthesis_data["cluster_summaries"].get(cluster["name"], ""),
            "hub_paper": hub_paper,
            "papers":   [
                {
                    "title":      p.get("title", ""),
                    "arxiv_id":   p.get("arxiv_id", ""),
                    "arxiv_url":  p.get("arxiv_url", ""),
                    "published":  p.get("published", ""),
                    "annotation": p.get("annotation", {}),
                    "wiggum_score": p.get("wiggum_score"),
                    "hub_score":  p.get("hub_score", 0),
                    "unresolved_refs": 0,
                }
                for p in cluster_papers
            ],
        })

    date_range = ""
    if after or before:
        date_range = f"{after or '(any)'} to {before or '(any)'}"

    ctx = {
        "meta": {
            "query":        query,
            "date_range":   date_range,
            "paper_count":  len(papers),
            "annotated":    len(papers),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "clusters":       template_clusters,
        "synthesis":      synthesis_data["synthesis"],
        "open_questions": synthesis_data["open_questions"],
        "gaps":           (graph.gap_candidates[:20] if graph else []),
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template_file = f"lit_review_{template_name}.j2"
    try:
        tmpl = env.get_template(template_file)
    except Exception as e:
        print(f"[lit-review] template not found: {template_file} — {e}")
        sys.exit(1)

    rendered = tmpl.render(**ctx)
    out_path = out_path.expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"[lit-review] output -> {out_path} ({len(rendered):,} chars)")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_lit_review(
    query:          str,
    out_path:       Path,
    max_fetch:      int  = DEFAULT_MAX_FETCH,
    max_annotate:   int  = DEFAULT_MAX_ANNOTATE,
    after:          str | None = None,
    before:         str | None = None,
    csv_path:       Path | None = None,
    no_curate:      bool = False,
    no_wiggum:      bool = False,
    no_s2:          bool = False,
    template:       str  = DEFAULT_TEMPLATE,
    producer_model: str  = DEFAULT_PRODUCER,
    evaluator_model: str = DEFAULT_EVALUATOR,
    checkpoint_dir: Path = CHECKPOINT_DIR,
    parallel:       int  = DEFAULT_ANNOTATE_PARALLEL,
    _trace=None,
) -> dict:
    t0 = time.monotonic()

    def _stage(name: str) -> None:
        if _trace and hasattr(_trace, "set_stage"):
            _trace.set_stage(name)

    # 1. Fetch or load
    _stage("search")
    if csv_path and csv_path.exists():
        print(f"\n[lit-review] loading {csv_path}...")
        with open(csv_path, newline="", encoding="utf-8") as f:
            papers = list(csv.DictReader(f))
        print(f"[lit-review] {len(papers)} papers loaded")
    else:
        papers = step_fetch(query, max_fetch, after, before, _trace=_trace)
        if not papers:
            print("[lit-review] no papers fetched — aborting")
            return {"papers": 0, "clusters": 0, "out_path": "", "error": "no_papers"}

    # 2. Enrich
    _stage("plan")
    with (_trace.span("enrich", papers=len(papers)) if _trace else _nullctx()):
        papers, graph = step_enrich(papers, skip=no_s2)

    # 3. Curate
    _stage("memory")
    papers = step_curate(papers, max_annotate, query=query, skip=no_curate,
                         producer_model=producer_model, _trace=_trace)

    # 4. Annotate
    _stage("synth")
    papers = step_annotate(papers, producer_model, evaluator_model,
                           use_wiggum=(not no_wiggum),
                           checkpoint_dir=checkpoint_dir,
                           parallel=parallel, _trace=_trace)

    # 5. Cluster + 6. Synthesize
    _stage("eval")
    clusters = step_cluster(papers, model=DEFAULT_CLUSTER_MODEL, _trace=_trace)

    synthesis_data = step_synthesize(papers, clusters, model=DEFAULT_CLUSTER_MODEL,
                                     _trace=_trace)

    # 7. Render
    with (_trace.span("render") if _trace else _nullctx()):
        step_render(
            papers=papers, clusters=clusters, synthesis_data=synthesis_data,
            graph=graph, query=query, after=after, before=before,
            template_name=template, out_path=out_path,
        )

    elapsed = round(time.monotonic() - t0, 1)
    print(f"\n[lit-review] done in {elapsed}s")

    return {
        "papers":       len(papers),
        "clusters":     len(clusters),
        "out_path":     str(out_path),
        "elapsed_s":    elapsed,
        "paper_titles": [p.get("title", "") for p in papers if p.get("title")],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="/lit-review skill — fetch, annotate, synthesize, render",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("query",          nargs="?",   help="Search query")
    ap.add_argument("--max-fetch",    type=int,    default=DEFAULT_MAX_FETCH)
    ap.add_argument("--max-annotate", type=int,    default=DEFAULT_MAX_ANNOTATE)
    ap.add_argument("--after",        default=None, help="Only papers on/after YYYY-MM-DD (default: last 2 years)")
    ap.add_argument("--all-time",     action="store_true", help="Disable default 2-year recency filter")
    ap.add_argument("--before",       default=None)
    ap.add_argument("--csv",          default=None, help="Existing CSV (skip fetch)")
    ap.add_argument("--no-fetch",     action="store_true")
    ap.add_argument("--no-curate",    action="store_true")
    ap.add_argument("--no-wiggum",    action="store_true")
    ap.add_argument("--no-s2",        action="store_true")
    ap.add_argument("--template",     default=DEFAULT_TEMPLATE,
                    choices=["survey", "gaps", "executive"])
    ap.add_argument("--producer",     default=DEFAULT_PRODUCER)
    ap.add_argument("--evaluator",    default=DEFAULT_EVALUATOR)
    ap.add_argument("--out",          default=None)
    ap.add_argument("--checkpoint",   default=str(CHECKPOINT_DIR))
    args = ap.parse_args()

    csv_path = Path(args.csv) if args.csv else None

    if not args.query and not csv_path:
        ap.print_help()
        sys.exit(1)

    query = args.query or (csv_path.stem if csv_path else "literature review")
    out_path = Path(args.out) if args.out else Path(f"lit_review_{query[:30].replace(' ','_')}.md")

    run_lit_review(
        query=query,
        out_path=out_path,
        max_fetch=args.max_fetch,
        max_annotate=args.max_annotate,
        after="all" if args.all_time else args.after,
        before=args.before,
        csv_path=csv_path,
        no_curate=args.no_curate,
        no_wiggum=args.no_wiggum,
        no_s2=args.no_s2,
        template=args.template,
        producer_model=args.producer,
        evaluator_model=args.evaluator,
        checkpoint_dir=Path(args.checkpoint),
    )


if __name__ == "__main__":
    main()
