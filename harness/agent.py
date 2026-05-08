"""
Agentic research + write + verify harness for qwen2.5 via Ollama.

Turn 1: vision preprocessing (if images detected) + 2 web searches + synthesis
Turn 2: Python writes output directly to disk
Turn 3: Wiggum loop — evaluate, revise, verify until PASS or max rounds

Usage:
    python agent.py "Search for X and save to ~/Desktop/harness-engineering/output.md"
    python agent.py "Analyze ~/Desktop/chart.png and save to ~/Desktop/analysis.md"
    python agent.py --no-wiggum "..."   # skip verification loop

Environment:
    conda activate ollama-pi
"""

import os
import random
import re
import subprocess
import sys
import textwrap
import warnings
from pathlib import Path

# Load .env from project root if present
from harness.config import ROOT as _ROOT
_env_file = _ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# Suppress pydub's ffmpeg-not-found warning — ffmpeg is not used in this pipeline
warnings.filterwarnings("ignore", message="Couldn't find ffmpeg", category=RuntimeWarning)

from harness.inference import OllamaLike as _OllamaLike

# Keep models hot between calls — avoids 30-60s cold reload between pipeline stages.
# OLLAMA_KEEP_ALIVE env var pins keep_alive globally (e.g. -1 to force always-on).
# If unset, _estimate_keep_alive() computes a per-run value from historical data.
# When INFERENCE_BACKEND=vllm, keep_alive is silently ignored (vLLM manages lifetime).
_KEEP_ALIVE_OVERRIDE = os.environ.get("OLLAMA_KEEP_ALIVE")
_KEEP_ALIVE = int(_KEEP_ALIVE_OVERRIDE) if _KEEP_ALIVE_OVERRIDE is not None else None


def _estimate_keep_alive(task_type: str, explicit_skills: set, use_wiggum: bool) -> int:
    """
    Estimate keep_alive (seconds) for this run.

    Strategy:
      1. Read last 100 runs from runs.jsonl, filter to matching task type.
      2. Take the 90th-percentile run_duration_s + 20% buffer.
      3. Fall back to skill-aware heuristics if history is thin (< 5 matching runs).

    The env var OLLAMA_KEEP_ALIVE always wins if set — this function is never
    called in that case.
    """
    # Standalone skills with short, bounded durations
    if explicit_skills & {"github", "email", "review", "recall", "queue"}:
        return 90
    if explicit_skills & {"lit-review"}:
        return -1   # keep alive indefinitely — pipeline runs for minutes to hours

    # Try historical data
    try:
        import json as _json
        from harness.config import RUNS_FILE as _RUNS_FILE
        _log = str(_RUNS_FILE)
        durations = []
        with open(_log, encoding="utf-8") as _f:
            lines = _f.readlines()
        for line in lines[-100:]:
            line = line.strip()
            if not line:
                continue
            try:
                r = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            dur = r.get("run_duration_s")
            # Match on task_type if known; otherwise use all runs
            if dur and dur > 0:
                if task_type and r.get("task_type") == task_type:
                    durations.append(dur)
        # Fall back to all task types if too few matching
        if len(durations) < 5:
            durations = []
            for line in lines[-100:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                dur = r.get("run_duration_s")
                if dur and dur > 0:
                    durations.append(dur)
        if len(durations) >= 5:
            durations.sort()
            p90 = durations[int(len(durations) * 0.9)]
            return int(p90 * 1.2)
    except Exception:
        pass

    # Heuristic fallback
    base = 300
    if use_wiggum:
        base += 150
    if "panel" in explicit_skills:
        base += 200
    if "deep" in explicit_skills:
        base = int(base * 1.5)
    if "annotate" in explicit_skills:
        base = max(base, 240)
    return base


ollama = _OllamaLike(keep_alive=_KEEP_ALIVE)

from duckduckgo_search import DDGS
from harness.logger import RunTrace
from harness.memory import MemoryStore, assess_novelty
from harness.planner import Plan, make_plan
from harness.security import check_file_path, check_output_path, check_python_code, scan_for_injection, strip_injection_candidates
from harness.skills import auto_activate, get_prompt_injections, merge_skills, parse_skills, run_annotate_standalone, run_post_synthesis, skills_at_hook
from harness.vision import detect_image_paths, extract_image_context
from harness.wiggum import loop as wiggum_loop

try:
    from markitdown import MarkItDown
    _md_converter = MarkItDown(enable_plugins=False)
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False

MODEL = os.environ.get("HARNESS_PRODUCER_MODEL", "pi-qwen-32b").strip()
COMPRESS_MODEL = os.environ.get("COMPRESS_MODEL", MODEL).strip()  # lighter model for compress_knowledge / plan_query

# If the configured models aren't served, fall back to whatever vLLM has loaded.
# This prevents 404s when switching between model configs without restarting the server.
try:
    from harness import inference as _inf_boot
    _active = _inf_boot.get_active_vllm_model()
    if _active:
        import json as _jb
        import urllib.request as _ur
        _vb = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")
        _ids = {m["id"] for m in _jb.loads(_ur.urlopen(f"{_vb}/models", timeout=2).read())["data"]}
        if MODEL not in _ids and _active:
            MODEL = _active
        if COMPRESS_MODEL not in _ids and _active:
            COMPRESS_MODEL = _active
except Exception:
    pass

# Models that think by default and require think=False to produce immediate output.
# Thinking mode consumes num_predict budget before the response starts, which
# stalls synthesis on the default 8192 token limit.
_THINKING_MODELS = {"qwen3", "qwq"}

def _is_thinking_model(model_name: str) -> bool:
    name = (model_name or "").lower()
    return any(tag in name for tag in _THINKING_MODELS)

def _synth_options(producer_model: str) -> dict:
    """Return ollama options for a synthesis call.
    HARNESS_PRODUCER_THINK=1 forces thinking on (and doubles num_predict budget).
    HARNESS_SYNTH_TEMPERATURE overrides the default synthesis temperature (used by RL data collection).
    Thinking models default to think=False to avoid consuming the token budget silently.
    """
    _temp = float(os.environ.get("HARNESS_SYNTH_TEMPERATURE", "0.1"))
    opts = {"temperature": _temp, "num_predict": 16384}
    think_override = os.environ.get("HARNESS_PRODUCER_THINK", "")
    if think_override == "1":
        opts["think"] = True
        opts["num_predict"] = 16384  # thinking tokens eat the budget before output starts
    elif _is_thinking_model(producer_model):
        opts["think"] = False
    return opts

# ---------------------------------------------------------------------------
# Synthesis instruction — the text appended to every synthesis prompt.
# This is the primary target for autoresearch.py experiments.
# autoresearch.py reads and rewrites SYNTH_INSTRUCTION between the sentinels.
# Do not rename the sentinels or move them off their own lines.
# ---------------------------------------------------------------------------
# AUTORESEARCH:SYNTH_INSTRUCTION:BEGIN
SYNTH_INSTRUCTION = (
    "output ONLY the markdown starting with #  Generate 5 best practices for designing effective prompts for large language models, presented as a concise narrative flow. Each practice should be explained in 1-2 sentences, focusing on how it improves model performance or output quality. Avoid listing or numbered formats; instead, connect the practices logically to show their cumulative impact on prompt engineering."
)
# AUTORESEARCH:SYNTH_INSTRUCTION:END

# AUTORESEARCH:SYNTH_INSTRUCTION_COUNT:BEGIN
SYNTH_INSTRUCTION_COUNT = (
    "output ONLY the markdown starting with #  Specify exactly 5 best practices for prompt design in large language models. These should be distinct, actionable techniques that can be applied by practitioners to improve output quality and model alignment."
)
# AUTORESEARCH:SYNTH_INSTRUCTION_COUNT:END

# Fallback instruction for non-technical tasks (recipes, general knowledge, etc.)
# Used when _is_technical_task() returns False so the model doesn't hallucinate code blocks.
# AUTORESEARCH:SYNTH_INSTRUCTION_PROSE:BEGIN
SYNTH_INSTRUCTION_PROSE = (
    "output ONLY the markdown starting with #  Write a single cohesive paragraph of 200-300 words that explains the core principles of effective prompt engineering for large language models. Structure the explanation as a logical narrative that builds from foundational concepts to advanced techniques, showing how each element contributes to better model performance. Use clear, accessible language without technical jargon."
)
# AUTORESEARCH:SYNTH_INSTRUCTION_PROSE:END

_TECHNICAL_KEYWORDS = frozenset({
    "code", "coding", "implement", "library", "api", "sdk", "python", "javascript",
    "typescript", "rust", "golang", "java", "c++", "c#", "sql", "database", "query",
    "algorithm", "function", "class", "module", "package", "framework", "deploy",
    "docker", "kubernetes", "ci/cd", "pipeline", "bash", "shell", "cli", "regex",
    "async", "thread", "concurrency", "memory", "performance", "benchmark", "test",
    "debugging", "refactor", "architecture", "microservice", "endpoint", "rest",
    "graphql", "websocket", "embedding", "llm", "transformer", "fine-tun",
    "inference", "tokenizer", "tensor", "gpu", "cuda", "vllm", "ollama",
})

_ANALYSIS_PHRASES = frozenset({
    "analyze", "analyse", "extract", "identify patterns", "score trajectory",
    "summarize the", "summarise the", "characterize", "characterise",
    "trace how", "identify which", "identify what", "read and report",
    "what the evaluator", "what types of changes", "which dimensions",
    "trends report", "analytical report", "read wiki", "read runs",
    "read autoresearch", "read bench", "read the current",
})

def _is_technical_task(task: str) -> bool:
    lower = task.lower()
    # Data-analysis tasks that read local files should use prose, not code tutorials
    if any(phrase in lower for phrase in _ANALYSIS_PHRASES):
        # Only override to prose if there are no explicit coding keywords
        if not any(kw in lower for kw in ("implement", "code", "script", "function", "api", "deploy")):
            return False
    return any(kw in lower for kw in _TECHNICAL_KEYWORDS)


def _synth_instruction(task: str) -> str:
    # HARNESS_SYNTH_INSTRUCTION env var overrides the experiment instruction — used by
    # RL data collection so diverse tasks aren't forced into the autoresearch template.
    override = os.environ.get("HARNESS_SYNTH_INSTRUCTION", "")
    if override:
        return override
    return SYNTH_INSTRUCTION if _is_technical_task(task) else SYNTH_INSTRUCTION_PROSE


SEARCHES_PER_TASK = 2        # minimum searches before novelty gating kicks in
SEARCH_QUALITY_FLOOR = 1800  # total merged chars — below this, run one more search
MAX_SEARCH_ROUNDS   = 5      # hard cap regardless of novelty
NOVELTY_THRESHOLD   = 3      # 0–10; stop if new results score below this
NOVELTY_EPSILON     = 0.15   # ε-greedy: pass sub-threshold results through 15% of the time
KNOWLEDGE_MAX_CHARS = 1500   # cap on rolling knowledge state fed to novelty scoring
MAX_RESULTS_PER_SEARCH = 5
PYTHON_TOOL_ROUNDS = 3       # max rounds in the run_python tool loop
PYTHON_TIMEOUT = 10          # seconds before code execution is killed

TEXT_EXTENSIONS = {".txt", ".py", ".json", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".xml", ".html"}
RICH_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".epub", ".htm"}
URL_ENRICH_COUNT = 2        # how many search-result URLs to fetch full content for (0 = disabled)
URL_ENRICH_MAX_CHARS = 8000 # cap per URL to avoid context bloat

PYTHON_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Execute Python code and return stdout/stderr. Use for data processing, computation, or analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"}
                },
                "required": ["code"]
            }
        }
    }
]


def _browser_state_file() -> str:
    import tempfile as _tf
    return os.path.join(_tf.gettempdir(), "harness_browser_state.json")


def _read_browser_state() -> dict:
    import json as _jbs
    try:
        p = _browser_state_file()
        if os.path.exists(p):
            return _jbs.loads(open(p, encoding="utf-8").read())
    except Exception:
        pass
    return {}


def _write_browser_state(data: dict):
    import json as _jbs
    try:
        with open(_browser_state_file(), "w", encoding="utf-8") as _f:
            _f.write(_jbs.dumps(data))
    except Exception:
        pass


def _clear_browser_state():
    try:
        os.unlink(_browser_state_file())
    except Exception:
        pass


# Module-level ref so the Popen handle is never GC'd while the browser should be alive.
_headed_browser_proc: "subprocess.Popen | None" = None


def web_search_headed(query: str, max_results: int = MAX_RESULTS_PER_SEARCH) -> list[dict]:
    """
    Open a visible Chromium window via CDP, navigate to DuckDuckGo, extract results.

    HARNESS_KEEP_BROWSER=1   — leave the browser running after the task (writes state file)
    HARNESS_REUSE_BROWSER=1  — reconnect to an existing browser via CDP instead of launching fresh
    """
    global _headed_browser_proc

    import urllib.parse as _up
    import time as _tb
    import subprocess as _spb
    import platform as _plat
    try:
        from playwright.sync_api import sync_playwright as _swp
    except ImportError:
        return []

    _keep  = os.environ.get("HARNESS_KEEP_BROWSER")  == "1"
    _reuse = os.environ.get("HARNESS_REUSE_BROWSER") == "1"
    _PORT  = int(os.environ.get("HARNESS_CDP_PORT", "9222"))

    url     = "https://duckduckgo.com/?q=" + _up.quote_plus(query) + "&ia=web"
    results: list[dict] = []
    _browser_proc = None  # local handle; also stored at module level when _keep=True

    # Use the non-context-manager form so we control when playwright stops.
    # Calling _pw_ctx.stop() (which sends Browser.close via CDP) is skipped when
    # we want to keep the browser alive.
    _pw_ctx = _swp()
    _pw     = _pw_ctx.start()

    try:
        browser = None

        # ── Try reconnecting to an existing browser ───────────────���──────────
        if _reuse:
            state = _read_browser_state()
            port  = state.get("cdp_port", _PORT)
            try:
                browser = _pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                print(f"  [headed] reconnected to browser on port {port}")
            except Exception as _re:
                print(f"  [headed] CDP reconnect failed ({_re}), launching fresh")
                browser = None

        # ── Launch a fresh browser as a fully-detached subprocess ────────────
        if browser is None:
            _exe = _pw.chromium.executable_path
            if _exe:
                # Windows: DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP breaks the
                # child out of the parent's Job Object so it survives agent.py exiting.
                # Unix:    start_new_session=True (setsid) achieves the same.
                if _plat.system() == "Windows":
                    _flags = _spb.DETACHED_PROCESS | _spb.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                    _browser_proc = _spb.Popen(
                        [_exe, f"--remote-debugging-port={_PORT}",
                         "--no-first-run", "--no-default-browser-check",
                         "--no-sandbox", "about:blank"],
                        stdout=_spb.DEVNULL, stderr=_spb.DEVNULL,
                        creationflags=_flags,
                    )
                else:
                    _browser_proc = _spb.Popen(
                        [_exe, f"--remote-debugging-port={_PORT}",
                         "--no-first-run", "--no-default-browser-check",
                         "--no-sandbox", "about:blank"],
                        stdout=_spb.DEVNULL, stderr=_spb.DEVNULL,
                        start_new_session=True,
                    )
                # Wait until CDP endpoint responds (up to 5 s)
                import urllib.request as _urq
                for _i in range(10):
                    _tb.sleep(0.5)
                    try:
                        _urq.urlopen(f"http://localhost:{_PORT}/json/version", timeout=1)
                        break
                    except Exception:
                        pass
                browser = _pw.chromium.connect_over_cdp(f"http://localhost:{_PORT}")
                _write_browser_state({"active": True, "cdp_port": _PORT,
                                      "pid": _browser_proc.pid, "ts": _tb.time()})
                print(f"  [headed] launched detached browser on CDP port {_PORT} (pid={_browser_proc.pid})")
            else:
                # executable_path unavailable — fall back to playwright-managed launch.
                # Browser will close when this task finishes; _keep is disabled.
                browser = _pw.chromium.launch(headless=False, slow_mo=150)
                _keep = False
                print("  [headed] fallback: playwright-managed launch (no persistence)")

        # ── Navigate & scrape ────────────────────────────────────────────────
        _ctx  = browser.contexts[0] if browser.contexts else browser.new_context(
            viewport={"width": 1280, "height": 860})
        _page = _ctx.pages[0] if _ctx.pages else _ctx.new_page()

        print(f"  [headed] navigating to: {url[:80]}")
        _page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        try:
            _page.wait_for_selector('article[data-testid="result"]', timeout=6_000)
        except Exception:
            _page.wait_for_timeout(2_500)

        articles = _page.query_selector_all('article[data-testid="result"]')
        if not articles:
            articles = _page.query_selector_all('article.nrn-react-div')

        for art in articles[:max_results]:
            try:
                link_el = (art.query_selector('a[data-testid="result-title-a"]')
                           or art.query_selector('h2 a'))
                if not link_el:
                    continue
                title = (link_el.inner_text() or "").strip()
                href  = link_el.get_attribute("href") or ""
                snip_el = (art.query_selector('[data-result="snippet"]')
                           or art.query_selector('[data-testid="result-snippet"]')
                           or art.query_selector('div > span'))
                body = (snip_el.inner_text() or "").strip() if snip_el else ""
                if title and href:
                    results.append({"title": title, "href": href, "body": body})
            except Exception:
                pass

        _page.wait_for_timeout(800)

        # ── Keep or close ────────────────────────────────────────────────────
        if _keep:
            state = _read_browser_state()
            state.update({"active": True, "last_url": _page.url,
                           "last_query": query, "last_ts": _tb.time()})
            _write_browser_state(state)
            # Pin the Popen handle at module level so it is never GC'd.
            _headed_browser_proc = _browser_proc
            print(f"  [headed] browser kept alive at {_page.url}")
            # Do NOT call _pw_ctx.stop() — that sends Browser.close via CDP.
            # The playwright server will exit with the agent process; Chromium lives on.
        else:
            browser.close()
            if _browser_proc:
                _browser_proc.terminate()
            _headed_browser_proc = None
            _clear_browser_state()
            _pw_ctx.stop()  # type: ignore[attr-defined]

        if results:
            print(f"  [headed] extracted {len(results)} result(s) from browser")
        else:
            print("  [headed] no results extracted from DOM — will fall back to DDGS")

    except Exception as _e:
        print(f"  [headed] playwright error: {_e} — falling back to DDGS")
        if _browser_proc:
            try:
                _browser_proc.terminate()
            except Exception:
                pass
        _headed_browser_proc = None
        try:
            _pw_ctx.stop()  # type: ignore[attr-defined]
        except Exception:
            pass

    return results


def web_search_raw(query: str, max_results: int = MAX_RESULTS_PER_SEARCH) -> list[dict]:
    """Return raw result dicts from DDGS (or headed playwright), using SQLite cache (24 h TTL)."""
    if os.environ.get("HARNESS_HEADED") == "1":
        headed = web_search_headed(query, max_results)
        if headed:
            return headed
        print("  [headed] falling back to DDGS for structured results")

    try:
        from harness.search_cache import cached_search
        def _ddgs(q: str, n: int) -> list[dict]:
            with DDGS() as ddgs:
                return list(ddgs.text(q, max_results=n))
        return cached_search(query, _ddgs, max_results=max_results)
    except ImportError:
        pass  # search_cache not available — fall through to direct DDGS
    except Exception as e:
        print(f"  [web_search error] {e}")
        return []

    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        print(f"  [web_search error] {e}")
        return []


def format_results(results: list[dict]) -> str:
    lines = []
    for r in results:
        lines.append(f"**{r['title']}**\n{r['href']}\n{r['body']}\n")
    return "\n".join(lines)


def detect_task_urls(task: str) -> list[str]:
    """Find http(s):// URLs in the task string (excluding the .md output path)."""
    return re.findall(r'https?://[^\s"\'<>]+', task)


def fetch_task_url_context(urls: list[str]) -> str:
    """Fetch and concatenate content from task-level URLs using MarkItDown."""
    if not MARKITDOWN_AVAILABLE or not urls:
        return ""
    blocks = []
    for url in urls:
        print(f"  [fetch_url] {url[:80]}...")
        content = fetch_url_content(url)
        if content:
            blocks.append(f"--- Source: {url} ---\n{content}")
            print(f"  [fetch_url] {len(content)} chars")
        else:
            print("  [fetch_url] failed or empty — skipping")
    return "\n\n".join(blocks)


def detect_text_files(task: str, exclude_path: str = None) -> list[str]:
    """Find readable file paths referenced in the task (non-image, non-output).
    Returns both plain-text and rich-document paths; caller uses extension to route.
    Matches absolute paths (~/..., C:/..., /...) and relative paths (wiki/log.md, runs.jsonl).
    """
    # Absolute path patterns
    abs_pattern = r'(~[\w/\\.\-]+|[A-Za-z]:[\w/\\.\-]+|/[\w/.\-]+)'
    # Relative path pattern: bare filenames and subdir/file.ext with known extensions
    known_exts = "|".join(
        e.lstrip(".") for e in (TEXT_EXTENSIONS | RICH_EXTENSIONS)
    )
    rel_pattern = rf'(?<![/\w])([a-zA-Z][\w\-]*(?:/[\w\-\.]+)*\.(?:{known_exts}))'
    candidates = re.findall(abs_pattern, task) + re.findall(rel_pattern, task)
    seen = set()
    found = []
    from harness.config import ROOT as _CWD_ROOT
    cwd = str(_CWD_ROOT)
    for c in candidates:
        expanded = os.path.expanduser(c)
        _, ext = os.path.splitext(expanded)
        if ext.lower() not in TEXT_EXTENSIONS and ext.lower() not in RICH_EXTENSIONS:
            continue
        # Resolve relative paths against the harness directory
        if not os.path.isabs(expanded):
            expanded = os.path.join(cwd, expanded)
        abs_expanded = os.path.abspath(expanded)
        if exclude_path and abs_expanded == os.path.abspath(os.path.expanduser(exclude_path)):
            continue
        if abs_expanded in seen:
            continue
        if os.path.isfile(expanded):
            seen.add(abs_expanded)
            found.append(expanded)
    return found


def read_file_context(paths: list[str], task: str = "") -> str:
    """Read files and return concatenated content blocks.
    Rich documents (PDF, DOCX, XLSX, etc.) are converted to markdown via MarkItDown.
    Plain text files are read directly.
    Large files (> LARGE_FILE_THRESHOLD chars) are context-extracted via chunker."""
    from harness.chunker import extract_paper_context, LARGE_FILE_THRESHOLD
    blocks = []
    for p in paths:
        ok, reason = check_file_path(p)
        if not ok:
            print(f"  [security] read_file blocked: {reason}")
            continue
        _, ext = os.path.splitext(p)
        if ext.lower() in RICH_EXTENSIONS and MARKITDOWN_AVAILABLE:
            try:
                result = _md_converter.convert(p)
                content = result.text_content or ""
                print(f"  [markitdown] {os.path.basename(p)} -> {len(content)} chars")
            except Exception as e:
                print(f"  [markitdown error] {os.path.basename(p)}: {e} — skipping")
                continue
            # OCR fallback: if MarkItDown output is sparse (scanned/image-heavy PDF),
            # try PyMuPDF then vision model for a better extraction
            if ext.lower() == ".pdf":
                try:
                    from harness.ocr import is_sparse, ocr_pdf
                    if is_sparse(content, p):
                        print(f"  [ocr] {os.path.basename(p)} is sparse — attempting OCR fallback")
                        content = ocr_pdf(p, task=task, markitdown_content=content)
                except Exception as e:
                    print(f"  [ocr] fallback failed (non-fatal): {e}")
        else:
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                print(f"  [read_file] {p} ({len(content)} chars)")
            except Exception as e:
                print(f"  [read_file error] {p}: {e}")
                continue
        # Injection scan applies to all sources
        clean, matches = scan_for_injection(content, source=os.path.basename(p))
        if not clean:
            print(f"  [security] injection pattern in {os.path.basename(p)} ({len(matches)} match(es)) — stripping")
            content, removed = strip_injection_candidates(content)
            print(f"  [security] removed {removed} line(s) from file")
        # Large file: extract most relevant context within budget
        if len(content) > LARGE_FILE_THRESHOLD:
            content = extract_paper_context(content, task=task, source=os.path.basename(p))
        blocks.append(f"--- {os.path.basename(p)} ---\n{content}")
    return "\n\n".join(blocks)


def execute_python(code: str) -> str:
    """Run Python code in a subprocess. Returns stdout + stderr (truncated to 4000 chars)."""
    ok, reason = check_python_code(code)
    if not ok:
        print(f"  [security] run_python blocked: {reason}")
        return f"[blocked] {reason}"
    from harness.config import ROOT
    _workspace = str(ROOT / "agent-workspace")
    _preamble = (
        f"import sys\n"
        f"sys.path.insert(0, {repr(str(ROOT))})\n"
        f"sys.path.insert(0, {repr(_workspace)})\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(_preamble + code)],
            capture_output=True, text=True, timeout=PYTHON_TIMEOUT,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output[:4000] if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return f"[timeout] code exceeded {PYTHON_TIMEOUT}s"
    except Exception as e:
        return f"[error] {e}"


def run_tool_loop(task: str, research_context: str, trace: RunTrace, producer_model: str = MODEL) -> str:
    """
    Optional pre-synthesis tool loop: lets the model call run_python for data tasks.
    Returns accumulated execution output (empty string if model doesn't call tools).
    """
    messages = [{
        "role": "user",
        "content": (
            f"Task: {task}\n\n"
            f"Research context:\n{research_context}\n\n"
            "If this task requires data processing, computation, or analysis that "
            "would benefit from running Python code, use the run_python tool. "
            "Otherwise respond with exactly: no code needed"
        )
    }]

    execution_log = []
    for _ in range(PYTHON_TOOL_ROUNDS):
        response = ollama.chat(
            model=producer_model,
            messages=messages,
            tools=PYTHON_TOOLS,
            options={"temperature": 0.1},
        )
        trace.log_usage(response, stage="tool_loop")
        msg = response["message"]
        turn_thinking = getattr(getattr(response, "message", None), "thinking", None) or ""
        messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": msg.get("tool_calls", [])})

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            break

        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name") == "run_python":
                code = fn.get("arguments", {}).get("code", "")
                print(f"  [run_python] executing ({len(code)} chars)...")
                result = execute_python(code)
                execution_log.append(f"```python\n{code}\n```\nOutput:\n```\n{result}\n```")
                trace.log_tool_call("run_python", code[:80], len(result))
                trace.log_step("tool_loop", thinking=turn_thinking, tool="run_python",
                               query=code[:120], result_chars=len(result))
                turn_thinking = ""  # consumed — only attribute to the first call in this turn
                messages.append({"role": "tool", "content": result, "name": "run_python"})

    return "\n\n".join(execution_log)


def fetch_url_content(url: str) -> str:
    """Fetch a URL and convert its HTML to markdown via MarkItDown. Returns empty string on failure."""
    from harness.skills.youtube_transcribe import is_youtube_url, is_media_url, transcribe_youtube, transcribe_media_url
    if is_youtube_url(url):
        try:
            return transcribe_youtube(url)
        except Exception as e:
            print(f"  [youtube] transcription error (skipping): {e}")
            return ""
    if is_media_url(url):
        try:
            return transcribe_media_url(url)
        except Exception as e:
            print(f"  [media] transcription error (skipping): {e}")
            return ""
    if not MARKITDOWN_AVAILABLE:
        return ""
    try:
        result = _md_converter.convert(url)
        text = (result.text_content or "").strip()
        if len(text) > URL_ENRICH_MAX_CHARS:
            text = text[:URL_ENRICH_MAX_CHARS] + "\n[truncated]"
        return text
    except Exception:
        return ""


def enrich_with_page_content(results: list[dict], count: int, knowledge_state: str = "") -> str:
    """Fetch full page content for the top `count` search results.
    Skips URLs whose snippet is already well-covered in knowledge_state (>80% word overlap).
    Returns a context block."""
    if not MARKITDOWN_AVAILABLE or count == 0:
        return ""
    known_words = set(knowledge_state.lower().split()) if knowledge_state else set()
    blocks = []
    fetched = 0
    for r in results:
        if fetched >= count:
            break
        url = r.get("href", "")
        if not url.startswith("http"):
            continue
        if known_words:
            snippet_words = set(r.get("body", "").lower().split())
            overlap = len(snippet_words & known_words) / max(len(snippet_words), 1)
            if overlap > 0.8:
                print(f"  [markitdown] skipping {url[:50]} — {overlap:.0%} covered")
                continue
        print(f"  [markitdown] fetching {url[:60]}...")
        content = fetch_url_content(url)
        if content:
            blocks.append(f"**Full page: {r.get('title', url)}**\n{url}\n\n{content}")
            fetched += 1
            print(f"    -> {len(content)} chars")
        else:
            print("    -> failed or empty")
    return "\n\n---\n\n".join(blocks)


def merge_results(sets: list[list[dict]]) -> list[dict]:
    """Merge multiple result sets, deduplicating by URL."""
    seen = set()
    merged = []
    for result_set in sets:
        for r in result_set:
            url = r.get("href", "")
            if url not in seen:
                seen.add(url)
                merged.append(r)
    return merged


COMPRESS_PROMPT = """\
Current knowledge summary:
{current_state}

New search results to incorporate:
{new_results}

Update the summary to include the new information. Be concise — 5–8 bullet points, \
each starting with a key fact. Do not exceed {max_chars} characters total.
Output ONLY the bullet points, nothing else."""


def compress_knowledge(current_state: str, new_results: list[dict],
                       producer_model: str = MODEL, trace=None) -> str:
    """
    Compress accumulated search results into a rolling bullet-point knowledge state.
    Round 1 (empty current_state): returns raw body text — no model call.
    Round 2+: model call with num_predict=400 cap so it stays fast.
    """
    new_text = " ".join(r.get("body", "") for r in new_results)

    if not current_state:
        # First round — skip model call, just seed with raw bodies
        return new_text[:KNOWLEDGE_MAX_CHARS]

    prompt = COMPRESS_PROMPT.format(
        current_state=current_state,
        new_results=new_text[:800],
        max_chars=KNOWLEDGE_MAX_CHARS,
    )
    response = ollama.chat(
        model=COMPRESS_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "num_predict": 400},
    )
    if trace is not None:
        trace.log_usage(response, stage="compress_knowledge")
    return response["message"]["content"].strip()[:KNOWLEDGE_MAX_CHARS]


def plan_query(task: str, knowledge_state: str, round_num: int, producer_model: str = MODEL, trace=None) -> str:
    """
    Generate a search query for the given round.
    Round 1: derives query directly from task (no model call).
    Round 2+: targets gaps in knowledge_state via model call.
    Replaces generate_second_query() — knowledge-state-aware for all rounds.
    """
    if round_num == 1 or not knowledge_state:
        return re.sub(r"(?i)^search\s+(for\s+)?", "", task.split("save to")[0].strip()).strip().rstrip("and ,.")

    prompt = (
        f"Task: {task}\n\n"
        f"What is already known:\n{knowledge_state}\n\n"
        "Generate ONE search query to find important information about the task NOT yet covered above. "
        "Output ONLY the query string, nothing else."
    )
    response = ollama.chat(
        model=COMPRESS_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.3},
    )
    query_out = response["message"]["content"].strip().strip('"')
    if trace is not None:
        trace.log_usage(response, stage="search_query")
        thinking = getattr(getattr(response, "message", None), "thinking", None) or ""
        if thinking:
            trace.log_step("search_query", thinking=thinking, tool="web_search", query=query_out)
    return query_out


def gather_research(task: str, trace: RunTrace, planned_queries: list[str] = None, producer_model: str = MODEL, force_deep: bool = False, task_type: str = "") -> str:
    """
    Saturation-based search loop: runs up to MAX_SEARCH_ROUNDS searches, stopping
    early when new results score below NOVELTY_THRESHOLD against the accumulated
    knowledge state. Minimum SEARCHES_PER_TASK rounds always run before gating.

    force_deep=True (set by /deep skill) disables novelty gating and runs all rounds.
    planned_queries are used for rounds 1–N before switching to plan_query().
    Returns a merged context string ready for synthesis.

    When RESEARCH_CACHE=1 (set by autoresearch.py), the full output is cached in
    research_cache table (24 h TTL). Cache hits skip the entire search + compress loop.
    Disabled for force_deep runs to ensure fresh results.
    """
    # Research cache — opt-in, autoresearch only (avoids stale results in interactive use)
    _research_cache_enabled = os.environ.get("RESEARCH_CACHE") == "1" and not force_deep
    if _research_cache_enabled:
        try:
            from harness.search_cache import get_research, put_research
            _rc_hit = get_research(task, task_type)
            if _rc_hit:
                trace.data["novelty_scores"] = _rc_hit["novelty_scores"]
                trace.data["search_rounds"]  = _rc_hit["search_rounds"]
                print(f"  [rcache] research context served from cache ({len(_rc_hit['context'])} chars, {_rc_hit['search_rounds']} rounds skipped)")
                return _rc_hit["context"]
        except Exception as _e:
            print(f"  [rcache] cache lookup failed: {_e} — running search normally")

    all_result_sets  = []
    queries_used     = []
    knowledge_state  = ""
    novelty_scores   = []
    novelty_gate     = NOVELTY_THRESHOLD if not force_deep else -1   # -1 = never gate

    for round_num in range(1, MAX_SEARCH_ROUNDS + 1):
        # Query selection: planned first, then gap-targeted model call
        if planned_queries and round_num <= len(planned_queries):
            query = planned_queries[round_num - 1]
            print(f"  [web_search {round_num}] {query}  (planned)")
        else:
            query = plan_query(task, knowledge_state, round_num, producer_model=producer_model, trace=trace)
            suffix = "" if round_num == 1 else "  (gap-targeted)"
            print(f"  [web_search {round_num}] {query}{suffix}")

        results = web_search_raw(query)
        trace.log_tool_call("web_search", query, len(format_results(results)))

        # Novelty gate — only after minimum rounds have run (skipped when force_deep)
        if round_num > SEARCHES_PER_TASK:
            novelty = assess_novelty(results, knowledge_state)
            novelty_scores.append(novelty)
            gate_label = " (deep — no gate)" if force_deep else ""
            print(f"  [novelty] round {round_num}: {novelty}/10{gate_label}")
            if novelty < novelty_gate:
                if random.random() < NOVELTY_EPSILON:
                    print("  [novelty] saturation but eps-greedy pass-through -- continuing")
                else:
                    print("  [novelty] saturation — stopping search")
                    break
        elif round_num > 1:
            # Log novelty for rounds inside the minimum window (informational only)
            novelty = assess_novelty(results, knowledge_state)
            novelty_scores.append(novelty)
            print(f"  [novelty] round {round_num}: {novelty}/10  (below gate minimum — continuing)")

        all_result_sets.append(results)
        queries_used.append(query)
        knowledge_state = compress_knowledge(knowledge_state, results, producer_model=producer_model, trace=trace)

    # Log to trace
    trace.data["novelty_scores"]  = novelty_scores
    trace.data["search_rounds"]   = len(queries_used)

    # Merge and check quality floor
    merged      = merge_results(all_result_sets)
    merged_text = format_results(merged)
    total_chars = len(merged_text)
    print(f"  [research] merged {len(merged)} results, {total_chars} chars ({len(queries_used)} rounds)")
    trace.log_search_quality(total_chars)

    if total_chars < SEARCH_QUALITY_FLOOR:
        print(f"  [quality floor] {total_chars} < {SEARCH_QUALITY_FLOOR} — running fallback search")
        fallback_query = f"{queries_used[0]} examples implementation best practices"
        print(f"  [web_search fallback] {fallback_query}")
        results_fallback = web_search_raw(fallback_query)
        all_result_sets.append(results_fallback)
        queries_used.append(fallback_query)
        merged      = merge_results(all_result_sets)
        merged_text = format_results(merged)
        total_chars = len(merged_text)
        trace.log_tool_call("web_search", fallback_query, len(format_results(results_fallback)))
        trace.log_search_quality(total_chars)
        print(f"  [research] after fallback: {len(merged)} results, {total_chars} chars")

    # URL enrichment — disabled for enumerated tasks: full-page context causes
    # the model to produce flat lists instead of H2 sections, triggering count_check_retry.
    # Traces show this adds 300-1000s overhead (29-56% on top of synthesis) with no score gain.
    enrich_count = 0 if task_type == "enumerated" else URL_ENRICH_COUNT

    # URL enrichment — fetch full page content for top results via MarkItDown
    if enrich_count > 0 and MARKITDOWN_AVAILABLE:
        print(f"  [markitdown] enriching top {enrich_count} URL(s)...")
        page_content = enrich_with_page_content(merged, enrich_count, knowledge_state=knowledge_state)
        if page_content:
            merged_text = merged_text + "\n\n## Full page content\n\n" + page_content
            print(f"  [markitdown] added {len(page_content)} chars of page content")

    # Injection scan — strip suspicious lines from search results before synthesis
    clean, injection_matches = scan_for_injection(merged_text, source="web_search")
    if not clean:
        print(f"  [security] prompt injection detected in search results ({len(injection_matches)} match(es)) — stripping")
        for m in injection_matches:
            print(f"    {m}")
        merged_text, removed = strip_injection_candidates(merged_text)
        print(f"  [security] removed {removed} line(s)")
        trace.log_injection_stripped(len(injection_matches))

    # Store in research cache for future autoresearch experiments on the same task
    if _research_cache_enabled:
        try:
            put_research(task, task_type, merged_text,
                         search_rounds=len(queries_used),
                         novelty_scores=novelty_scores)
        except Exception as _e:
            print(f"  [rcache] store failed: {_e}")

    return merged_text


_SYNTH_CONTEXT_MAX_CHARS = int(os.environ.get("HARNESS_SYNTH_CONTEXT_MAX", 24000))


def synthesize(task: str, research_context: str, vision_context: str = "", file_context: str = "", code_context: str = "", memory_context: str = "", skill_context: str = "", producer_model: str = MODEL, trace=None) -> str:
    """Ask the model to synthesize research (and optional contexts) into a markdown document."""
    # Hard cap on all input contexts to avoid exceeding model context window (~8192 tokens).
    if len(research_context) > _SYNTH_CONTEXT_MAX_CHARS:
        research_context = research_context[:_SYNTH_CONTEXT_MAX_CHARS] + "\n[research context truncated]"
    if len(file_context) > _SYNTH_CONTEXT_MAX_CHARS:
        file_context = file_context[:_SYNTH_CONTEXT_MAX_CHARS] + "\n[file context truncated]"

    vision_block = f"\nImage analysis:\n{vision_context}\n" if vision_context else ""
    file_block = f"\nFile contents:\n{file_context}\n" if file_context else ""
    code_block = f"\nCode execution results:\n{code_context}\n" if code_context else ""
    memory_block = f"\n{memory_context}\n" if memory_context else ""
    skill_block  = f"\nAdditional requirements:\n{skill_context}\n" if skill_context else ""
    prompt = (
        f"Task: {task}\n\n"
        f"Research findings:\n{research_context}\n"
        f"{vision_block}{file_block}{code_block}{memory_block}{skill_block}\n"
        f"{_synth_instruction(task)}"
    )
    response = ollama.chat(
        model=producer_model,
        messages=[{"role": "user", "content": prompt}],
        options=_synth_options(producer_model),
    )
    if trace is not None:
        _thinking = getattr(response.message, "thinking", "") or ""
        trace.log_usage(response, stage="synth")
        trace.log_synth_cot(_thinking)
        trace.log_llm_turn("synth", prompt, response["message"].get("content", ""), _thinking)
    return response["message"].get("content", "")


def research(task: str, trace: RunTrace) -> str:
    print("\n[turn 1] researching...\n")
    context = gather_research(task, trace)
    print("\n  [synth] synthesizing from merged results...")
    return synthesize(task, context)


def extract_count_constraint(task: str) -> int | None:
    """Return the numeric count constraint from a task string, e.g. 'top 5' -> 5."""
    match = re.search(
        r'\btop\s+(\d+)\b|\b(\d+)\s+most\b|\b(\d+)\s+(?:best|key|common|main)\b',
        task,
        re.IGNORECASE,
    )
    if match:
        return int(next(g for g in match.groups() if g is not None))
    return None


def clean_synthesis_output(content: str) -> str:
    """
    Strip artefacts that models sometimes wrap around markdown output:
      - Any preamble before the first H1 heading (bash setup blocks, ```markdown fences, etc.)
      - Trailing ```  that closes an outer fence, plus any verification/commentary after it
      - Standalone trailing Verification sections and file-write epilogues
      - Leading and trailing blank lines
    """
    content = content.strip()

    # Anchor to the first H1 — discard everything before it (preamble, fences, bash blocks)
    h1_match = re.search(r'(?:^|\n)(# .+)', content)
    if h1_match:
        content = content[h1_match.start(1):]

    # Strip a trailing closing ``` fence + any epilogue that follows it
    # Only if what follows the fence looks like a verification block, not real content
    outer_close = re.search(r'\n```\s*\n(.+)$', content, re.DOTALL)
    if outer_close and re.search(
        r'Verification|was created|has been|cat ~|display the contents',
        outer_close.group(1), re.IGNORECASE
    ):
        content = content[:outer_close.start()]

    # Strip trailing verification / file-write commentary
    epilogue_re = re.compile(
        r'\n+(?:#{1,4}\s*)?(?:Verification|Verify)[:\s].*$'
        r'|\n+The (?:markdown )?file .{0,120} (?:was created|has been).*$'
        r'|\n+This command will (?:display|show|confirm).*$'
        # Trailing --- divider followed by meta-commentary about saving / file paths
        r'|\n+---\s*\n+(?:This (?:synthesized|guide|document|markdown)|Ensure you have|Save this|Note:|The above).{0,400}$',
        re.DOTALL | re.IGNORECASE,
    )
    content = epilogue_re.sub('', content)

    # Close any unclosed code fences (odd number of ``` markers = fence left open)
    fence_count = len(re.findall(r'^```', content, re.MULTILINE))
    if fence_count % 2 != 0:
        content = content.rstrip() + '\n```'

    return content.strip()


_STRUCTURAL_HEADERS = {
    "introduction", "conclusion", "summary", "overview",
    "background", "references", "appendix",
}

def _is_structural_header(text: str) -> bool:
    return re.sub(r'^[\d.\s]+', '', text).strip().lower() in _STRUCTURAL_HEADERS


def count_output_items(content: str) -> int:
    """Count H2-level content sections in markdown, ignoring structural headers."""
    headers = re.findall(r'^##\s+(.+)', content, re.MULTILINE)
    return sum(1 for h in headers if not _is_structural_header(h))


def trim_to_count(content: str, expected: int) -> str | None:
    """
    Trim over-produced sections to exactly `expected` H2 content sections.

    Returns trimmed content if the model over-counted (fast, no LLM call).
    Returns None if the model under-counted — caller must fall back to LLM retry.

    Shares the same structural-header exclusion logic as count_output_items so
    the count before and after trim is always consistent.
    """
    matches = list(re.finditer(r'^##\s+(.+)', content, re.MULTILINE))
    content_matches = [m for m in matches if not _is_structural_header(m.group(1))]

    n = len(content_matches)
    if n < expected:
        return None          # under-count — can't fix without LLM
    if n == expected:
        return content       # exact — nothing to do

    # Cut at the start of the (expected+1)th content section.
    # Any structural headers that come after it (e.g. a trailing References) are
    # also dropped — they belong to the section that's being removed.
    cut_at = content_matches[expected].start()
    return content[:cut_at].rstrip()


def synthesize_with_count(task: str, research_context: str, expected_count: int, vision_context: str = "", file_context: str = "", code_context: str = "", memory_context: str = "", skill_context: str = "", producer_model: str = MODEL, trace=None) -> str:
    """Re-synthesize with an explicit count constraint injected into the prompt."""
    vision_block = f"\nImage analysis:\n{vision_context}\n" if vision_context else ""
    file_block = f"\nFile contents:\n{file_context}\n" if file_context else ""
    code_block = f"\nCode execution results:\n{code_context}\n" if code_context else ""
    memory_block = f"\n{memory_context}\n" if memory_context else ""
    skill_block  = f"\nAdditional requirements:\n{skill_context}\n" if skill_context else ""
    prompt = (
        f"Task: {task}\n\n"
        f"Research findings:\n{research_context}\n"
        f"{vision_block}{file_block}{code_block}{memory_block}{skill_block}\n"
        f"IMPORTANT: You must produce EXACTLY {expected_count} numbered sections "
        f"(## 1. ... through ## {expected_count}. ...) — no more, no fewer. "
        f"{_synth_instruction(task)}"
    )
    response = ollama.chat(
        model=producer_model,
        messages=[{"role": "user", "content": prompt}],
        options=_synth_options(producer_model),
    )
    if trace is not None:
        trace.log_usage(response, stage="synth_count")
        trace.log_synth_cot(getattr(response.message, "thinking", "") or "")
    return response["message"]["content"].strip()


def extract_path(task: str) -> str | None:
    """Extract the OUTPUT file path from a task string.

    Prefers paths that follow "save to", "save ... to", or "output to" phrasing
    so that read-path references in the task don't get mistaken for the output.
    Falls back to the last .md/.html path in the task if no save-phrase is found.
    """
    _PATH_RE = r"(~[\w/\\.\-]+\.(?:md|html)|[A-Za-z]:[\w/\\.\-]+\.(?:md|html)|/[\w/.\-]+\.(?:md|html)|[\w./\\\-]+\.(?:md|html))"
    # Priority 1: explicit save/write/output directive
    save_match = re.search(
        r"(?:save(?:\s+\S+){0,5}?\s+to|write\s+to|output\s+to)\s+" + _PATH_RE,
        task, re.IGNORECASE,
    )
    if save_match:
        return save_match.group(1)
    # Priority 2: last .md/.html path in the task (output paths tend to appear last)
    all_paths = re.findall(_PATH_RE, task)
    return all_paths[-1] if all_paths else None


def write_output(content: str, path: str, trace: RunTrace):
    print("\n[turn 2] writing file...\n")

    # Validate output path against sandbox before writing
    ok, reason = check_output_path(path)
    if not ok:
        print(f"[security] write blocked: {reason}")
        print("[error] output path is outside allowed directories — aborting write")
        trace.finish("ERROR")
        sys.exit(1)

    expanded = os.path.expanduser(path)
    dir_path = os.path.dirname(expanded)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    with open(expanded, "w", encoding="utf-8") as f:
        f.write(content)

    trace.log_write(path, content)

    if os.path.exists(expanded):
        size = os.path.getsize(expanded)
        lines = content.count("\n") + 1
        print(f"[eval] PASS — {expanded}")
        print(f"       {lines} lines, {size} bytes\n")
        print("--- preview (first 20 lines) ---")
        print("\n".join(content.splitlines()[:20]))
        print("--------------------------------")
    else:
        print(f"[eval] FAIL — {expanded} not found")


def _estimate_tac_hours(task: str, content: str, model: str) -> float | None:
    """
    Ask the LLM to estimate how long a skilled human researcher would take
    to complete the same task manually. Returns decimal hours or None on error.
    """
    prompt = (
        f"Task: {task}\n\n"
        f"Output produced ({len(content)} chars, first 600 shown):\n"
        f"{content[:600]}\n\n"
        "Estimate how long a skilled human researcher would take to complete this task "
        "manually: searching the web, reading sources, and writing an output of similar "
        "depth and quality. Break it into search, read, and write time.\n\n"
        "Reply with JSON only — no prose:\n"
        '{"hours": <decimal>, "search_h": <decimal>, "read_h": <decimal>, "write_h": <decimal>, "reasoning": "<one sentence>"}'
    )
    try:
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 128},
        )
        import json as _json_tac
        raw = resp["message"].get("content", "").strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        data = _json_tac.loads(raw)
        hours = float(data["hours"])
        print(f"  [tac] estimated human time: {hours:.2f}h  "
              f"(search={data.get('search_h',0):.2f}h  "
              f"read={data.get('read_h',0):.2f}h  "
              f"write={data.get('write_h',0):.2f}h)  — {data.get('reasoning','')}")
        return hours
    except Exception as e:
        print(f"  [tac] estimation failed (non-fatal): {e}")
        return None


def _store_memory(memory: MemoryStore, task: str, task_type: str, trace_data: dict, content: str, wiggum_issues: list[str] | None = None):
    """Compress a completed run and write it to the memory store."""
    print("\n  [memory] compressing run...")
    try:
        obs = memory.compress_and_store(
            task=task,
            task_type=task_type,
            tool_calls=trace_data.get("tool_calls", []),
            output_content=content,
            output_lines=trace_data.get("output_lines", 0),
            output_bytes=trace_data.get("output_bytes", 0),
            output_path=trace_data.get("output_path", ""),
            wiggum_scores=trace_data.get("wiggum_scores", []),
            final=trace_data.get("final", "PASS"),
            wiggum_issues=wiggum_issues or [],
        )
        print(f"  [memory] stored: {obs['title']!r}")
    except Exception as e:
        print(f"  [memory] compression failed (non-fatal): {e}")


_LIT_REVIEW_NL_RE = re.compile(
    r'\b(?:literature\s+review|lit\s+review|systematic\s+review'
    r'|perform\s+(?:a\s+)?(?:literature|lit)\s+review'
    r'|(?:fetch|gather|collect)\s+(?:up\s+to\s+\d+\s+)?(?:relevant\s+)?papers'
    r'|review\s+(?:the\s+)?(?:academic\s+)?literature'
    r'|survey\s+(?:the\s+)?(?:recent\s+)?(?:academic\s+)?literature)\b',
    re.IGNORECASE,
)


def run(task: str, use_wiggum: bool = True, producer_model: str = MODEL, evaluator_model: str = None):
    global _KEEP_ALIVE
    from harness.wiggum import EVALUATOR_MODEL, ANNOTATE_EVALUATOR_MODEL

    # Strip box-drawing Unicode (U+2500–U+257F) introduced by pasting Rich panel output,
    # then collapse runs of whitespace so downstream parsing sees clean text.
    task = re.sub(r'[─-╿]', ' ', task)
    task = re.sub(r'\s+', ' ', task).strip()

    # Normalize natural-language lit-review requests before skill parsing
    if not re.match(r'\s*/lit-review\b', task, re.IGNORECASE) and _LIT_REVIEW_NL_RE.search(task):
        task = "/lit-review " + task
        print("[auto] lit-review intent detected — routing to /lit-review")

    _eval_model    = evaluator_model or EVALUATOR_MODEL
    _ann_eval_model = evaluator_model or ANNOTATE_EVALUATOR_MODEL
    trace = RunTrace(
        task=task,
        producer_model=producer_model,
        evaluator_model=_eval_model,
        session_id=os.environ.get("HARNESS_SESSION_ID", ""),
        project_id=os.environ.get("HARNESS_PROJECT_ID", ""),
    )
    os.environ["HARNESS_RUN_ID"] = trace.run_id
    memory = MemoryStore()

    # Load plugins — must happen before parse_skills() so plugin commands are in REGISTRY
    try:
        from harness import plugin_loader as _pl
        _pl.load_all()
    except Exception as _pl_err:
        print(f"[warn] plugin_loader: {_pl_err}")
        _pl = None  # type: ignore[assignment]

    try:
        # Skill parsing — extract /skill tokens before anything else touches the task
        task, explicit_skills = parse_skills(task)

        # Auto-detect playwright intent when no explicit /playwright prefix was given.
        # Triggers on navigation verbs + a domain URL so general tasks don't false-positive.
        if "playwright" not in explicit_skills:
            import re as _re_pw
            _PW_PATTERN = _re_pw.compile(
                r'\b(?:go\s+to|navigate\s+to|visit|open)\s+'
                r'[a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}',
                _re_pw.IGNORECASE,
            )
            if _PW_PATTERN.search(task):
                explicit_skills = list(explicit_skills) + ["playwright"]
                print("  [auto] playwright intent detected — routing to /playwright")

# Set dynamic keep_alive unless overridden by OLLAMA_KEEP_ALIVE env var
        if _KEEP_ALIVE_OVERRIDE is None:
            _KEEP_ALIVE = _estimate_keep_alive(
                task_type="",             # task_type not known yet; refined below after planning
                explicit_skills=set(explicit_skills),
                use_wiggum=use_wiggum,
            )
            print(f"[agent] keep_alive={_KEEP_ALIVE}s (dynamic)")
        mode = "+".join(explicit_skills) if explicit_skills else "research"
        print(f"[agent] model={producer_model}  mode={mode}")

        # Standalone skills that produce their own output don't require a .md path
        _path_optional = {"email", "github", "review", "lit-review", "recall", "queue", "sync-wiki", "orientation", "introspect", "playwright", "sitemap", "crawl", "transcribe", "re-orient", "suggest", "debug", "troubleshoot", "design", "build-page", "site", "deck"}
        # Add plugin commands that declare path_optional=true
        if _pl:
            for _pk, _pc in _pl.get_commands().items():
                if _pc["definition"].get("path_optional", False):
                    _path_optional.add(_pk)
        path = extract_path(task)
        if not path and not (set(explicit_skills) & _path_optional):
            from datetime import datetime as _dt
            _slug = re.sub(r"[^\w]+", "-", task.strip().lower())[:40].strip("-")
            _ts   = _dt.now().strftime("%Y%m%dT%H%M%S")
            _out  = _ROOT / "data" / "output"
            _out.mkdir(parents=True, exist_ok=True)
            path  = str(_out / f"{_slug}-{_ts}.md")
            print(f"[agent] output -> {path}")

        # Vision preprocessing — extract context from any images referenced in the task
        vision_context = ""
        image_paths = detect_image_paths(task)
        if image_paths:
            print(f"\n[vision] {len(image_paths)} image(s) detected — extracting context...")
            trace.log_vision(image_paths)
            for img_path in image_paths:
                print(f"  [vision] processing {os.path.basename(img_path)}...")
                desc = extract_image_context(img_path, task)
                vision_context += f"\n--- {os.path.basename(img_path)} ---\n{desc}\n"
            print(f"  [vision] extracted {len(vision_context)} chars of image context")

        # read_file — inject content of any text files referenced in the task
        file_context = ""
        text_files = detect_text_files(task, exclude_path=path)
        if text_files:
            print(f"\n[read_file] {len(text_files)} file(s) detected — reading...")
            trace.log_files_read(text_files)
            file_context = read_file_context(text_files, task=task)
            print(f"  [read_file] injecting {len(file_context)} chars of file context")

        # URL fetch — inject content of any http(s):// URLs referenced in the task
        # Skills that drive the browser themselves — don't pre-fetch the target URL as context
        _url_fetch_skip = {"playwright", "sitemap", "crawl", "design", "build-page", "site", "deck"}
        task_urls = detect_task_urls(task) if not (set(explicit_skills) & _url_fetch_skip) else []
        has_url_content = False
        if task_urls:
            print(f"\n[fetch_url] {len(task_urls)} URL(s) in task — fetching...")
            url_context = fetch_task_url_context(task_urls)
            if url_context:
                file_context = (file_context + "\n\n" + url_context).strip()
                has_url_content = True
                print(f"  [fetch_url] injecting {len(url_context)} chars of URL content")

        # ---------------------------------------------------------------------------
        # Standalone skill dispatch
        # Each handler closes over local variables (trace, task, path, etc.).
        # Must be defined after file/URL context is assembled.
        # Add new standalone skills here — one function, one entry in _STANDALONE.
        # ---------------------------------------------------------------------------

        def _handle_annotate():
            print("\n[skill:annotate] standalone mode — annotating paper abstract...")
            trace.data["task_type"] = "annotate"
            if not file_context.strip():
                print("[error] /annotate requires a paper URL or local file path in the task")
                trace.finish("ERROR")
                sys.exit(1)
            with trace.span("synthesize", model=producer_model):
                content = run_annotate_standalone(file_context, producer_model)
            content = content.strip()
            if not content:
                print("[error] annotation model returned empty output")
                trace.finish("ERROR")
                return
            print("\n" + content + "\n")
            write_output(content, path, trace)
            if "wiggum" in explicit_skills:
                from harness.wiggum import loop_annotate
                wiggum_result = loop_annotate(
                    task=task,
                    output_path=path,
                    paper_context=file_context,
                    producer_model=producer_model,
                    evaluator_model=_ann_eval_model,
                    parent_trace=trace,
                )
                trace.log_wiggum(wiggum_result)
                trace.finish(wiggum_result.get("final", "FAIL"))
            else:
                trace.finish("PASS")
            _store_memory(memory, task, "annotate", trace.data, content)

        def _handle_email():
            from harness.skills.email_skill import run_email_standalone, generate_single_email

            print("\n[skill:email] parsing task...")
            raw = task.strip()

            _SOURCE_EXTS = {".pdf", ".txt", ".md", ".docx", ".html", ".pptx", ".csv"}
            _out_dir = "email_drafts/"

            # --- CSV batch mode ---
            csv_token = next((t for t in raw.split() if t.endswith(".csv")), "")
            if csv_token:
                tokens = raw.split()
                goal = " ".join(t for t in tokens if t != csv_token).strip() or raw
                print(f"  [email] batch mode — csv={csv_token}")
                with trace.span("email_drafts", model=producer_model):
                    results = run_email_standalone(
                        csv_path=csv_token,
                        goal=goal,
                        output_dir=_out_dir,
                        producer_model=producer_model,
                        sender_name=os.environ.get("SENDER_NAME", ""),
                        sender_email=os.environ.get("SENDER_EMAIL", ""),
                    )
                tok_in  = results[0].get("_tokens_in",  0) if results else 0
                tok_out = results[0].get("_tokens_out", 0) if results else 0
                trace.data.update({"task_type": "email", "email_drafts": len(results),
                                   "email_output_dir": _out_dir,
                                   "input_tokens": tok_in, "output_tokens": tok_out})
                trace.finish("PASS")
                return

            # --- Single contact mode ---
            # Email address identified by @ token. If absent, agent will search online.
            tokens = raw.split()
            email_token = next((t for t in tokens if "@" in t and "." in t.split("@")[-1]), "")

            if email_token:
                # Form 1: email address provided
                email_idx   = tokens.index(email_token)
                name        = " ".join(tokens[:email_idx]).strip()
                rest        = tokens[email_idx + 1:]
                source      = ""
                goal_tokens = rest
                if rest:
                    first = rest[0].strip('"')
                    if first.startswith("http") or any(first.endswith(ext) for ext in _SOURCE_EXTS):
                        source = first
                        goal_tokens = rest[1:]
                goal = " ".join(goal_tokens).strip().strip('"')
                if not goal:
                    goal = f"reach out to {name}"
                print(f"  [email] single mode (email known) — to={email_token}  goal={goal[:60]}")
            else:
                # Form 2: no email — parse name + context, search online for address
                import re as _re2
                # Name = leading words up to first quoted string or recognisable break
                # Heuristic: first quoted segment is context, rest is goal
                quoted = _re2.findall(r'"([^"]+)"', raw)
                # Strip all quoted segments to isolate name + goal
                stripped = _re2.sub(r'"[^"]+"', "", raw).split()
                # Name is the leading capitalised words (stop at lowercase verb words)
                name_parts = []
                for tok in stripped:
                    if tok[0].isupper() or (name_parts and tok.lower() in ("de","van","von","le","la")):
                        name_parts.append(tok)
                    else:
                        break
                name        = " ".join(name_parts).strip() or stripped[0] if stripped else "Unknown"
                context     = " ".join(quoted)          # from quoted strings in task
                goal_words  = [t for t in stripped if t not in name_parts]
                goal        = " ".join(goal_words).strip() or f"reach out to {name}"

                print(f"  [email] single mode (find email) — name={name}  context={context[:60]}")
                # Web search for email address
                _query   = f'"{name}" email contact {context[:60]}'
                _results = web_search_raw(_query)
                _combined = " ".join(r.get("body", "") for r in (_results or []))
                # Extract first email-looking string from results
                _found = _re2.findall(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", _combined)
                email_token = _found[0] if _found else ""
                if email_token:
                    print(f"  [email] found address via web search: {email_token}")
                else:
                    print("  [email] no email found online — draft will use placeholder")
                # Use search results excerpt as source context
                source = _combined[:1200] if _combined else context

            with trace.span("email_single", model=producer_model):
                result = generate_single_email(
                    name=name,
                    to_email=email_token,
                    source=source,
                    goal=goal,
                    output_dir=_out_dir,
                    producer_model=producer_model,
                    sender_name=os.environ.get("SENDER_NAME", ""),
                    sender_email=os.environ.get("SENDER_EMAIL", ""),
                    sender_company=os.environ.get("SENDER_COMPANY", ""),
                )
            if result:
                trace.data.update({"task_type": "email", "email_drafts": 1,
                                   "email_output_dir": _out_dir,
                                   "input_tokens":  result.get("_tokens_in",  0),
                                   "output_tokens": result.get("_tokens_out", 0)})
                trace.finish("PASS")
            else:
                trace.finish("ERROR")

        def _handle_github():
            print("\n[skill:github] standalone mode...")
            from harness.skills.github_skill import run_github_standalone
            result, tok_in, tok_out = run_github_standalone(task, model=producer_model)
            if path:
                write_output(result, path, trace)
            trace.data["task_type"]     = "github"
            trace.data["input_tokens"]  = tok_in
            trace.data["output_tokens"] = tok_out
            trace.finish("PASS")

        def _handle_review():
            print("\n[skill:review] standalone mode — reviewing diff...")
            from harness.skills.review_skill import run_review_standalone
            result = run_review_standalone(task, model=producer_model)
            if path:
                write_output(result["text"], path, trace)
            trace.data["task_type"]        = "review"
            trace.data["input_tokens"]     = result["tokens_in"]
            trace.data["output_tokens"]    = result["tokens_out"]
            trace.data["review_scope"]     = result["scope"]
            trace.data["review_diff_chars"] = result["diff_chars"]
            trace.data["review_warnings"]  = result["warnings"]
            trace.data["review_warnings_count"] = result["warnings_count"]
            trace.data["review_summary"]   = result["summary"]
            if result["thinking"]:
                trace.data["review_thinking"] = result["thinking"]
            trace.finish("PASS")

        def _handle_lit_review():
            from harness.skills.lit_review_skill import run_lit_review
            import re as _re
            # Parse flags from task string
            no_fetch   = "--no-fetch"   in task
            no_curate  = "--no-curate"  in task
            no_wiggum  = "--no-wiggum"  in task
            no_s2      = "--no-s2"      in task
            after_m    = _re.search(r"--after\s+(\S+)",        task)
            before_m   = _re.search(r"--before\s+(\S+)",       task)
            csv_m      = _re.search(r"--csv\s+(\S+)",          task)
            max_f_m    = _re.search(r"--max-fetch\s+(\d+)",    task)
            max_a_m    = _re.search(r"--max-annotate\s+(\d+)", task)
            tmpl_m     = _re.search(r"--template\s+(\S+)",     task)
            after      = after_m.group(1)  if after_m  else None
            before     = before_m.group(1) if before_m else None
            csv_path   = Path(csv_m.group(1)) if csv_m else None
            max_fetch  = int(max_f_m.group(1)) if max_f_m else 100
            max_ann    = int(max_a_m.group(1)) if max_a_m else 20
            template   = tmpl_m.group(1) if tmpl_m else "survey"
            # Natural language overrides for max_fetch / max_annotate when no CLI flags given
            if not max_f_m:
                _nl_f = _re.search(r'\bfetch\s+(?:up\s+to\s+)?(\d+)\b', task, _re.IGNORECASE)
                if not _nl_f:
                    _nl_f = _re.search(r'\b(?:up\s+to|retrieve|collect)\s+(\d+)\s+(?:relevant\s+)?papers\b', task, _re.IGNORECASE)
                if _nl_f:
                    max_fetch = int(_nl_f.group(1))
            if not max_a_m:
                _nl_a = _re.search(r'\b(?:up\s+to\s+)?(\d+)\s+(?:especially\s+)?(?:important\s+)?(?:key\s+)?papers\b.*\bannot', task, _re.IGNORECASE)
                if not _nl_a:
                    _nl_a = _re.search(r'\bannot\w*\s+(?:for\s+)?(?:up\s+to\s+)?(\d+)\b', task, _re.IGNORECASE)
                if _nl_a:
                    max_ann = int(_nl_a.group(1))
            # Strip known flags and save instructions to get the research query
            query = _re.sub(
                r"(/lit-review|--no-fetch|--no-curate|--no-wiggum|--no-s2"
                r"|--after\s+\S+|--before\s+\S+|--csv\s+\S+"
                r"|--max-fetch\s+\d+|--max-annotate\s+\d+"
                r"|--template\s+\S+"
                r"|[Ss]ave\s+(?:(?:\w+\s+){0,10})?(?:as|to|at)\s+\S+"
                r"|\S+\.(?:md|html))",
                "", task, flags=_re.IGNORECASE,
            ).strip()
            from harness.config import LIT_REVIEWS_DIR
            if path:
                p = Path(path).expanduser()
                out = p if p.is_absolute() else LIT_REVIEWS_DIR / p.name
            else:
                _slug = _re.sub(r"[^\w]+", "_", query.lower() if query else "review")[:50].strip("_")
                out = LIT_REVIEWS_DIR / f"{_slug}.md"
            trace.data["task_type"] = "lit-review"
            result = run_lit_review(
                query=query,
                out_path=out,
                max_fetch=max_fetch,
                max_annotate=max_ann,
                after=after,
                before=before,
                csv_path=csv_path if (no_fetch or csv_path) else None,
                no_curate=no_curate,
                no_wiggum=no_wiggum,
                no_s2=no_s2,
                template=template,
                producer_model=producer_model,
                evaluator_model=_ann_eval_model,
                _trace=trace,
            )
            out_path_str = result.get("out_path", "")
            out_p = Path(out_path_str) if out_path_str else None
            trace.data["output_path"]         = out_path_str
            trace.data["output_bytes"]        = out_p.stat().st_size if out_p and out_p.exists() else 0
            trace.data["lit_review_papers"]   = result.get("papers", 0)
            trace.data["lit_review_clusters"] = result.get("clusters", 0)
            trace.data["tool_calls"]          = [
                {"name": "web_search", "query": t}
                for t in result.get("paper_titles", [])
            ]
            if result.get("error") or not out_path_str:
                err = result.get("error", "unknown")
                papers_found = result.get("papers", 0)
                trace.data["final_content"] = (
                    f"# Lit-review aborted\n\n"
                    f"**Error:** {err}\n"
                    f"**Papers found:** {papers_found}\n"
                    f"**Query:** {query}\n\n"
                    f"arXiv returned no results. Try a shorter, keyword-style query:\n"
                    f"e.g. `Gemma language model evaluation` instead of a full sentence."
                )
                trace.finish("ERROR")
            else:
                trace.finish("PASS")
            if out_p and out_p.exists():
                _store_memory(memory, task, "lit-review", trace.data, out_p.read_text(encoding="utf-8"))

        def _handle_recall():
            import re as _re
            import json as _json

            # Parse: /recall <query> [--n N] [--facts] [--scores]
            raw = task.strip()
            n_match = _re.search(r"--n\s+(\d+)", raw)
            n = int(n_match.group(1)) if n_match else 10
            show_facts  = "--facts"  in raw
            show_scores = "--scores" in raw
            query = _re.sub(r"--n\s+\d+|--facts|--scores", "", raw).strip()

            if not query:
                print("[recall] usage: /recall <query> [--n N] [--facts] [--scores]")
                trace.finish("ERROR")
                return

            print(f"\n[recall] searching memory for: {query!r}  (top {n})")
            hits = memory.search(query, n=n)

            if not hits:
                print("[recall] no matching observations found.")
                trace.finish("PASS")
                return

            for i, row in enumerate(hits, 1):
                score_str = f"  score={row['final_score']:.1f}" if show_scores and row["final_score"] else ""
                date = (row["timestamp"] or "")[:10]
                print(f"\n{'-'*60}")
                print(f"[{i}] {row['title']}")
                print(f"     {date}{score_str}")
                print(f"     {row['narrative']}")
                if show_facts and row["facts"]:
                    try:
                        facts = _json.loads(row["facts"]) if isinstance(row["facts"], str) else row["facts"]
                        for f in (facts or []):
                            print(f"     • {f}")
                    except Exception:
                        print(f"     {row['facts']}")

            print(f"\n{'-'*60}")
            print(f"[recall] {len(hits)} result(s) for {query!r}")
            trace.finish("PASS")

        def _handle_introspect():
            print("\n[skill:introspect] standalone mode — answering from memory + context files...")
            trace.data["task_type"] = "introspect"
            from harness.skills import REGISTRY, load_context_files

            # Build live capabilities document from the skill registry and current config
            _hook_labels = {
                "standalone":     "Standalone (slash command)",
                "pre_research":   "Pre-research hook",
                "pre_synthesis":  "Pre-synthesis hook",
                "post_synthesis": "Post-synthesis hook",
                "post_wiggum":    "Post-eval hook",
                "modifier":       "Modifier flag",
            }
            _sections: dict[str, list[str]] = {}
            for name, entry in REGISTRY.items():
                label = _hook_labels.get(entry.get("hook", ""), entry.get("hook", ""))
                _sections.setdefault(label, []).append(f"- **/{name}** — {entry['description']}")
            caps_lines = [
                "# Agent Capabilities\n",
                f"## Model configuration\n- Producer: {producer_model}\n- Evaluator: {_ann_eval_model}\n",
            ]
            for label, items in _sections.items():
                caps_lines.append(f"## {label}\n" + "\n".join(items))
            capabilities_doc = "\n\n".join(caps_lines)
            print(f"  [introspect] built live capabilities doc ({len(capabilities_doc)} chars, {len(REGISTRY)} skills)")

            # Wiki/context files supplement the live doc (human-authored notes, examples, etc.)
            ctx_files = load_context_files()
            if ctx_files and len(ctx_files.strip()) > 4:
                print(f"  [introspect] loaded {len(ctx_files)} chars from wiki/context")
            else:
                ctx_files = ""

            # Use a fixed introspection query so memory search returns agent-knowledge
            # observations rather than research papers that happen to match the task string.
            mem_ctx = memory.get_context("agent capabilities skills configuration models")
            if mem_ctx:
                print(f"  [introspect] {mem_ctx.count('**[')} memory observation(s) retrieved")
            else:
                print("  [introspect] no relevant memory observations")

            combined = "\n\n".join(filter(None, [capabilities_doc, ctx_files, mem_ctx]))
            # Custom prompt — SYNTH_INSTRUCTION is for research docs and causes hallucination here.
            # num_predict=2000 is enough for any self-description and keeps vLLM context headroom.
            prompt = (
                f"Task: {task}\n\n"
                f"Agent context (use ONLY this — do not invent capabilities not listed):\n\n"
                f"{combined}\n\n"
                "Answer the task accurately and concisely using only the context above. "
                "Format as clear markdown starting with a # heading. "
                "Do not fabricate skills, models, or capabilities not described in the context."
            )
            with trace.span("introspect", model=producer_model):
                response = ollama.chat(
                    model=producer_model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.1, "num_predict": 2000, "num_ctx": 16384, "repeat_penalty": 1.1},
                )
            trace.log_usage(response, stage="introspect")
            trace.log_llm_turn("introspect", prompt, response["message"].get("content", "").strip())
            content = clean_synthesis_output(response["message"].get("content", "").strip())
            if not content:
                print("[error] introspect returned empty output")
                trace.finish("ERROR")
                return
            print("\n" + content + "\n")
            _out_path = path
            if not _out_path:
                from datetime import datetime as _dt
                _ts  = _dt.now().strftime("%Y%m%dT%H%M%S")
                _out = _ROOT / "data" / "output"
                _out.mkdir(parents=True, exist_ok=True)
                _out_path = str(_out / f"introspect-{_ts}.md")
            write_output(content, _out_path, trace)
            trace.finish("PASS")
            _store_memory(memory, task, "introspect", trace.data, content)

        def _handle_orientation():
            print("\n[skill:orientation] building situational awareness document...")
            trace.data["task_type"] = "orientation"
            from harness.skills.orientation_skill import build_orientation
            mem_ctx = memory.get_context(task) or ""
            doc = build_orientation(
                producer_model=producer_model,
                memory_ctx=mem_ctx,
                compress_model=COMPRESS_MODEL,
            )
            # Write raw doc to temp file so server.py can pick it up for cache
            try:
                import tempfile
                _raw_path = os.path.join(tempfile.gettempdir(), "harness_orientation_raw.md")
                with open(_raw_path, "w", encoding="utf-8") as _f:
                    _f.write(doc)
            except Exception as _e:
                print(f"  [orientation] raw doc write failed: {_e}")
            # Synthesize a response grounded in the orientation document (best-effort)
            content = ""
            try:
                from harness import inference as _inf
                _synth_model = _inf.get_active_vllm_model() or producer_model
                prompt = (
                    f"Task: {task}\n\n"
                    f"Project orientation:\n\n{doc}\n\n"
                    "Using only the orientation above, respond to the task accurately. "
                    "Format as clear markdown. If the task is just '/orientation' with no "
                    "specific question, produce a concise executive summary of the project state."
                )
                with trace.span("orientation", model=_synth_model):
                    response = ollama.chat(
                        model=_synth_model,
                        messages=[{"role": "user", "content": prompt}],
                        options={"temperature": 0.1, "num_predict": 3000},
                    )
                trace.log_usage(response, stage="orientation")
                trace.log_llm_turn("orientation", prompt, response["message"].get("content", "").strip())
                content = clean_synthesis_output(response["message"].get("content", "").strip())
            except Exception as _syn_err:
                print(f"  [orientation] synthesis skipped ({_syn_err}); using raw doc")
            if not content:
                content = doc
            print("\n" + content[:2000] + ("\n...[truncated]" if len(content) > 2000 else "") + "\n")
            if path:
                write_output(content, path, trace)
            else:
                trace.data["final_content"] = content[:16_000]
                trace.data["output_bytes"]  = len(content.encode())
            trace.finish("PASS")
            _store_memory(memory, task, "orientation", trace.data, content)

        def _handle_playwright():
            print("\n[skill:playwright] launching browser navigation...")
            trace.data["task_type"] = "playwright"
            try:
                from harness.skills.playwright_skill import navigate_and_extract, parse_playwright_task
            except ImportError:
                print("[error] playwright_skill.py not found — pip install playwright && playwright install chromium")
                trace.finish("ERROR")
                return
            try:
                start_url, goal = parse_playwright_task(task)
            except ValueError as _e:
                print(f"[error] {_e}")
                trace.finish("ERROR")
                return

            headed = os.environ.get("PLAYWRIGHT_HEADLESS", "0") != "1"
            print(f"  [playwright] site={start_url}  goal={goal[:80]}  headed={headed}")
            try:
                with trace.span("playwright_navigate", model=COMPRESS_MODEL):
                    page_text, final_url, _screenshots, _nav_history = navigate_and_extract(
                        start_url=start_url,
                        goal=goal,
                        model=COMPRESS_MODEL,
                        headed=headed,
                        keep=os.environ.get("HARNESS_KEEP_BROWSER") == "1",
                        run_id=trace.data.get("run_id", ""),
                    )
            except RuntimeError as _e:
                print(f"[error] playwright navigation failed: {_e}")
                trace.finish("ERROR")
                return

            trace.data["screenshots"]   = _screenshots
            trace.data["browser_history"] = _nav_history
            print(f"  [playwright] extracted {len(page_text)} chars from {final_url}  ({len(_screenshots)} screenshots)")
            if not page_text:
                print("[error] playwright returned empty content")
                trace.finish("ERROR")
                return

            # Synthesize from extracted content
            # Truncate to ~20 000 chars (~5 000 tokens) so synthesis fits in 8 192-token context
            _MAX_SYNTH_CHARS = 20_000
            synth_text = page_text
            if len(page_text) > _MAX_SYNTH_CHARS:
                synth_text = page_text[:_MAX_SYNTH_CHARS] + "\n\n... [content truncated for synthesis]"
                print(f"  [playwright] synthesis input truncated from {len(page_text)} -> {_MAX_SYNTH_CHARS} chars")
            prompt = (
                f"Task: {task}\n\n"
                f"Source URL: {final_url}\n\n"
                f"Extracted page content:\n\n{synth_text}\n\n"
                "Using only the content above, complete the task accurately. "
                "Format as clear markdown."
            )
            with trace.span("playwright_synthesis", model=producer_model):
                response = ollama.chat(
                    model=producer_model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2, "num_predict": 4096},
                )
            trace.log_usage(response, stage="playwright_synthesis")
            content = clean_synthesis_output(response["message"].get("content", "").strip())
            if not content:
                print("[error] synthesis returned empty output")
                trace.finish("ERROR")
                return
            print("\n" + content[:1000] + ("\n...[truncated]" if len(content) > 1000 else "") + "\n")
            if path:
                write_output(content, path, trace)
            else:
                trace.data["final_content"] = content[:16_000]
                trace.data["output_bytes"]  = len(content.encode())
            trace.finish("PASS")
            _store_memory(memory, task, "playwright", trace.data, content)
            try:
                from harness.skill_extractor import extract_browser_skill_and_store as _extract_bskill
                _extract_bskill(task=task, trace_data=trace.data,
                                model=COMPRESS_MODEL, run_id=trace.data.get("run_id", ""))
            except Exception:
                pass

        def _handle_sitemap():
            import re as _re
            print("\n[skill:sitemap] discovering site structure...")
            trace.data["task_type"] = "sitemap"
            raw = _re.sub(r"^/(sitemap|crawl)\s*", "", task.strip(), flags=_re.IGNORECASE).strip()
            # Split off optional goal after the URL
            m = _re.match(
                r"([a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(?:/[^\s]*)?|https?://\S+)\s*(.*)",
                raw, _re.IGNORECASE,
            )
            if not m:
                print("[error] /sitemap requires a URL, e.g.  /sitemap anthropic.com/research")
                trace.finish("ERROR")
                return
            site_url, goal_hint = m.group(1).strip(), m.group(2).strip()
            try:
                from harness.skills.sitemap_skill import discover_pages, rank_by_goal, format_as_markdown
            except ImportError:
                print("[error] sitemap_skill.py not found")
                trace.finish("ERROR")
                return
            pages = discover_pages(site_url, max_pages=80)
            if goal_hint:
                from harness.skills.sitemap_skill import rank_by_goal, _domain
                top, n_matched = rank_by_goal(pages, goal_hint, top_n=20)
                match_note = f"{n_matched} matched" if n_matched else "no direct matches — showing by relevance"
                print(f"\n  [sitemap] top {len(top)} pages for goal: {goal_hint[:60]!r}  ({match_note})")
                for i, p in enumerate(top, 1):
                    print(f"    {i:2d}. {p['url']}" + (f"  [{p['title']}]" if p.get("title") else ""))
                if not n_matched:
                    _goal_lower = goal_hint.lower()
                    _doc_words = {"doc", "guide", "api", "integration", "tutorial", "reference", "quickstart", "sdk"}
                    if any(w in _goal_lower for w in _doc_words):
                        from skills.sitemap_skill import _normalize
                        _dom = _domain(_normalize(site_url))
                        print(f"\n  [hint] no matches on {_dom} — try: oh /sitemap docs.{_dom} {goal_hint}")
            from harness.skills.sitemap_skill import _domain, format_as_markdown
            content = format_as_markdown(pages, _domain(site_url))
            if goal_hint:
                from harness.skills.sitemap_skill import rank_by_goal
                top, n_matched = rank_by_goal(pages, goal_hint, top_n=20)
                section_note = f" ({n_matched} matched)" if n_matched else " (best-effort — no direct matches)"
                content += f"\n\n## Most Relevant for: {goal_hint}{section_note}\n\n"
                content += "\n".join(f"- [{p.get('title') or p['url']}]({p['url']})" for p in top)
            if path:
                write_output(content, path, trace)
            else:
                print("\n" + content[:3000])
                trace.data["final_content"] = content
            trace.finish("PASS")

        def _handle_transcribe():
            import re as _re
            from pathlib import Path as _Path

            print("\n[skill:transcribe] locating audio file...")
            trace.data["task_type"] = "transcribe"

            # Parse: /transcribe <filename or path> [to <output.md>]
            raw = task.strip()
            raw = _re.sub(r"^/transcribe\s*", "", raw, flags=_re.IGNORECASE).strip()

            # Optional explicit output path: "... to path/to/output.md"
            _out_match = _re.search(r"\bto\s+(\S+\.md)\s*$", raw, _re.IGNORECASE)
            out_path = _out_match.group(1) if _out_match else None
            audio_hint = raw[: _out_match.start()].strip() if _out_match else raw
            audio_hint = audio_hint.strip('"\'')

            if not audio_hint:
                print("[error] usage: /transcribe <audio_file> [to <output.md>]")
                trace.finish("ERROR")
                return

            # Locate the file: try as-is, then search common locations
            _search_roots = [
                os.getcwd(),
                os.path.expanduser("~/Desktop"),
                os.path.expanduser("~/Downloads"),
                os.path.expanduser("~/Documents"),
                os.path.expanduser("~/Music"),
                os.path.expanduser("~/Videos"),
            ]
            audio_path = None
            # First: treat as explicit path
            if os.path.isfile(audio_hint):
                audio_path = os.path.abspath(audio_hint)
            else:
                # Walk search roots for matching filename
                _hint_name = _Path(audio_hint).name
                for root in _search_roots:
                    for dirpath, _, files in os.walk(root):
                        for fname in files:
                            if fname.lower() == _hint_name.lower():
                                audio_path = os.path.join(dirpath, fname)
                                break
                        if audio_path:
                            break
                    if audio_path:
                        break

            if not audio_path:
                print(f"[error] audio file not found: {audio_hint!r}")
                print(f"  searched: {', '.join(_search_roots)}")
                trace.finish("ERROR")
                return

            print(f"  [transcribe] found: {audio_path}")

            # Transcribe
            try:
                from harness.skills.youtube_transcribe import _whisper_transcribe, _ensure_ffmpeg
                _ensure_ffmpeg()
                with trace.span("transcribe", model="whisper"):
                    transcript = _whisper_transcribe(audio_path)
            except Exception as _e:
                print(f"[error] transcription failed: {_e}")
                trace.finish("ERROR")
                return

            if not transcript:
                print("[error] whisper returned empty transcript")
                trace.finish("ERROR")
                return

            print(f"  [transcribe] {len(transcript)} chars transcribed")

            # Build output markdown
            stem = _Path(audio_path).stem
            content = f"# Transcript: {stem}\n\n**Source:** `{audio_path}`\n\n---\n\n{transcript}\n"

            # Determine output path
            if not out_path:
                from harness.config import TRANSCRIPTS_DIR
                TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
                safe_stem = _re.sub(r"[^\w\-]", "-", stem).strip("-").lower()
                out_path = str(TRANSCRIPTS_DIR / f"{safe_stem}-transcript.md")

            write_output(content, out_path, trace)
            trace.finish("PASS")
            _store_memory(memory, task, "transcribe", trace.data, content)

        def _handle_reorient():
            import re as _re
            import subprocess as _sp
            import shutil as _sh
            import tempfile as _tmp
            import concurrent.futures as _cf

            print("\n[skill:re-orient] gathering orientation + GitHub state...")
            trace.data["task_type"] = "re-orient"

            # Optional focus question: everything after /re-orient token
            question = _re.sub(r"^/re-orient\s*", "", task, flags=_re.IGNORECASE).strip()
            question = question or "Summarise the current project state, what was recently shipped, and what should be prioritised next."

            # ── 1. Read cached orientation doc ──────────────────────────────
            _ori_path = os.path.join(_tmp.gettempdir(), "harness_orientation_raw.md")
            orientation_doc = ""
            ori_age_min = None
            if os.path.exists(_ori_path):
                import time as _t
                ori_age_min = round((_t.time() - os.path.getmtime(_ori_path)) / 60, 1)
                try:
                    orientation_doc = open(_ori_path, encoding="utf-8").read()
                    print(f"  [re-orient] orientation cache: {len(orientation_doc)} chars ({ori_age_min} min old)")
                except Exception as _e:
                    print(f"  [re-orient] orientation cache read failed: {_e}")
            else:
                print("  [re-orient] orientation cache not found — run /orientation first")

            # ── 2. GitHub + git commands (parallel) ──────────────────────────
            _GH = _sh.which("gh") or "gh"
            _GIT = _sh.which("git") or "git"

            def _run(cmd, label):
                try:
                    r = _sp.run(cmd, capture_output=True, text=True, timeout=15,
                                cwd=os.getcwd())
                    out = r.stdout.strip()
                    if out:
                        print(f"  [re-orient] {label}: {len(out)} chars")
                    return label, out
                except Exception as _e:
                    return label, f"(error: {_e})"

            _cmds = [
                (["git", "log", "--oneline", "-20"], "recent_commits"),
                ([_GH, "pr", "list", "--state", "merged", "--limit", "10",
                  "--json", "number,title,mergedAt,author"], "merged_prs"),
                ([_GH, "pr", "list",
                  "--json", "number,title,author,createdAt,headRefName"], "open_prs"),
                ([_GH, "issue", "list", "--limit", "10",
                  "--json", "number,title,labels,createdAt,state"], "open_issues"),
                ([_GH, "run", "list", "--limit", "5",
                  "--json", "status,conclusion,name,createdAt,headBranch"], "ci_runs"),
            ]

            gh_sections = {}
            with _cf.ThreadPoolExecutor(max_workers=5) as _pool:
                futures = {_pool.submit(_run, cmd, label): label for cmd, label in _cmds}
                for fut in _cf.as_completed(futures):
                    label, out = fut.result()
                    gh_sections[label] = out

            # ── 3. Build context block ────────────────────────────────────────
            _age_note = f"(cached {ori_age_min} min ago)" if ori_age_min is not None else "(cache missing)"
            context_parts = []
            if orientation_doc:
                context_parts.append(f"## Project orientation {_age_note}\n\n{orientation_doc[:6000]}")

            _gh_labels = {
                "recent_commits": "Recent commits (git log)",
                "merged_prs":     "Recently merged PRs",
                "open_prs":       "Open PRs",
                "open_issues":    "Open issues",
                "ci_runs":        "Recent CI runs",
            }
            for key in ["recent_commits", "merged_prs", "open_prs", "open_issues", "ci_runs"]:
                val = gh_sections.get(key, "")
                if val and not val.startswith("(error"):
                    context_parts.append(f"## {_gh_labels[key]}\n\n```\n{val[:1200]}\n```")

            full_context = "\n\n".join(context_parts)
            if not full_context.strip():
                print("[error] no orientation data or GitHub output available")
                trace.finish("ERROR")
                return

            # ── 4. LLM synthesis ─────────────────────────────────────────────
            _prompt = (
                f"You are reviewing the current state of an agentic research engineering project.\n\n"
                f"{full_context}\n\n"
                f"---\n\nQuestion / focus: {question}\n\n"
                "Answer concisely in well-structured markdown. "
                "Draw on all context above — orientation doc, recent commits, PRs, issues, and CI runs. "
                "Be specific: reference commit messages, PR titles, issue numbers where relevant."
            )
            print(f"  [re-orient] synthesizing ({len(_prompt)} char prompt)...")
            with trace.span("reorient_synth", model=producer_model):
                _resp = ollama.chat(
                    model=producer_model,
                    messages=[{"role": "user", "content": _prompt}],
                    options={"temperature": 0.2, "num_predict": 2048},
                )
            trace.log_usage(_resp, stage="reorient_synth")
            content = clean_synthesis_output(
                (_resp.message.content or "").strip()
            )
            if not content:
                print("[error] synthesis returned empty output")
                trace.finish("ERROR")
                return

            print("\n" + content[:1200] + ("\n...[truncated]" if len(content) > 1200 else "") + "\n")

            if path:
                write_output(content, path, trace)
            else:
                trace.data["final_content"] = content[:16_000]
                trace.data["output_bytes"]  = len(content.encode())

            trace.finish("PASS")
            _store_memory(memory, task, "re-orient", trace.data, content)

        def _handle_debug():
            print("\n[skill:debug] diagnosing recent failures...")
            trace.data["task_type"] = "debug"

            import re as _re_d
            import json as _json_d
            from harness.config import ROOT as _ROOT_D, RUNS_FILE as _RUNS_D, TRACES_DIR as _TRACES_D
            _base_d = _ROOT_D / 'harness'

            # ── 1. Parse filter from task string ────────────────────────────
            # /debug [task_type | ERROR | FAIL | run_id | model_name]
            _filter_raw = _re_d.sub(r"^/debug\s*", "", task, flags=_re_d.IGNORECASE).strip()
            _filter = _filter_raw.lower() if _filter_raw else ""

            # ── 2. Load runs and find matching failures ───────────────────────
            _runs_path = _RUNS_D
            all_runs = []
            if _runs_path.exists():
                try:
                    _rf_content = _runs_path.read_text(encoding="utf-8", errors="replace")
                    for _line in _rf_content.splitlines():
                        _line = _line.strip()
                        if _line:
                            try:
                                all_runs.append(_json_d.loads(_line))
                            except Exception:
                                pass
                except Exception:
                    pass

            def _run_matches(r):
                if r.get("final") not in ("ERROR", "FAIL"):
                    return False
                if r.get("task_type") in ("debug", "suggest", "orientation", "re-orient"):
                    return False
                if not _filter:
                    return True
                haystack = " ".join([
                    r.get("task_type") or "",
                    r.get("final") or "",
                    r.get("run_id") or "",
                    r.get("producer_model") or "",
                    r.get("task") or "",
                ]).lower()
                return _filter in haystack

            candidates = [r for r in all_runs if _run_matches(r)]
            if not candidates:
                print(f"  [debug] no ERROR/FAIL runs found matching '{_filter or 'any'}'")
                trace.finish("ERROR")
                return

            # Use last 2 matching runs for pattern detection
            targets = candidates[-2:]
            print(f"  [debug] found {len(candidates)} matching run(s), analysing last {len(targets)}")

            # ── 3. Source file mapping: task_type -> relevant files + anchors ──
            _SOURCE_MAP = {
                "annotate":      [("skills.py",         "run_annotate_standalone")],
                "introspect":    [("agent.py",           "_handle_introspect")],
                "re-orient":     [("agent.py",           "_handle_reorient")],
                "orientation":   [("orientation_skill.py", "def build_orientation")],
                "research":      [("agent.py",           "SYNTH_INSTRUCTION"), ("wiggum.py", "def loop")],
                "best_practices":[("agent.py",           "SYNTH_INSTRUCTION"), ("wiggum.py", "def loop")],
                "enumerated":    [("agent.py",           "SYNTH_INSTRUCTION_COUNT"), ("wiggum.py", "def loop")],
            }

            def _extract_source(fname, anchor, max_chars=1800):
                fpath = _base_d / fname
                if not fpath.exists():
                    return ""
                text = fpath.read_text(encoding="utf-8", errors="replace")
                idx = text.find(anchor)
                if idx == -1:
                    return text[:max_chars]
                start = max(0, idx - 100)
                return text[start:start + max_chars]

            # ── 4. Read trace events for each target run ──────────────────────
            def _read_trace_events(run_id):
                traces_dir = _TRACES_D
                if not traces_dir.exists():
                    return ""
                matches = list(traces_dir.glob(f"{run_id}_*.json"))
                if not matches:
                    return ""
                try:
                    data = _json_d.loads(matches[0].read_text(encoding="utf-8", errors="replace"))
                    events = [
                        e for e in data.get("traceEvents", [])
                        if e.get("ph") == "X"
                    ]
                    lines = []
                    for e in events:
                        dur_ms = round(e.get("dur", 0) / 1000)
                        args = e.get("args", {})
                        err = args.get("error", "")
                        err_str = f"  ERROR: {err}" if err else ""
                        lines.append(f"  {e['name']:35s} {dur_ms:6d}ms{err_str}")
                    return "\n".join(lines)
                except Exception:
                    return ""

            # ── 5. Assemble context blocks ────────────────────────────────────
            ctx_parts = []

            for run in targets:
                tt       = run.get("task_type", "unknown")
                final    = run.get("final", "?")
                model    = run.get("producer_model", "")
                dur      = run.get("run_duration_s", 0)
                run_id   = run.get("run_id", "")
                task_str = (run.get("task") or "")[:120]
                scores   = run.get("wiggum_scores") or []
                eval_log = run.get("wiggum_eval_log") or []

                block = [
                    f"## Run: {run_id}",
                    f"task_type={tt}  final={final}  model={model}  duration={dur}s",
                    f"task: {task_str}",
                ]
                if scores:
                    block.append(f"wiggum_scores: {scores}")
                if eval_log:
                    for entry in eval_log[-2:]:
                        dims  = entry.get("dims", {})
                        issues = entry.get("issues", [])
                        block.append(f"eval round {entry.get('round')}: score={entry.get('score')}  dims={dims}")
                        if issues:
                            block.append("issues:\n" + "\n".join(f"  - {i}" for i in issues[:5]))

                events_str = _read_trace_events(run_id)
                if events_str:
                    block.append(f"trace events:\n{events_str}")

                ctx_parts.append("\n".join(block))

            # Source excerpts
            combined_types = set(r.get("task_type", "") for r in targets)
            seen_files = set()
            source_blocks = []
            for tt in combined_types:
                for fname, anchor in _SOURCE_MAP.get(tt, [("agent.py", "SYNTH_INSTRUCTION")]):
                    key = (fname, anchor)
                    if key in seen_files:
                        continue
                    seen_files.add(key)
                    snippet = _extract_source(fname, anchor)
                    if snippet:
                        source_blocks.append(f"### {fname} (near `{anchor}`)\n```python\n{snippet}\n```")

            if source_blocks:
                ctx_parts.append("## Relevant source\n\n" + "\n\n".join(source_blocks))

            full_ctx = "\n\n".join(ctx_parts)

            # ── 6. Synthesis ──────────────────────────────────────────────────
            _is_code_error = any(r.get("final") == "ERROR" for r in targets)
            fix_guidance = (
                "Show the exact lines to change as a minimal diff or replacement block."
                if _is_code_error else
                "Suggest specific changes to the synthesis instruction, prompt, or harness config. "
                "If the fix is a SYNTH_INSTRUCTION change, show the full replacement string."
            )

            _prompt = (
                "You are debugging a failing agentic research harness. "
                "Analyse the run records and source below, then diagnose the root cause.\n\n"
                f"{full_ctx}\n\n"
                "---\n\n"
                f"{fix_guidance}\n\n"
                "Respond in this exact format:\n\n"
                "**Diagnosis:** <one sentence root cause>\n\n"
                "**Evidence:** <2-3 specific observations from the run data above>\n\n"
                "**Fix:**\n<concrete code change or config change, ready to apply>"
            )

            print(f"  [debug] synthesising ({len(_prompt)} char prompt)...")
            with trace.span("debug_synth", model=producer_model):
                _resp = ollama.chat(
                    model=producer_model,
                    messages=[{"role": "user", "content": _prompt}],
                    options={"temperature": 0.1, "num_predict": 1024},
                )
            trace.log_usage(_resp, stage="debug_synth")
            content = clean_synthesis_output((_resp.message.content or "").strip())

            if not content:
                print("[error] synthesis returned empty output")
                trace.finish("ERROR")
                return

            print("\n" + content + "\n")

            if path:
                write_output(content, path, trace)
            else:
                trace.data["final_content"] = content
                trace.data["output_bytes"]  = len(content.encode())

            trace.finish("PASS")
            _store_memory(memory, task, "debug", trace.data, content)

        def _handle_suggest():
            print("\n[skill:suggest] synthesising next task recommendation...")
            trace.data["task_type"] = "suggest"

            import time as _t
            import tempfile as _tmp_s
            import json as _json_s

            from harness.config import ROOT as _ROOT_S, RUNS_FILE as _RUNS_S
            _base_s = _ROOT_S

            # ── 1. Orientation cache ─────────────────────────────────────────
            _ori_path = os.path.join(_tmp_s.gettempdir(), "harness_orientation_raw.md")
            orientation_doc = ""
            ori_age_min = None
            if os.path.exists(_ori_path):
                ori_age_min = round((_t.time() - os.path.getmtime(_ori_path)) / 60, 1)
                try:
                    orientation_doc = open(_ori_path, encoding="utf-8").read()[:4000]
                except Exception:
                    pass
            if ori_age_min is None:
                print("  [suggest] orientation cache missing — run /orientation first for best results")
            elif ori_age_min > 30:
                print(f"  [suggest] orientation cache is {ori_age_min} min old — consider /re-orient")

            # ── 2. Recent runs ────────────────────────────────────────────────
            runs_lines = []
            _runs_path = _RUNS_S
            if _runs_path.exists():
                try:
                    with open(_runs_path, encoding="utf-8", errors="replace") as _rf:
                        all_r = [l.strip() for l in _rf if l.strip()]
                    for _raw in all_r[-8:]:
                        try:
                            _r = _json_s.loads(_raw)
                            ts       = (_r.get("timestamp") or "")[:16].replace("T", " ")
                            final    = _r.get("final", "?")
                            score    = (_r.get("wiggum_scores") or [None])[-1]
                            score_str = f"  score={score}" if score is not None else ""
                            model    = _r.get("producer_model", "")
                            task_str = (_r.get("task") or "")[:80]
                            runs_lines.append(f"- [{ts}] {final}{score_str}  model={model}  {task_str}")
                        except Exception:
                            pass
                except Exception:
                    pass

            # ── 3. Git log ────────────────────────────────────────────────────
            git_log = ""
            try:
                git_log = subprocess.check_output(
                    ["git", "log", "--oneline", "-12"],
                    cwd=_base_s, stderr=subprocess.DEVNULL, text=True,
                ).strip()
            except Exception:
                pass

            # ── 4. Autoresearch state ─────────────────────────────────────────
            ar_state = ""
            _ar_path = _base_s / "autoresearch.tsv"
            if _ar_path.exists():
                try:
                    lines = _ar_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    header = lines[0] if lines else ""
                    recent = lines[-3:] if len(lines) > 1 else []
                    ar_state = "\n".join([header] + recent)
                except Exception:
                    pass

            # ── 5. Build context ──────────────────────────────────────────────
            ctx_parts = []
            if orientation_doc:
                age_note = f"(cached {ori_age_min} min ago)" if ori_age_min is not None else ""
                ctx_parts.append(f"## Project orientation {age_note}\n\n{orientation_doc}")
            if git_log:
                ctx_parts.append(f"## Recent commits\n\n```\n{git_log}\n```")
            if runs_lines:
                ctx_parts.append("## Recent runs\n\n" + "\n".join(runs_lines))
            if ar_state:
                ctx_parts.append(f"## Autoresearch state (last 3 rows)\n\n```\n{ar_state}\n```")

            if not ctx_parts:
                print("[error] no context available — run /orientation first")
                trace.finish("ERROR")
                return

            full_ctx = "\n\n".join(ctx_parts)

            # ── 6. Synthesise one recommendation ─────────────────────────────
            _prompt = (
                "You are advising an ML engineer on what to work on next.\n\n"
                f"{full_ctx}\n\n"
                "---\n\n"
                "Based on the project state above, identify the single most valuable next task. "
                "Consider: unresolved failures from recent runs, incomplete benchmarks, "
                "open experiments, and natural follow-ons from recent commits.\n\n"
                "Respond in this exact format — nothing else:\n\n"
                "**Suggested task:** <one sentence describing the task>\n\n"
                "**Why:** <2-3 sentences of rationale referencing specific evidence above>\n\n"
                "**Command:** `<the exact command or action to take>`\n\n"
                "The command must be a real, runnable shell invocation. "
                "Use only these signatures:\n"
                "  python agent.py \"<task description and output path>\"\n"
                "  python bench_model_compare.py --test-model <tag> --baseline-model <tag> [--run-both]\n"
                "  python autoresearch.py [--tasks T_A,T_B] [--rounds N]\n"
                "  python eval_suite.py [--fast] [--no-wiggum]\n"
                "  python orchestrator.py \"<compound task>\"\n"
                "Do not invent flags, subcommands, or module paths that are not listed above."
            )
            print(f"  [suggest] synthesising ({len(_prompt)} char prompt)...")
            with trace.span("suggest_synth", model=producer_model):
                _resp = ollama.chat(
                    model=producer_model,
                    messages=[{"role": "user", "content": _prompt}],
                    options={"temperature": 0.15, "num_predict": 512},
                )
            trace.log_usage(_resp, stage="suggest_synth")
            content = clean_synthesis_output((_resp.message.content or "").strip())

            if not content:
                print("[error] synthesis returned empty output")
                trace.finish("ERROR")
                return

            print("\n" + content + "\n")

            if path:
                write_output(content, path, trace)
            else:
                trace.data["final_content"] = content
                trace.data["output_bytes"]  = len(content.encode())

            trace.finish("PASS")
            _store_memory(memory, task, "suggest", trace.data, content)

        def _handle_troubleshoot():
            print("\n[skill:troubleshoot] diagnosing failures and planning next step...")
            trace.data["task_type"] = "troubleshoot"

            import re as _re_ts
            import json as _json_ts
            import time as _t_ts
            import tempfile as _tmp_ts

            from harness.config import ROOT as _ROOT_TS, RUNS_FILE as _RUNS_TS, TRACES_DIR as _TRACES_TS
            _base_ts = _ROOT_TS / 'harness'

            # ── 1. Parse optional filter ──────────────────────────────────────
            _filter_raw = _re_ts.sub(r"^/troubleshoot\s*", "", task, flags=_re_ts.IGNORECASE).strip()
            _filter = _filter_raw.lower() if _filter_raw else ""

            # ── 2. Load recent ERROR/FAIL runs ───────────────────────────────
            _runs_path_ts = _RUNS_TS
            all_runs = []
            if _runs_path_ts.exists():
                try:
                    for _line in _runs_path_ts.read_text(encoding="utf-8", errors="replace").splitlines():
                        _line = _line.strip()
                        if _line:
                            try:
                                all_runs.append(_json_ts.loads(_line))
                            except Exception:
                                pass
                except Exception:
                    pass

            _excluded_types = {"debug", "suggest", "orientation", "re-orient", "troubleshoot"}

            def _ts_run_matches(r):
                if r.get("final") not in ("ERROR", "FAIL"):
                    return False
                if r.get("task_type") in _excluded_types:
                    return False
                if not _filter:
                    return True
                haystack = " ".join([
                    r.get("task_type") or "",
                    r.get("final") or "",
                    r.get("run_id") or "",
                    r.get("producer_model") or "",
                    r.get("task") or "",
                ]).lower()
                return _filter in haystack

            candidates = [r for r in all_runs if _ts_run_matches(r)]
            targets = candidates[-2:] if candidates else []
            if targets:
                print(f"  [troubleshoot] {len(candidates)} failure(s) — analysing last {len(targets)}")
            else:
                print("  [troubleshoot] no recent failures — switching to suggest-only mode")

            # ── 3. Project context: orientation, git log, autoresearch ────────
            orientation_doc = ""
            ori_age_min = None
            _ori_path_ts = os.path.join(_tmp_ts.gettempdir(), "harness_orientation_raw.md")
            if os.path.exists(_ori_path_ts):
                ori_age_min = round((_t_ts.time() - os.path.getmtime(_ori_path_ts)) / 60, 1)
                try:
                    orientation_doc = open(_ori_path_ts, encoding="utf-8").read()[:3000]
                except Exception:
                    pass
            if ori_age_min is None:
                print("  [troubleshoot] no orientation cache — run /orientation for richer context")
            elif ori_age_min > 30:
                print(f"  [troubleshoot] orientation cache is {ori_age_min}min old — consider /re-orient")

            git_log = ""
            try:
                git_log = subprocess.check_output(
                    ["git", "log", "--oneline", "-12"],
                    cwd=_base_ts, stderr=subprocess.DEVNULL, text=True,
                ).strip()
            except Exception:
                pass

            ar_state = ""
            _ar_path_ts = _base_ts / "autoresearch.tsv"
            if _ar_path_ts.exists():
                try:
                    _ar_lines = _ar_path_ts.read_text(encoding="utf-8", errors="replace").splitlines()
                    ar_state = "\n".join(([_ar_lines[0]] if _ar_lines else []) + _ar_lines[-3:])
                except Exception:
                    pass

            # ── 4. Failure detail: run records, source, trace events ──────────
            _SOURCE_MAP_TS = {
                "annotate":       [("skills.py",            "run_annotate_standalone")],
                "introspect":     [("agent.py",              "_handle_introspect")],
                "re-orient":      [("agent.py",              "_handle_reorient")],
                "orientation":    [("orientation_skill.py",  "def build_orientation")],
                "research":       [("agent.py",              "SYNTH_INSTRUCTION"), ("wiggum.py", "def loop")],
                "best_practices": [("agent.py",              "SYNTH_INSTRUCTION"), ("wiggum.py", "def loop")],
                "enumerated":     [("agent.py",              "SYNTH_INSTRUCTION_COUNT"), ("wiggum.py", "def loop")],
            }

            def _ts_extract_source(fname, anchor, max_chars=1200):
                fpath = _base_ts / fname
                if not fpath.exists():
                    return ""
                text = fpath.read_text(encoding="utf-8", errors="replace")
                idx = text.find(anchor)
                start = max(0, (idx - 100) if idx != -1 else 0)
                return text[start:start + max_chars]

            def _ts_read_trace(run_id):
                traces_dir = _TRACES_TS
                if not traces_dir.exists():
                    return ""
                matches = list(traces_dir.glob(f"{run_id}_*.json"))
                if not matches:
                    return ""
                try:
                    data = _json_ts.loads(matches[0].read_text(encoding="utf-8", errors="replace"))
                    lines = []
                    for e in [e for e in data.get("traceEvents", []) if e.get("ph") == "X"]:
                        dur_ms = round(e.get("dur", 0) / 1000)
                        err_str = f"  ERROR: {e['args']['error']}" if e.get("args", {}).get("error") else ""
                        lines.append(f"  {e['name']:35s} {dur_ms:6d}ms{err_str}")
                    return "\n".join(lines)
                except Exception:
                    return ""

            ctx_parts = []

            # Failure run blocks
            failure_blocks = []
            for run in targets:
                tt       = run.get("task_type", "unknown")
                final    = run.get("final", "?")
                model    = run.get("producer_model", "")
                dur      = run.get("run_duration_s", 0)
                run_id   = run.get("run_id", "")
                task_str = (run.get("task") or "")[:120]
                scores   = run.get("wiggum_scores") or []
                eval_log = run.get("wiggum_eval_log") or []

                block = [
                    f"### Run {run_id}",
                    f"task_type={tt}  final={final}  model={model}  duration={dur}s",
                    f"task: {task_str}",
                ]
                if scores:
                    block.append(f"wiggum_scores: {scores}")
                for entry in eval_log[-2:]:
                    dims   = entry.get("dims", {})
                    issues = entry.get("issues", [])
                    block.append(f"eval round {entry.get('round')}: score={entry.get('score')}  dims={dims}")
                    if issues:
                        block.append("issues:\n" + "\n".join(f"  - {i}" for i in issues[:4]))
                events_str = _ts_read_trace(run_id)
                if events_str:
                    block.append(f"trace events:\n{events_str}")
                failure_blocks.append("\n".join(block))

            if failure_blocks:
                ctx_parts.append("## Recent failures\n\n" + "\n\n".join(failure_blocks))

            # Source excerpts for failure task types
            seen_ts = set()
            source_blocks = []
            for tt in set(r.get("task_type", "") for r in targets):
                for fname, anchor in _SOURCE_MAP_TS.get(tt, [("agent.py", "SYNTH_INSTRUCTION")]):
                    if (fname, anchor) not in seen_ts:
                        seen_ts.add((fname, anchor))
                        snippet = _ts_extract_source(fname, anchor)
                        if snippet:
                            source_blocks.append(f"### {fname} (near `{anchor}`)\n```python\n{snippet}\n```")
            if source_blocks:
                ctx_parts.append("## Relevant source\n\n" + "\n\n".join(source_blocks))

            # Project context
            if orientation_doc:
                age_note = f"(cached {ori_age_min}min ago)" if ori_age_min is not None else ""
                ctx_parts.append(f"## Project orientation {age_note}\n\n{orientation_doc}")
            if git_log:
                ctx_parts.append(f"## Recent commits\n\n```\n{git_log}\n```")
            if ar_state:
                ctx_parts.append(f"## Autoresearch state\n\n```\n{ar_state}\n```")

            if not ctx_parts:
                print("[error] no context available — run /orientation first")
                trace.finish("ERROR")
                return

            full_ctx = "\n\n".join(ctx_parts)

            # ── 5. Unified synthesis ──────────────────────────────────────────
            mode_note = (
                "There are recent failures to diagnose. Identify the root cause and exact fix, "
                "then recommend what to do NEXT once the fix is applied."
                if targets else
                "No recent failures found. Recommend the single most valuable next task "
                "based on project state, recent commits, and autoresearch progress."
            )

            _prompt = (
                "You are a senior engineer reviewing an agentic ML research harness. "
                f"{mode_note}\n\n"
                f"{full_ctx}\n\n"
                "---\n\n"
                "Respond in this exact format — nothing else:\n\n"
                "**Issue:** <one sentence — active failure pattern, or 'No active failures'>\n\n"
                "**Root cause:** <2-3 sentences — cite specific run IDs, scores, or source lines>\n\n"
                "**Fix:**\n<concrete code change, config update, or shell command ready to apply>\n\n"
                "**Next task after fix:** <one sentence — what to prioritise once the fix is in>\n\n"
                "**Command:** `<exact shell command>`\n\n"
                "Command must use only these signatures:\n"
                "  python agent.py \"<task description and output path>\"\n"
                "  python bench_model_compare.py --test-model <tag> --baseline-model <tag> [--run-both]\n"
                "  python autoresearch.py [--tasks T_A,T_B] [--rounds N]\n"
                "  python eval_suite.py [--fast] [--no-wiggum]\n"
                "  python orchestrator.py \"<compound task>\"\n"
                "Do not invent flags, subcommands, or module paths not listed above."
            )

            print(f"  [troubleshoot] synthesising ({len(_prompt)} char prompt)...")
            with trace.span("troubleshoot_synth", model=producer_model):
                _resp = ollama.chat(
                    model=producer_model,
                    messages=[{"role": "user", "content": _prompt}],
                    options={"temperature": 0.1, "num_predict": 768},
                )
            trace.log_usage(_resp, stage="troubleshoot_synth")
            content = clean_synthesis_output((_resp.message.content or "").strip())

            if not content:
                print("[error] synthesis returned empty output")
                trace.finish("ERROR")
                return

            print("\n" + content + "\n")

            if path:
                write_output(content, path, trace)
            else:
                trace.data["final_content"] = content
                trace.data["output_bytes"]  = len(content.encode())

            trace.finish("PASS")
            _store_memory(memory, task, "troubleshoot", trace.data, content)

        def _handle_sync_wiki():
            print("\n[skill:sync-wiki] extracting implementation facts from source code...")
            trace.data["task_type"] = "sync_wiki"
            from harness.skills.wiki_sync import sync as _wiki_sync
            summary = _wiki_sync()
            print(f"  [sync-wiki] {summary.splitlines()[0]}")
            content = summary
            print("\n" + content[:800] + ("..." if len(content) > 800 else "") + "\n")
            write_output(content, path, trace)
            trace.finish("PASS")

        def _handle_queue():
            import urllib.request as _urllib
            import json as _json

            # tasks separated by ;; in the task string
            subtasks = [t.strip() for t in task.split(";;") if t.strip()]
            if not subtasks:
                print("[queue] usage: /queue <task1> ;; <task2> ;; ...")
                trace.finish("ERROR")
                return

            server_url = os.environ.get("HARNESS_SERVER", "http://127.0.0.1:8765")
            queued = []
            for i, subtask in enumerate(subtasks, 1):
                body = _json.dumps({"task": subtask}).encode()
                req  = _urllib.Request(
                    f"{server_url}/api/queue",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with _urllib.urlopen(req, timeout=10) as resp:
                        d = _json.loads(resp.read())
                    print(f"[queue] [{i}/{len(subtasks)}] position={d.get('position')}  id={d.get('queue_id')}  {subtask[:60]}")
                    queued.append(d)
                except Exception as exc:
                    print(f"[queue] [{i}/{len(subtasks)}] FAILED: {exc}  task={subtask[:60]}")

            print(f"[queue] {len(queued)}/{len(subtasks)} task(s) enqueued.")
            trace.finish("PASS")

        def _handle_forge_list():
            if not _pl:
                print("[forge] plugin_loader not available")
                trace.finish("ERROR")
                return
            cmds = _pl.get_commands()
            if not cmds:
                print("[forge] no plugins installed")
            else:
                print(f"\n[forge:list] {len(cmds)} plugin command(s):\n")
                current_plugin = None
                for key in sorted(cmds):
                    plugin_name = cmds[key]["plugin"]
                    if plugin_name != current_plugin:
                        current_plugin = plugin_name
                        print(f"\n  ▸ {plugin_name}")
                    desc = cmds[key]["definition"].get("description", "")
                    print(f"    /{key:<28} {desc}")
                print()
            trace.finish("PASS")

        def _handle_forge_plugin():
            if not _pl:
                print("[forge] plugin_loader not available")
                trace.finish("ERROR")
                return
            # task has already had /forge:plugin stripped by parse_skills()
            raw = task.strip()
            if not raw:
                print("[forge:plugin] usage: /forge:plugin <description of what the plugin should do>")
                trace.finish("ERROR")
                return

            print(f"\n[forge:plugin] designing plugin: {raw[:80]}...")

            _forge_prompt = f"""You are designing a plugin for a local AI research agent called "harness".

Plugin description: {raw}

Generate a complete plugin definition as a single JSON object with this exact structure:
{{
  "name": "<short-slug, e.g. 'code-review'>",
  "manifest": {{
    "name": "<same slug>",
    "description": "<one-sentence description>",
    "version": "1.0",
    "commands": [
      {{
        "name": "<command-name>",
        "description": "<what this command does>",
        "path_optional": true,
        "template": "commands/<command-name>.md"
      }}
    ],
    "skills": [
      {{"name": "<skill-name>", "path": "skills/<skill-name>.md"}}
    ],
    "connectors": []
  }},
  "skills": {{
    "<skill-name>": "<multi-line skill prompt content — domain expertise, best practices, heuristics>"
  }},
  "commands": {{
    "<command-name>": "<multi-line command template — instructions for how the LLM should handle this command>"
  }}
}}

Rules:
- name must be a lowercase hyphen-slug, no spaces
- Include 1-3 commands and 1-2 skill files
- Skills contain domain knowledge injected into every task using this plugin
- Commands are prompt templates invoked by /name:command-name
- Output ONLY valid JSON — no markdown fences, no explanation

"""
            from harness import inference as _inf_forge
            import json as _json_forge
            resp = _inf_forge.chat(
                model=producer_model,
                messages=[{"role": "user", "content": _forge_prompt}],
                temperature=0.3,
            )
            raw_json = resp.message.content.strip()
            # Strip markdown fences if model wrapped anyway
            if raw_json.startswith("```"):
                raw_json = "\n".join(
                    line for line in raw_json.splitlines()
                    if not line.strip().startswith("```")
                )

            try:
                plugin_def = _json_forge.loads(raw_json)
            except Exception as parse_err:
                print(f"[forge:plugin] JSON parse error: {parse_err}")
                print(f"  raw output:\n{raw_json[:500]}")
                trace.finish("ERROR")
                return

            name     = plugin_def.get("name", "unnamed")
            manifest = plugin_def.get("manifest", {})
            skills   = plugin_def.get("skills", {})
            commands = plugin_def.get("commands", {})

            print(f"  [forge] creating plugin: {name}")
            try:
                _pl.create_plugin(name, manifest, skills, commands)
                print(f"  [forge] plugin '{name}' installed at plugins/{name}/")
                print("  [forge] commands: " + ", ".join(f"/{name}:{c}" for c in commands))
                print("  [forge] skills:   " + ", ".join(skills.keys()))
            except Exception as create_err:
                print(f"[forge:plugin] create error: {create_err}")
                trace.finish("ERROR")
                return

            trace.finish("PASS")

        def _handle_plugin_command(skill_key: str):
            """Dispatch a non-forge plugin command through the synthesis pipeline."""
            nonlocal _plugin_cmd_context  # type: ignore[misc]
            if not _pl:
                print("[plugin] plugin_loader not available")
                trace.finish("ERROR")
                return
            cmd_info = _pl.get_commands().get(skill_key)
            if not cmd_info:
                print(f"[plugin] unknown command: {skill_key}")
                trace.finish("ERROR")
                return
            template = cmd_info.get("template", "")
            _plugin_cmd_context = f"# Plugin command: /{skill_key}\n\n{template}"
            # Fall through — synthesis pipeline picks up _plugin_cmd_context

        _plugin_cmd_context = ""

        def _handle_site():
            import re as _re
            from harness.skills.site_skill import extract_design_system, generate_page, parse_site_task
            from harness.vision import VISION_MODEL as _VM

            _skill_name = next((s for s in explicit_skills if s in ("design", "build-page", "site")), "site")
            print(f"\n[skill:{_skill_name}] starting...")
            trace.data["task_type"] = _skill_name

            try:
                parsed = parse_site_task(task)
            except ValueError as _e:
                print(f"[error] {_e}")
                trace.finish("ERROR")
                return

            _mode      = parsed["mode"]
            _url       = parsed["url"]
            _ds_path   = parsed["design_system_path"]
            _content   = parsed["content_dir"]
            _out       = parsed.get("output_path") or path
            _refine    = parsed["refine_iterations"]
            _headed    = os.environ.get("HARNESS_HEADED") == "1"

            _original_shots: list[str] = []

            # ── Phase 1: extract design system ──────────────────────────────
            design_system_text = ""
            if _mode in ("design", "site"):
                design_system_text = extract_design_system(
                    url=_url,
                    model=producer_model,
                    vision_model=_VM,
                    headed=_headed,
                    run_id=trace.data.get("run_id", ""),
                )
                # Pull original screenshots for refinement pass
                _shot_m = _re.search(r"<!-- screenshots: (\[.*?\]) -->", design_system_text)
                if _shot_m:
                    try:
                        import json as _json_s
                        _original_shots = _json_s.loads(_shot_m.group(1))
                    except Exception:
                        pass

                if _mode == "design":
                    if not _out:
                        from datetime import datetime as _dt
                        _slug = _re.sub(r"[^\w]+", "-", _url.split("//")[-1].split("/")[0])[:30]
                        _out  = str(_ROOT / "data" / "output" / f"design-{_slug}-{_dt.now().strftime('%Y%m%dT%H%M%S')}.md")
                    write_output(design_system_text, _out, trace)
                    print(f"\n  [design] design system -> {_out}")
                    trace.finish("PASS")
                    _store_memory(memory, task, "design", trace.data, design_system_text)
                    return

            # ── Phase 2: generate HTML page ──────────────────────────────────
            if _mode in ("build-page", "site"):
                if _mode == "build-page" and _ds_path:
                    _ds_file = Path(_ds_path).expanduser()
                    if not _ds_file.exists():
                        print(f"[error] design system file not found: {_ds_path}")
                        trace.finish("ERROR")
                        return
                    design_system_text = _ds_file.read_text(encoding="utf-8")
                    # Extract any screenshots embedded in the file
                    _shot_m = _re.search(r"<!-- screenshots: (\[.*?\]) -->", design_system_text)
                    if _shot_m:
                        try:
                            import json as _json_s
                            _original_shots = _json_s.loads(_shot_m.group(1))
                        except Exception:
                            pass

                if not design_system_text:
                    print("[error] no design system available for page generation")
                    trace.finish("ERROR")
                    return
                if not _content:
                    print("[error] /build-page requires a content directory: from <dir/>")
                    trace.finish("ERROR")
                    return

                if not _out:
                    from datetime import datetime as _dt
                    _out = str(_ROOT / "data" / "output" / f"page-{_dt.now().strftime('%Y%m%dT%H%M%S')}.html")

                try:
                    html = generate_page(
                        design_system   = design_system_text,
                        content_dir     = _content,
                        model           = producer_model,
                        vision_model    = _VM,
                        output_path     = _out,
                        refine_iterations = _refine,
                        original_screenshots = _original_shots or None,
                        run_id          = trace.data.get("run_id", ""),
                    )
                except ValueError as _e:
                    print(f"[error] {_e}")
                    trace.finish("ERROR")
                    return

                write_output(html, _out, trace)
                print(f"\n  [{_skill_name}] page -> {_out}")
                trace.finish("PASS")
                _store_memory(memory, task, _skill_name, trace.data, html[:8000])

        def _handle_deck():
            import re as _re
            from datetime import datetime as _dt
            from pathlib import Path as _Path

            from harness.skills.deck import (
                DesignTheme, build_deck, load_content,
                parse_deck_task, parse_design_tokens,
            )
            from harness.skills.site_skill import extract_design_system

            print("\n[skill:deck] starting...")
            trace.data["task_type"] = "deck"

            try:
                parsed = parse_deck_task(task)
            except ValueError as _e:
                print(f"[error] {_e}")
                trace.finish("ERROR")
                return

            _design_src  = parsed["design_src"]
            _content_src = parsed["content_src"]
            _out         = parsed["output_path"]
            _title       = parsed["title"]

            if not _out:
                _slug = _re.sub(r"[^\w]+", "-", (_title or "deck").lower())[:30]
                _out  = str(_ROOT / "data" / "output" / f"deck-{_slug}-{_dt.now().strftime('%Y%m%dT%H%M%S')}.pptx")

            # ── Step 1: design system ────────────────────────────────────────
            design_md = ""
            if _design_src:
                if _design_src.startswith("http"):
                    from harness.vision import VISION_MODEL as _VM
                    print(f"  [deck] extracting design system from {_design_src}...")
                    design_md = extract_design_system(
                        url      = _design_src,
                        model    = producer_model,
                        vision_model = _VM,
                        headed   = False,
                        run_id   = trace.data.get("run_id", ""),
                    )
                else:
                    _ds_file = _Path(_design_src).expanduser()
                    if not _ds_file.exists():
                        print(f"[error] design file not found: {_ds_file}")
                        trace.finish("ERROR")
                        return
                    design_md = _ds_file.read_text(encoding="utf-8")

            theme = parse_design_tokens(design_md) if design_md else DesignTheme()
            print(f"  [deck] theme: bg={theme.bg_primary}  accent={theme.accent}  font={theme.heading_font}")

            # ── Step 2: content ──────────────────────────────────────────────
            if not _content_src:
                print("[error] /deck requires --content <url|folder|pdf>")
                trace.finish("ERROR")
                return

            try:
                content_pages = load_content(_content_src)
            except (ValueError, RuntimeError) as _e:
                print(f"[error] {_e}")
                trace.finish("ERROR")
                return

            # ── Step 3: build deck ───────────────────────────────────────────
            out_path = build_deck(
                theme       = theme,
                content     = content_pages,
                output_path = _out,
                deck_title  = _title,
            )

            trace.data["output_path"] = out_path
            trace.finish("PASS")
            _store_memory(
                memory, task, "deck", trace.data,
                f"Deck: {_title or 'untitled'} | {len(content_pages)} source(s) | design: {_design_src or 'default'} | out: {out_path}",
            )
            print(f"\n  [deck] → {out_path}")

        _STANDALONE = {
            "annotate":     _handle_annotate,
            "email":        _handle_email,
            "github":       _handle_github,
            "review":       _handle_review,
            "lit-review":   _handle_lit_review,
            "recall":       _handle_recall,
            "queue":        _handle_queue,
            "introspect":   _handle_introspect,
            "orientation":  _handle_orientation,
            "sync-wiki":    _handle_sync_wiki,
            "playwright":   _handle_playwright,
            "sitemap":      _handle_sitemap,
            "crawl":        _handle_sitemap,
            "transcribe":   _handle_transcribe,
            "re-orient":    _handle_reorient,
            "debug":        _handle_debug,
            "suggest":      _handle_suggest,
            "troubleshoot": _handle_troubleshoot,
            "forge:plugin": _handle_forge_plugin,
            "forge:list":   _handle_forge_list,
            "design":       _handle_site,
            "build-page":   _handle_site,
            "site":         _handle_site,
            "deck":         _handle_deck,
        }

        for _skill in explicit_skills:
            if _skill in _STANDALONE:
                _STANDALONE[_skill]()
                return
            # Non-forge plugin commands — set context then fall through to synthesis
            if _pl and _skill in _pl.get_commands():
                _handle_plugin_command(_skill)
                break  # don't return; continue to synthesis pipeline

        # Plugin commands with pre-fetched URL content skip memory + planning —
        # the command template + URL content is sufficient context for synthesis.
        if _plugin_cmd_context and has_url_content:
            memory_context = ""
            plan           = Plan(task_type="research", complexity="low", notes="")
            auto_skills    = []
            active_skills  = list(explicit_skills)
            print("  [plugin] URL content available — skipping memory + planner")
        else:
            # Memory retrieval — before planning so the planner can use prior context
            trace.set_stage("memory")
            with trace.span("memory_retrieval"):
                memory_context, _mem_titles = memory.get_context_with_titles(task)
            if memory_context:
                memory_hits = len(_mem_titles)
                print(f"\n  [memory] injecting {memory_hits} past observation(s)")
                for t in _mem_titles:
                    print(f"    • {t}")
                trace.log_memory_hits(memory_hits, titles=_mem_titles)
            else:
                print("\n  [memory] no relevant history")

            # Planning — analyse task + memory; produces search queries and synthesis notes
            trace.set_stage("plan")
            print("  [planner] generating plan...")
            with trace.span("planner"):
                plan, _planner_resp = make_plan(task, memory_context)
            trace.log_plan(plan.to_dict())
            trace.log_plan_record(plan.to_dict(), plan_type="agent")
            if _planner_resp is not None:
                trace.log_usage(_planner_resp, stage="planner")
                trace.log_planner_cot(_planner_resp)
            print(f"  [planner] {plan.task_type} / {plan.complexity}"
                  + (f" / {plan.expected_sections} sections" if plan.expected_sections else "")
                  + (f"\n  [planner] note: {plan.notes}" if plan.notes else ""))

            # Skill activation — merge explicit + auto-triggered
            auto_skills   = auto_activate(task, plan)
            active_skills = merge_skills(explicit_skills, auto_skills)

        # Refine keep_alive now that task_type and active_skills are known
        if _KEEP_ALIVE_OVERRIDE is None:
            _KEEP_ALIVE = _estimate_keep_alive(
                task_type=plan.task_type,
                explicit_skills=set(active_skills),
                use_wiggum=use_wiggum,
            )
            print(f"  [agent] keep_alive refined to {_KEEP_ALIVE}s ({plan.task_type})")
        if auto_skills:
            print(f"  [skills] auto-activated: {auto_skills}")
        if active_skills:
            print(f"  [skills] active: {active_skills}")

        # Combined synthesis context: memory observations + planner notes
        plan_ctx = plan.synthesis_context()
        full_memory_context = "\n\n".join(filter(None, [memory_context, plan_ctx]))

        print("\n[turn 1] researching...\n")
        trace.name_thread("main")
        force_deep = "deep" in active_skills
        if force_deep:
            print("  [skill:deep] novelty gate disabled — running all search rounds")

        # Contextualize — inject agent self-knowledge and skip web search
        _skip_research = False
        if "contextualize" in active_skills:
            from harness.skills import load_context_files
            from harness.skills.wiki_sync import get_relevant_wiki_context as _get_wiki_ctx
            _ctx_content = load_context_files()
            _wiki_ctx = _get_wiki_ctx()
            if _wiki_ctx:
                _ctx_content = (_ctx_content + "\n\n" + _wiki_ctx).strip() if _ctx_content else _wiki_ctx
            if _ctx_content:
                file_context = (file_context + "\n\n" + _ctx_content).strip() if file_context else _ctx_content
                _skip_research = True
                wiki_note = f" + {len(_wiki_ctx)}ch wiki" if _wiki_ctx else ""
                print(f"  [skill:contextualize] injected {len(_ctx_content)} chars of agent context{wiki_note}; skipping web search")
            else:
                print("  [skill:contextualize] no context files found — falling back to web search")

        # If local files were read, treat their content as the research source and
        # skip web search — the data is already on disk, searching the web won't help.
        if text_files and file_context and not _skip_research:
            _skip_research = True
            print(f"  [read_file] {len(text_files)} local file(s) loaded — skipping web search")

        if has_url_content or _skip_research:
            if has_url_content:
                print("  [fetch_url] document already fetched — skipping web search")
            # Promote injected content to research slot so the model treats it as
            # primary source material rather than supplementary context.
            if file_context:
                context = file_context
                file_context = ""
            else:
                context = ""
        else:
            trace.set_stage("search")
            with trace.span("gather_research"):
                context = gather_research(task, trace, planned_queries=plan.search_queries or None, producer_model=producer_model, force_deep=force_deep, task_type=plan.task_type or "")

        # run_python tool loop — skip for pure research tasks unless /scratchpad is active
        code_context = ""
        _scratchpad_active = "scratchpad" in active_skills
        if plan.task_type in ("research", "best_practices") and not _scratchpad_active:
            print("\n  [tool loop] skipped for research task")
        else:
            tag = " (scratchpad)" if _scratchpad_active else ""
            print(f"\n  [tool loop] checking for code execution needs...{tag}")
            with trace.span("tool_loop"):
                code_context = run_tool_loop(task, context, trace, producer_model=producer_model)
            if code_context:
                print(f"  [tool loop] {len(code_context)} chars of execution output")
            else:
                print("  [tool loop] no code needed")

        # Inject prior scratchpad results for this topic (non-blocking)
        if _scratchpad_active:
            try:
                from harness.config import ROOT as _ROOT_WS
                import sys as _sys
                _ws = str(_ROOT_WS / "agent-workspace")
                if _ws not in _sys.path:
                    _sys.path.insert(0, _ws)
                from scratch_helpers import load_recent as _load_scratch
                from harness.security import strip_injection_candidates
                prior = _load_scratch(n=3, task_hint=task[:60])
                if prior:
                    prior, _removed = strip_injection_candidates(prior)
                    if _removed:
                        print(f"  [scratchpad] stripped {_removed} injection candidate line(s) from prior results")
                    code_context = (code_context + "\n\nPrior scratchpad results:\n" + prior).strip()
                    print(f"  [scratchpad] injected {len(prior)} chars of prior results")
            except Exception as _sc_err:
                print(f"  [scratchpad] prior load error (non-fatal): {_sc_err}")

        # Pre-synthesis skill injections
        skill_context = get_prompt_injections(active_skills, "pre_synthesis")

        # Plugin command template injection
        if _plugin_cmd_context:
            skill_context = (_plugin_cmd_context + "\n\n" + skill_context).strip() if skill_context else _plugin_cmd_context

        # Plugin skill auto-inject (all loaded plugins' skill content)
        if _pl:
            _plugin_skill_ctx = _pl.get_skill_context()
            if _plugin_skill_ctx:
                skill_context = (skill_context + "\n\n" + _plugin_skill_ctx).strip() if skill_context else _plugin_skill_ctx

        if "contextualize" in active_skills:
            _ctx_directive = (
                "The research context above contains source code, implementation details, "
                "specific values (thresholds, weights, dimension names), and function bodies. "
                "You MUST cite these specifics in your output — do not summarize generically. "
                "For example: name the exact evaluation dimensions and their weights, quote "
                "specific threshold values, and describe how functions actually work per the "
                "provided source, not a hypothetical version."
            )
            skill_context = (_ctx_directive + "\n\n" + skill_context).strip() if skill_context else _ctx_directive
        if skill_context:
            skill_names = [s for s in active_skills if s in ("annotate", "cite")]
            print(f"  [skills] injecting pre_synthesis prompts: {skill_names}")

        # Count constraint: detect before synthesis so we can use the count-aware prompt directly
        expected_count = plan.expected_sections or extract_count_constraint(task)

        trace.set_stage("synth")
        print("\n  [synth] synthesizing from merged results...")
        if expected_count is not None:
            print(f"  [count] detected count constraint: {expected_count} — using count-aware synthesis")
            with trace.span("synthesize", model=producer_model):
                content = synthesize_with_count(task, context, expected_count, vision_context=vision_context, file_context=file_context, code_context=code_context, memory_context=full_memory_context, skill_context=skill_context, producer_model=producer_model, trace=trace)
        else:
            with trace.span("synthesize", model=producer_model):
                content = synthesize(task, context, vision_context=vision_context, file_context=file_context, code_context=code_context, memory_context=full_memory_context, skill_context=skill_context, producer_model=producer_model, trace=trace)

        # Clean fences and trailing epilogues before any downstream processing
        content = clean_synthesis_output(content)

        # Count verification (safety net — synthesis should already comply)
        if expected_count is not None:
            actual_count = count_output_items(content)
            if actual_count != expected_count:
                # Try a Python trim first: over-count (model produced too many) can be
                # fixed instantly by cutting at the (N+1)th ## boundary — no LLM call.
                # Under-count cannot be fixed in Python and falls through to LLM retry.
                trimmed = trim_to_count(content, expected_count)
                if trimmed is not None:
                    content = trimmed
                    print(f"\n[count check] trimmed {actual_count}->{expected_count} items (Python, no retry)")
                else:
                    print(f"\n[count check] expected {expected_count} items, got {actual_count} — retrying synthesis")
                    trace.log_count_retry()
                    content = synthesize_with_count(task, context, expected_count, vision_context=vision_context, file_context=file_context, code_context=code_context, memory_context=full_memory_context, skill_context=skill_context, producer_model=producer_model, trace=trace)
                    content = clean_synthesis_output(content)
                    actual_count = count_output_items(content)
                    if actual_count == expected_count:
                        print(f"  [count check] OK — {actual_count} items after retry")
                    else:
                        # Still wrong — try one more Python trim before giving up
                        trimmed = trim_to_count(content, expected_count)
                        if trimmed is not None:
                            content = trimmed
                            print(f"  [count check] trimmed {actual_count}->{expected_count} after retry")
                        else:
                            print(f"  [count check] still {actual_count} after retry — proceeding anyway")
            else:
                print(f"\n[count check] OK — {actual_count} items match constraint ({expected_count})")

        if not content.strip():
            print("[error] model returned empty content — check model and tool setup")
            trace.finish("ERROR")
            sys.exit(1)

        print("\n" + content + "\n")
        if path:
            write_output(content, path, trace)
        else:
            trace.finish("PASS")

        # Post-synthesis skill handlers (e.g. /knowledge-graph)
        if skills_at_hook(active_skills, "post_synthesis"):
            with trace.span("post_synthesis_skills"):
                run_post_synthesis(active_skills, content, task, path or "", producer_model)

        if use_wiggum:
            trace.set_stage("eval")
            # /panel skill activates the 3-persona panel inside wiggum
            if "panel" in active_skills:
                os.environ["WIGGUM_PANEL"] = "1"
                print("  [skill:panel] panel evaluation enabled")
            with trace.span("wiggum"):
                wiggum_trace = wiggum_loop(task, path or "", producer_model=producer_model, parent_trace=trace)
            trace.log_wiggum(wiggum_trace)
            print(f"\n[wiggum] {wiggum_trace['final']} after {len(wiggum_trace['rounds'])} round(s)")
            for r in wiggum_trace["rounds"]:
                print(f"  round {r['round']}: score={r['score']}/10  passed={r['passed']}")
                for issue in r.get("issues", []):
                    print(f"    - {issue}")

            all_wiggum_issues = [
                issue
                for r in wiggum_trace["rounds"]
                for issue in (r.get("issues") or [])
            ]

            # Gap-targeted wiki sync: when a contextualize run fails, extract source
            # sections that answer wiggum's issues so the next run has concrete facts.
            if wiggum_trace["final"] != "PASS" and "contextualize" in active_skills:
                if all_wiggum_issues:
                    print("\n  [sync-wiki:gaps] wiggum FAIL on contextualize — extracting gap facts...")
                    try:
                        from harness.skills.wiki_sync import sync_gaps as _sync_gaps
                        _sync_gaps(all_wiggum_issues)
                    except Exception as _gap_err:
                        print(f"  [sync-wiki:gaps] error (non-fatal): {_gap_err}")

            tac = _estimate_tac_hours(task, content, COMPRESS_MODEL)
            if tac is not None:
                trace.data["tac_hours"] = tac
            trace.finish()
            _store_memory(memory, task, wiggum_trace.get("task_type") or "", trace.data, content, wiggum_issues=all_wiggum_issues)

            # Post-run skill extraction — non-blocking
            try:
                from harness.skill_extractor import extract_and_store as _extract_skill
                _wiggum_score = float((wiggum_trace.get("rounds") or [{}])[-1].get("score", 0))
                _extract_skill(
                    task          = task,
                    trace_data    = trace.data,
                    wiggum_issues = all_wiggum_issues,
                    score         = _wiggum_score,
                    model         = COMPRESS_MODEL,
                    run_id        = trace.data.get("run_id", ""),
                )
            except Exception as _skill_err:
                print(f"  [skill] extraction error (non-fatal): {_skill_err}")
        else:
            tac = _estimate_tac_hours(task, content, COMPRESS_MODEL)
            if tac is not None:
                trace.data["tac_hours"] = tac
            trace.finish("PASS")
            from harness.wiggum import detect_task_type
            _store_memory(memory, task, detect_task_type(task), trace.data, content)

    except Exception as e:
        print(f"[error] unhandled exception: {e}")
        trace.finish("ERROR")
        raise


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print('usage: python agent.py "<task>"')
        print('       python agent.py --no-wiggum "<task>"')
        sys.exit(1)

    no_wiggum    = "--no-wiggum" in args
    headed       = "--headed"       in args
    keep_browser = "--keep-browser" in args
    reuse_browser= "--reuse-browser"in args
    if headed:        os.environ["HARNESS_HEADED"]       = "1"
    if keep_browser:  os.environ["HARNESS_KEEP_BROWSER"] = "1"
    if reuse_browser: os.environ["HARNESS_REUSE_BROWSER"]= "1"
    # reuse implies headed
    if reuse_browser: os.environ["HARNESS_HEADED"] = "1"

    producer = MODEL
    if "--producer" in args:
        idx = args.index("--producer")
        if idx + 1 < len(args):
            producer = args[idx + 1]
            args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    evaluator = None
    if "--evaluator" in args:
        idx = args.index("--evaluator")
        if idx + 1 < len(args):
            evaluator = args[idx + 1]
            args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    if "--from-env" in args:
        task = os.environ.get("AGENT_TASK", "").strip()
        if not task:
            print("[error] --from-env specified but AGENT_TASK env var is empty")
            sys.exit(1)
        # Parse --producer / --evaluator / --no-wiggum / --headed out of the task string too,
        # since the server bundles everything into AGENT_TASK to avoid MSYS2 path conversion.
        task_parts = task.split()
        clean_parts = []
        i = 0
        while i < len(task_parts):
            tok = task_parts[i]
            if tok == "--producer" and i + 1 < len(task_parts):
                producer = task_parts[i + 1]; i += 2
            elif tok == "--evaluator" and i + 1 < len(task_parts):
                evaluator = task_parts[i + 1]; i += 2
            elif tok == "--no-wiggum":
                no_wiggum = True; i += 1
            elif tok == "--headed":
                os.environ["HARNESS_HEADED"] = "1"; i += 1
            elif tok == "--keep-browser":
                os.environ["HARNESS_KEEP_BROWSER"] = "1"; i += 1
            elif tok == "--reuse-browser":
                os.environ["HARNESS_REUSE_BROWSER"] = "1"
                os.environ["HARNESS_HEADED"] = "1"; i += 1
            else:
                clean_parts.append(tok); i += 1
        task = " ".join(clean_parts)
    else:
        task_args = [a for a in args if a not in ("--no-wiggum", "--from-env", "--headed",
                                                    "--keep-browser", "--reuse-browser")]
        task = " ".join(task_args)

    run(task, use_wiggum=not no_wiggum, producer_model=producer, evaluator_model=evaluator)
