"""
playwright_skill.py — LLM-guided website navigation via accessibility-tree snapshots.

Uses playwright's ARIA snapshot (page.aria_snapshot()) to give the LLM a structured,
role/name-based view of the page instead of raw DOM links. Actions use semantic
locators (get_by_role, get_by_text, get_by_placeholder) — more robust than href
matching or CSS selectors.

Decision loop per step:
  1. Snapshot current page: title, URL, ARIA tree (roles + names + refs)
  2. Ask oracle LLM: given goal + history + snapshot, what next?
     Actions: fill | press | click | goto | extract | fail
  3. Execute via semantic locator, repeat up to max_steps
  4. On "extract": return cleaned body text

Install:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import tempfile
import textwrap
import time
from urllib.parse import urlparse

# Module-level handle prevents GC when keeping the browser alive between tasks.
_persistent_browser_proc: "subprocess.Popen | None" = None

_CDP_PORT        = int(os.environ.get("HARNESS_CDP_PORT", "9222"))
_STATE_FILE      = os.path.join(tempfile.gettempdir(), "harness_browser_state.json")
_SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


# ---------------------------------------------------------------------------
# Browser state helpers (mirrors agent.py — kept local to avoid circular import)
# ---------------------------------------------------------------------------

def _read_state() -> dict:
    try:
        if os.path.exists(_STATE_FILE):
            return json.loads(open(_STATE_FILE, encoding="utf-8").read())
    except Exception:
        pass
    return {}


def _write_state(data: dict):
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(data))
    except Exception:
        pass


def _clear_state():
    try:
        os.unlink(_STATE_FILE)
    except Exception:
        pass


def _launch_detached(exe: str, port: int) -> "subprocess.Popen":
    """Launch Chromium as a detached OS process so it outlives the agent subprocess."""
    args = [exe, f"--remote-debugging-port={port}",
            "--no-first-run", "--no-default-browser-check",
            "--no-sandbox", "about:blank"]
    if platform.system() == "Windows":
        return subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _settle(page, timeout_ms: int = 4000):
    """Best-effort networkidle wait so JS-rendered ARIA roles are available."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def _wait_for_url_change(page, url_before: str, timeout_s: float = 6.0) -> bool:
    """Poll until the page URL differs from url_before. Returns True if it changed."""
    import time
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if page.url != url_before:
            return True
        time.sleep(0.15)
    return False


def _wait_for_cdp(port: int, retries: int = 10, delay: float = 0.5):
    import urllib.request as _ur
    for _ in range(retries):
        time.sleep(delay)
        try:
            _ur.urlopen(f"http://localhost:{port}/json/version", timeout=1)
            return
        except Exception:
            pass
    raise RuntimeError(f"CDP endpoint on port {port} did not respond after {retries * delay:.0f}s")


# ---------------------------------------------------------------------------
# Page snapshot
# ---------------------------------------------------------------------------

def _page_snapshot(page) -> dict:
    """Return a compact snapshot of the current page using the ARIA tree."""
    title = page.title() or ""
    url   = page.url

    aria = ""
    try:
        aria = (page.aria_snapshot() or "").strip()
        aria = aria[:4000]
    except Exception:
        pass

    if not aria:
        # ARIA empty (JS-heavy page not yet rendered) — fall back to body text
        try:
            aria = (page.inner_text("body") or "").strip()
            aria = re.sub(r"\n{3,}", "\n\n", aria)[:3000]
        except Exception:
            aria = ""

    return {"title": title, "url": url, "aria": aria}


def _clean_full_text(page) -> str:
    """Extract and clean the full body text of the current page."""
    try:
        text = (page.inner_text("body") or "").strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:16_000]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Pre-navigation planner — pick best URL from sitemap before loop starts
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = textwrap.dedent("""\
    You are a URL selection agent. Given a goal and a list of available pages on a domain,
    rank the top 3 pages most likely to answer the goal, ordered best-first.
    Reply with JSON only — no prose.

    If pages match:
      {"action": "goto", "url": "https://...", "alternatives": ["https://...", "https://..."], "reason": "one-line explanation"}

    If no page matches the goal (content is not on this site):
      {"action": "fail", "reason": "brief explanation"}

    URL selection rules (apply in order):

    1. BREADTH vs DEPTH — identify the goal intent first:
       - BROAD goals ("best practices", "overview", "guide", "tips", "recommendations",
         "cost management", "getting started", "introduction", "how to"):
         → The PRIMARY url must be a high-level, broad page — path ends in "overview",
           "guide", "best-practices", "index", or has fewer than 5 path segments.
         → NEVER pick a deep feature-specific page (e.g. /docs/en/section/specific-feature)
           as the PRIMARY for a broad goal, even if a keyword matches. A specific feature
           page answers "what is X?", not "what are best practices across the topic?".
         → Put specific feature pages in alternatives[], not as the primary url.
       - SPECIFIC goals ("how does X work", "API for Y", "error Z"):
         → Pick the exact deep page that covers that topic.

    2. KEYWORD MATCH — score URL path segments + title words against goal keywords.
       Prefer highest overlap, but never let keyword match override rule 1.

    3. SKEPTICISM — exclude: surveys, team/about, news, changelogs, release notes, legal.

    4. Only pick URLs from the provided list. Output only the JSON object.
""")


def _plan_from_sitemap(pages: list[dict], goal: str, model: str) -> dict | None:
    """
    One-shot LLM call: pick the best URL from the sitemap for the goal,
    or declare that the content is not on this site.
    Returns a decision dict {action: goto|fail, url?, reason?} or None on error.
    """
    from harness import inference

    if not pages:
        return None

    lines = []
    for i, p in enumerate(pages[:60]):
        meta = f"  [{p['title']}]" if p.get("title") else ""
        if p.get("body"):
            meta += f"  — {p['body'][:80]}"
        lines.append(f"  {i+1:3d}. {p['url']}{meta}")

    pages_str = "\n".join(lines)
    prompt = textwrap.dedent(f"""\
        Goal: {goal}

        Available pages on this domain ({len(pages)} total):
        {pages_str}

        Rank the top 3 URLs most likely to answer the goal (best first).
        Primary url = the single best page. alternatives = the next 2, in order.
    """)

    try:
        resp = inference.chat(
            model=model,
            messages=[
                {"role": "system", "content": _PLAN_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            options={"temperature": 0.1, "num_predict": 128},
        )
        raw = resp.message.content.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  [sitemap] planner error: {e}")
        return None


# ---------------------------------------------------------------------------
# LLM navigation oracle
# ---------------------------------------------------------------------------
# Completeness oracle — saturation check after extraction
# ---------------------------------------------------------------------------

SATURATION_THRESHOLD = 7   # 0-10; below this, pull more pages
MAX_EXTRACT_PAGES    = 3   # total pages to draw from (including first)

_COMPLETENESS_SYSTEM = textwrap.dedent("""\
    You are evaluating how completely a piece of extracted web content answers a research goal.
    Reply with JSON only — no prose, no markdown fences.
    {"score": <integer 0-10>, "missing": "<one sentence: what key aspect is not yet covered, or 'nothing' if complete>"}

    Scoring guide:
      9-10: content fully answers the goal with concrete details; nothing important missing
      7-8:  most of the goal is covered; minor gaps or could use one more source
      5-6:  covers the topic generally but missing specific strategies or concrete details
      3-4:  only tangentially related; major aspects of the goal are absent
      0-2:  does not address the goal at all

    IMPORTANT: Scores must be monotonically non-decreasing as content grows.
    If a prior score is given, your score MUST be >= that value.
    Only increase the score when new content adds coverage; never decrease it.
""")


def _score_completeness(content: str, goal: str, model: str, prior_score: int = 0) -> dict:
    """
    Score how completely the extracted content answers the goal.
    Samples proportionally from each source page so later pages are visible.
    Returns {"score": int, "missing": str}.
    """
    from harness import inference

    # Split on source separators and sample proportionally from each page
    parts = re.split(r'\n---\nSource: [^\n]+\n\n', content)
    chars_per_part = max(1500, 5000 // len(parts))
    sample = "\n\n[...]\n\n".join(p[:chars_per_part] for p in parts)

    prior_note = f"Prior score from fewer pages: {prior_score}/10. Your score must be >= {prior_score}.\n\n" if prior_score > 0 else ""
    prompt = (
        f"{prior_note}"
        f"Goal: {goal}\n\n"
        f"Extracted content ({len(parts)} page(s), sampled):\n"
        f"{sample}\n\n"
        f"How completely does this content answer the goal? Reply with JSON."
    )
    try:
        resp = inference.chat(
            model=model,
            messages=[
                {"role": "system", "content": _COMPLETENESS_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            options={"temperature": 0.1, "num_predict": 80},
        )
        raw = resp.message.content.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        result = json.loads(raw)
        return {"score": int(result.get("score", 0)), "missing": result.get("missing", "")}
    except Exception:
        return {"score": 10, "missing": ""}  # fail open — don't block on oracle error


# ---------------------------------------------------------------------------

_SYSTEM = textwrap.dedent("""\
    You are a web navigation agent. Given a goal and an ARIA accessibility-tree
    snapshot of the current page, decide the single best next action.
    Reply with a JSON object only — no prose.

    Actions:
      {"action": "fill",      "role": "<ARIA role>", "name": "<element label/placeholder>", "value": "<text to type>"}
          — fill an input field identified by its ARIA role and accessible name
      {"action": "press",     "key": "<key name>"}
          — press a keyboard key (e.g. "Enter", "Tab")
      {"action": "click",     "text": "<visible link or button text>"}
          — click a link or button by its visible text
      {"action": "goto",      "url": "<absolute URL>"}
          — navigate directly (use when you know the URL)
      {"action": "backtrack", "reason": "<why this page is not useful>"}
          — go back to the previous page and try a different link or search
      {"action": "extract"}
          — the current page contains the target content; extract it now
      {"action": "fail",      "reason": "<why you cannot proceed>"}
          — give up only after backtracking and exhausting all options

    Rules:
    - Use "fill" for search boxes, inputs. Identify them by role (e.g. "searchbox",
      "textbox") and name (label or placeholder text visible in the snapshot).
    - After filling a search box, always follow with {"action": "press", "key": "Enter"}.
    - Use "click" to follow links or press buttons — match the exact visible text.
    - Use "goto" only when you know the destination URL with high confidence.
    - Use "extract" ONLY when the current page directly answers the goal — not as a last resort.
    - Use "backtrack" whenever the current page is clearly off-topic or a dead end.
      Then try a different link on the previous page, or a different search query.
    - Never revisit a URL already in history.
    - Never click a link whose text previously led to a page that was backtracked.
      The history shows "via: <link text>" for pages that were backtracked — avoid those link texts.
    - IMPORTANT — avoid semantic false positives when clicking links:
      A link named "Economic Research" or "AI Policy" may sound related but lead to
      surveys or reports, not practitioner guides. If the goal is "best practices" or
      "how to implement", prefer links with words like "docs", "guide", "tutorial",
      "engineering", "blog", or direct article titles that match the goal closely.
      When unsure, prefer search results over navigation links.
    - If a search yields no relevant results, use "backtrack" and reformulate the query.
    - If you have already backtracked from this page with no other links to try, use "fail".
    - If the sitemap list shows this was the best available URL on the domain, prefer "extract"
      over "backtrack" when the page is topically related — the synthesis step can extract
      what is relevant even from a broader page. Only "backtrack" if the page is completely
      unrelated to the goal.
    - Output only the JSON object, nothing else.
""")


def _decide(snapshot: dict, goal: str, history: list[dict], model: str,
            blocked_clicks: set[str] | None = None,
            sitemap_context: str = "",
            last_action_note: str = "") -> dict:
    from harness import inference

    def _hist_line(h: dict) -> str:
        parts = f"  - {h['url']}  [{h['title']}]"
        if h.get("via"):
            parts += f"  via: '{h['via']}'"
        if h.get("note"):
            parts += f"  — {h['note']}"
        return parts

    history_str = "\n".join(_hist_line(h) for h in history[-6:]) if history else "  (none)"

    blocked_str = ""
    if blocked_clicks:
        lines = "\n".join(f"  - \"{t}\"" for t in sorted(blocked_clicks))
        blocked_str = f"\nDO NOT click any of these links — they previously led to dead ends:\n{lines}\n"

    # Cap sitemap block to top 8 entries; trim ARIA to stay within context window
    _sitemap_trimmed = "\n".join(sitemap_context.splitlines()[:10]) if sitemap_context else ""
    sitemap_block = f"\n{_sitemap_trimmed}\n" if _sitemap_trimmed else ""
    action_note   = f"\n⚠ {last_action_note}\n" if last_action_note else ""

    aria_text = (snapshot['aria'] or '  (empty)')[:3000]
    if len(snapshot.get('aria', '')) > 3000:
        aria_text += "\n  ... (truncated)"

    prompt = textwrap.dedent(f"""\
        Goal: {goal}
        {sitemap_block}{action_note}
        Current page:
          Title: {snapshot['title']}
          URL:   {snapshot['url']}

        ARIA accessibility tree (roles, names, interactive elements):
        {aria_text}

        Already visited (url — title — outcome note):
        {history_str}
        {blocked_str}
        What is the single best next action?
    """)

    try:
        resp = inference.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            options={"temperature": 0.1, "num_predict": 256, "num_ctx": 12288},
        )
        raw = resp.message.content.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        return json.loads(raw)
    except Exception as e:
        return {"action": "fail", "reason": f"oracle error: {e}"}


# ---------------------------------------------------------------------------
# Semantic action executor
# ---------------------------------------------------------------------------

def _execute(page, decision: dict, history: list[dict], timeout_ms: int) -> bool:
    """
    Execute a decision dict against the page using semantic locators.
    Returns True if navigation occurred (history should be updated).
    history is a list of {url, title, note} dicts.
    """
    action = decision.get("action", "fail")

    if action == "backtrack":
        # Walk back through history skipping pages that were themselves dead ends
        for h in reversed(history[:-1]):
            if not h.get("note", "").startswith("backtracked"):
                page.goto(h["url"], wait_until="domcontentloaded")
                return True
        # No valid ancestor — the planner sent us here directly and it was the best choice.
        # Raise immediately rather than looping on the same page.
        raise RuntimeError(
            "navigator gave up: backtracked from planner-chosen page with no parent — "
            "content not available on this site in the required form"
        )

    if action == "fill":
        role  = decision.get("role", "textbox")
        name  = decision.get("name", "")
        value = decision.get("value", "")
        _target = None
        try:
            _loc = page.get_by_role(role, name=name) if name else page.get_by_role(role)
            _target = _loc.first
            _target.fill(value)
        except Exception:
            try:
                _target = page.get_by_placeholder(re.compile(r"search", re.IGNORECASE)).first
                _target.fill(value)
            except Exception:
                try:
                    _target = page.locator(
                        "input[type='search'], input[name*='search'], input[id*='search']"
                    ).first
                    _target.fill(value)
                except Exception:
                    _target = None

        # Auto-submit search inputs so the LLM never needs a separate press step
        # (avoids autocomplete-reopen loops where the model re-fills instead of pressing Enter)
        _is_search = role == "searchbox" or "search" in (name or "").lower()
        if _is_search and _target is not None:
            try:
                _target.press("Enter")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass
                return True
            except Exception:
                pass
        return False

    elif action == "press":
        key = decision.get("key", "Enter")
        # Dispatch to the focused DOM element so autocomplete dropdowns can't
        # steal the keypress; fall back to global keyboard if nothing is focused.
        try:
            focused = page.locator(":focus")
            if focused.count():
                focused.first.press(key)
            else:
                page.keyboard.press(key)
        except Exception:
            page.keyboard.press(key)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass  # press may not trigger navigation
        return True

    elif action == "click":
        text = decision.get("text", "")
        if not text:
            return False
        # Block clicks that previously led to backtracked pages
        backtracked_via = {h["via"] for h in history if h.get("note", "").startswith("backtracked") and h.get("via")}
        if text in backtracked_via:
            return False  # silently skip — LLM will re-prompt and choose differently
        try:
            page.get_by_role("link", name=text).first.click()
        except Exception:
            try:
                page.get_by_text(text, exact=False).first.click()
            except Exception:
                return False
        try:
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        return True

    elif action == "goto":
        url = decision.get("url", "")
        visited_urls = {h["url"] for h in history}
        if not url or url in visited_urls:
            return False
        page.goto(url, wait_until="domcontentloaded")
        return True

    return False


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def _url_slug(url: str) -> str:
    """Turn a URL into a short filename-safe slug."""
    parsed = urlparse(url)
    host = re.sub(r"^www\.", "", parsed.netloc or "page")
    path = re.sub(r"[^\w]", "_", parsed.path.strip("/"))[:30]
    slug = host + ("_" + path if path else "")
    return re.sub(r"_+", "_", slug)[:50]


def _take_screenshot(page, run_id: str, step: int, action: str, full_page: bool = False) -> "str | None":
    """Capture a screenshot; returns the absolute file path or None on failure."""
    if not run_id:
        return None
    try:
        shot_dir = os.path.join(_SCREENSHOTS_DIR, run_id)
        os.makedirs(shot_dir, exist_ok=True)
        filename = f"step{step:02d}_{action}_{_url_slug(page.url)}.png"
        path = os.path.join(shot_dir, filename)
        page.screenshot(path=path, full_page=full_page)
        return path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main navigation loop
# ---------------------------------------------------------------------------

def navigate_and_extract(
    start_url:  str,
    goal:       str,
    model:      str,
    max_steps:  int  = 12,
    headed:     bool = True,
    timeout_ms: int  = 15_000,
    keep:       bool = False,
    run_id:     str  = "",
) -> tuple[str, str, list[str], list[dict]]:
    """
    Navigate to start_url and find the page matching goal.

    Returns (extracted_text, final_url, screenshots, history).  Raises RuntimeError on failure.

    keep=True  — leave the Chromium window open after the task completes.
                 The browser is launched as a detached OS process so it survives
                 the agent subprocess exiting.  State written to harness_browser_state.json.
    """
    global _persistent_browser_proc

    _reuse = os.environ.get("HARNESS_REUSE_BROWSER") == "1"

    if not start_url.startswith("http"):
        start_url = "https://" + start_url

    from playwright.sync_api import sync_playwright

    # Use the manual lifecycle form so we control when (and whether) playwright stops.
    # The context-manager form calls stop() on exit which can send Browser.close via CDP.
    _pw_ctx = sync_playwright()
    pw      = _pw_ctx.start()
    _browser_proc = None  # only set when WE launched a detached subprocess

    def _teardown(browser, final_url: str = ""):
        """Close or persist the browser depending on the keep flag."""
        if keep:
            try:
                state = _read_state()
                state.update({"active": True, "last_url": final_url, "last_ts": time.time()})
                _write_state(state)
            except Exception:
                pass
            global _persistent_browser_proc
            _persistent_browser_proc = _browser_proc
            print(f"  [playwright] browser kept alive at {final_url}")
            # Do NOT stop playwright — that sends Browser.close via CDP
        else:
            try:
                browser.close()
            except Exception:
                pass
            if _browser_proc:
                try:
                    _browser_proc.terminate()
                except Exception:
                    pass
            _persistent_browser_proc = None
            _clear_state()
            try:
                _pw_ctx.stop()
            except Exception:
                pass

    try:
        browser = None

        # ── Try reconnecting to an existing browser ──────────────────────────
        if _reuse and headed:
            state = _read_state()
            port  = state.get("cdp_port", _CDP_PORT)
            try:
                browser = pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                print(f"  [playwright] reconnected to browser on CDP port {port}")
            except Exception as _e:
                print(f"  [playwright] CDP reconnect failed ({_e}), launching fresh")
                browser = None

        # ── Launch a fresh browser ────────────────────────────────────────────
        if browser is None:
            if headed and keep:
                # Detached subprocess so Chromium outlives agent.py
                _exe = pw.chromium.executable_path
                if _exe:
                    _browser_proc = _launch_detached(_exe, _CDP_PORT)
                    _wait_for_cdp(_CDP_PORT)
                    browser = pw.chromium.connect_over_cdp(f"http://localhost:{_CDP_PORT}")
                    _write_state({"active": True, "cdp_port": _CDP_PORT,
                                  "pid": _browser_proc.pid, "ts": time.time()})
                    print(f"  [playwright] detached browser on CDP port {_CDP_PORT} (pid={_browser_proc.pid})")
                else:
                    # executable_path unavailable — fall back, persistence disabled
                    keep = False
                    print("  [playwright] executable_path unavailable — persistence disabled")

            if browser is None:
                # Playwright-owned launch (no persistence even if keep was requested)
                browser = pw.chromium.launch(
                    headless=not headed,
                    slow_mo=100 if headed else 0,
                )
                keep = False  # playwright owns this browser; can't keep it

        # ── Build context + page ──────────────────────────────────────────────
        _ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0.0.0 Safari/537.36")
        if browser.contexts:
            ctx = browser.contexts[0]
        else:
            ctx = browser.new_context(user_agent=_ua, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)

        history:           list[dict] = []  # {url, title, note, via}
        screenshots:       list[str]  = []
        _last_action_note: str        = ""  # injected into next _decide when action failed/didn't navigate
        _url_visit_count:  dict       = {}  # url → times visited (non-navigating steps count)
        _planner_chose:    bool       = False  # True when planner pre-selected the start URL

        # Discover site structure then do a one-shot planning call before navigation.
        sitemap_context = ""
        _sitemap_pages: list[dict] = []
        try:
            from skills.sitemap_skill import discover_pages, rank_by_goal, format_for_navigator
            _sitemap_pages = discover_pages(start_url, max_pages=80, quick=True)
            if _sitemap_pages:
                _top, _ = rank_by_goal(_sitemap_pages, goal, top_n=15)
                sitemap_context = format_for_navigator(_top if _top else _sitemap_pages[:15])
        except Exception as _se:
            print(f"  [sitemap] skipped: {_se}")

        # Pre-navigation planning: ask LLM which URL best matches the goal.
        # If it says "fail", raise immediately — content is not on this site.
        _plan_start_url  = start_url  # may be overridden by planner goto
        _plan_alternatives: list[str] = []  # planner's ranked backup URLs for saturation
        if _sitemap_pages:
            print(f"  [playwright] planning: asking LLM to pick best URL from {len(_sitemap_pages)} pages...")
            _plan = _plan_from_sitemap(_sitemap_pages, goal, model)
            if _plan:
                if _plan.get("action") == "fail":
                    reason = _plan.get("reason", "content not found on this site")
                    print(f"  [playwright] planner: fail — {reason}")
                    raise RuntimeError(f"navigator gave up: {reason}")
                elif _plan.get("action") == "goto" and _plan.get("url"):
                    _plan_start_url    = _plan["url"]
                    _planner_chose     = True
                    _plan_reason       = _plan.get("reason", "")
                    _plan_alternatives = [u for u in _plan.get("alternatives", []) if u != _plan_start_url]
                    alt_str = ", ".join(_plan_alternatives) if _plan_alternatives else "none"
                    print(f"  [playwright] planner: goto {_plan_start_url}"
                          + (f"  — {_plan_reason}" if _plan_reason else ""))
                    if _plan_alternatives:
                        print(f"  [playwright] planner alternatives: {alt_str}")

        page.goto(_plan_start_url, wait_until="domcontentloaded")
        _settle(page)
        history.append({"url": page.url, "title": page.title(), "note": "", "via": ""})
        if _planner_chose:
            _last_action_note = (
                "Note: the planner pre-selected this page as the best match from the full "
                "site index. If this page is topically related to the goal, prefer 'extract' "
                "over 'backtrack' — the synthesis step will extract only what is relevant."
            )
        _p = _take_screenshot(page, run_id, 0, "goto")
        if _p:
            screenshots.append(_p)

        for step in range(max_steps):
            snapshot = _page_snapshot(page)
            _url_visit_count[snapshot["url"]] = _url_visit_count.get(snapshot["url"], 0) + 1
            print(f"  [playwright] step {step+1}/{max_steps}  {snapshot['url'][:70]}")

            # Force fail if we've returned to the same page too many times without progress
            if _url_visit_count[snapshot["url"]] >= 4:
                reason = (f"Stuck: visited {snapshot['url']} {_url_visit_count[snapshot['url']]} times "
                          f"without finding the goal. Content likely not available on this site.")
                print(f"  [playwright] auto-fail: {reason}")
                _p = _take_screenshot(page, run_id, step + 1, "fail")
                if _p:
                    screenshots.append(_p)
                _teardown(browser, page.url)
                raise RuntimeError(f"navigator gave up: {reason}")

            blocked_clicks = {
                h["via"] for h in history
                if h.get("note", "").startswith("backtracked") and h.get("via")
            }
            decision = _decide(snapshot, goal, history, model,
                               blocked_clicks=blocked_clicks or None,
                               sitemap_context=sitemap_context,
                               last_action_note=_last_action_note)
            action   = decision.get("action", "fail")

            _desc = ""
            if action == "fill":
                _desc = f": {decision.get('role','')} '{decision.get('name','')}' <- {decision.get('value','')!r}"
            elif action in ("click", "press"):
                _desc = f": {decision.get('text') or decision.get('key','')}"
            elif action == "goto":
                _desc = f": {decision.get('url','')[:60]}"
            elif action in ("fail", "backtrack"):
                _desc = f": {decision.get('reason','')}"
            print(f"  [playwright] decision -> {action}{_desc}")

            if action == "extract":
                _p = _take_screenshot(page, run_id, step + 1, "extract", full_page=True)
                if _p:
                    screenshots.append(_p)
                text      = _clean_full_text(page)
                final_url = page.url

                # ── Saturation check ────────────────────────────────────────
                # Score how completely the first page answers the goal.
                # If below threshold and the sitemap has more relevant pages,
                # extract from those too and merge before returning.
                _pages_extracted = 1
                if _sitemap_pages and _pages_extracted < MAX_EXTRACT_PAGES:
                    _completeness = _score_completeness(text, goal, model)
                    _score = _completeness["score"]
                    _missing = _completeness["missing"]
                    print(f"  [saturation] score={_score}/10  missing: {_missing[:80]}")

                    if _score < SATURATION_THRESHOLD:
                        _visited = {h["url"] for h in history} | {final_url}
                        # Prefer planner's ranked alternatives; fall back to keyword re-rank
                        _alt_pages = [{"url": u} for u in _plan_alternatives if u not in _visited]
                        if not _alt_pages:
                            try:
                                from skills.sitemap_skill import rank_by_goal
                                _remaining = [p for p in _sitemap_pages if p["url"] not in _visited]
                                _aug_goal  = goal + " " + _missing
                                _alt_pages, _ = rank_by_goal(_remaining, _aug_goal, top_n=MAX_EXTRACT_PAGES - 1)
                            except Exception:
                                _alt_pages = []
                        _next_pages = _alt_pages

                        _prev_score = _score
                        for _np in _next_pages:
                            if _pages_extracted >= MAX_EXTRACT_PAGES:
                                break
                            print(f"  [saturation] pulling additional page: {_np['url']}")
                            try:
                                page.goto(_np["url"], wait_until="domcontentloaded")
                                _settle(page)
                                _extra = _clean_full_text(page)
                                if _extra:
                                    text += f"\n\n---\nSource: {_np['url']}\n\n{_extra}"
                                    final_url = _np["url"]
                                    _pages_extracted += 1
                                    _p2 = _take_screenshot(page, run_id, step + 2 + _pages_extracted, "extract")
                                    if _p2:
                                        screenshots.append(_p2)
                            except Exception as _fe:
                                print(f"  [saturation] fetch failed: {_fe}")
                                continue

                            _completeness = _score_completeness(text, goal, model, prior_score=_prev_score)
                            _score = max(_completeness["score"], _prev_score)  # enforce floor client-side
                            _missing = _completeness["missing"]
                            print(f"  [saturation] score={_score}/10  missing: {_missing[:80]}")
                            if _score >= SATURATION_THRESHOLD or _score == _prev_score:
                                break  # saturated or not improving — stop pulling
                            _prev_score = _score

                    print(f"  [saturation] done — {_pages_extracted} page(s), final score={_score}/10")
                # ── End saturation ───────────────────────────────────────────

                _teardown(browser, final_url)
                return text, final_url, screenshots, history

            elif action == "fail":
                _p = _take_screenshot(page, run_id, step + 1, "fail")
                if _p:
                    screenshots.append(_p)
                reason = decision.get("reason", "unknown")
                _teardown(browser, page.url)
                raise RuntimeError(f"navigator gave up: {reason}")

            else:
                # Annotate the current page with a "leaving" note before navigation
                if action == "backtrack" and history:
                    history[-1]["note"] = f"backtracked: {decision.get('reason','off-topic')}"

                _url_before = page.url
                navigated = _execute(page, decision, history, timeout_ms)
                if navigated:
                    _settle(page)
                    visited_urls = {h["url"] for h in history}
                    if page.url not in visited_urls:
                        via = decision.get("text", "") if action == "click" else ""
                        history.append({"url": page.url, "title": page.title(), "note": "", "via": via})
                        _last_action_note = ""
                    elif page.url == _url_before and action == "click":
                        # URL unchanged after first settle — SPA client-side routers lag
                        # behind load events. Poll for an actual URL change before giving up.
                        if _wait_for_url_change(page, _url_before, timeout_s=6.0):
                            _settle(page)  # let the new page finish rendering
                            if page.url not in {h["url"] for h in history}:
                                via = decision.get("text", "")
                                history.append({"url": page.url, "title": page.title(), "note": "", "via": via})
                            _last_action_note = ""
                        else:
                            # Truly non-navigating — modal, anchor, or dead link
                            _clicked = decision.get("text", "this element")
                            _last_action_note = (
                                f"Note: clicking '{_clicked}' did not navigate — the URL is unchanged. "
                                f"A modal or overlay may have opened. Check the updated ARIA tree below "
                                f"and act on any new input, dialog, or search field that appeared. "
                                f"Do NOT click '{_clicked}' again."
                            )
                    else:
                        _last_action_note = ""
                    _p = _take_screenshot(page, run_id, step + 1, action)
                    if _p:
                        screenshots.append(_p)
                else:
                    # Action was blocked or the element wasn't found
                    if action == "fill":
                        role  = decision.get("role", "searchbox")
                        name  = decision.get("name", "")
                        _last_action_note = (
                            f"Note: fill failed — could not find a {role} named '{name}' on this page. "
                            f"The ARIA tree below shows what IS available. "
                            f"Try a different locator, a different action, or use 'fail' if stuck."
                        )
                    elif action == "click":
                        _last_action_note = (
                            f"Note: click '{decision.get('text','')}' was blocked (previously led to a dead end). "
                            f"Choose a different link or action."
                        )

        print(f"  [playwright] max steps reached after visiting {len(history)} page(s) — extracting current page")
        _p = _take_screenshot(page, run_id, max_steps, "extract", full_page=True)
        if _p:
            screenshots.append(_p)
        text      = _clean_full_text(page)
        final_url = page.url
        _teardown(browser, final_url)
        return text, final_url, screenshots, history

    except RuntimeError:
        _teardown(browser if "browser" in dir() else None, "")
        raise
    except Exception as e:
        _teardown(browser if "browser" in dir() else None, "")
        raise RuntimeError(f"playwright error: {e}") from e


# ---------------------------------------------------------------------------
# Task string parser
# ---------------------------------------------------------------------------

def parse_playwright_task(task: str) -> tuple[str, str]:
    """
    Extract (start_url, goal) from a task string like:
      '/playwright go to flavortotaste.com, find the fruit-flavored water recipe'
      '/playwright https://example.com summarize the pricing page'
    Returns (url, goal).
    """
    task = re.sub(r"^/(playwright|browser)\s*", "", task, flags=re.IGNORECASE).strip()

    m = re.search(
        r"(?:go\s+to\s+|visit\s+|navigate\s+to\s+|open\s+)?([a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(?:/[^\s,]*)?|https?://\S+)",
        task, re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"No URL found in task: {task!r}")

    url  = m.group(1)
    goal = (task[: m.start()] + " " + task[m.end() :]).strip()
    goal = re.sub(r"^(go\s+to|visit|navigate\s+to|open)\s*", "", goal, flags=re.IGNORECASE).strip(" ,")
    goal = re.sub(r"^(and|then|,)\s+", "", goal, flags=re.IGNORECASE).strip()

    # Strip any remaining bare URLs / hostnames from the goal — they belong to
    # the navigation path, not the semantic content goal.
    goal = re.sub(r"https?://\S+", "", goal)
    goal = re.sub(
        r"\b[a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(?:/[^\s,]*)?\b", "", goal
    )

    # Strip file-save instructions — the navigator doesn't write files;
    # that's handled by the synthesis step after extraction.
    goal = re.sub(
        r",?\s*(save|write|output)\s+(it\s+)?to\s+\S+", "", goal, flags=re.IGNORECASE
    )

    goal = re.sub(r"\s{2,}", " ", goal).strip(" ,")
    if not goal:
        goal = "Extract the main content of this page"

    return url, goal
