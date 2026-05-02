"""
harness/skills/site_skill.py — Design-system extraction and page generation.

Two skills:

  /design <url> [save to design.md]
      Visit a URL, extract CSS tokens and screenshots, synthesize a structured
      design system document (colors, typography, spacing, components, full CSS).

  /build-page <design.md> from <content_dir/> [save to index.html]
      Read all .md files in content_dir, combine with the design system, and
      generate a self-contained HTML page matching the source site's aesthetic.
      With --headed, opens the result in Chrome and iteratively refines against
      screenshots of the original.

  /site <url> from <content_dir/> [save to index.html]
      Both phases in one command.

Usage examples:
    oh /design https://vercel.com save to design-system.md
    oh /build-page design-system.md from ~/Desktop/content/ save to index.html
    oh /site https://stripe.com from ~/Desktop/content/ save to site/index.html
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# CSS / DOM extraction (runs inside the browser via Playwright evaluate)
# ---------------------------------------------------------------------------

_EXTRACT_JS = """
() => {
    // 1. CSS custom properties from :root
    const cssVars = {};
    for (const sheet of document.styleSheets) {
        try {
            for (const rule of sheet.cssRules) {
                if (rule.selectorText === ':root') {
                    const matches = [...rule.cssText.matchAll(/--([^:]+):\\s*([^;]+)/g)];
                    for (const m of matches) cssVars[m[1].trim()] = m[2].trim();
                }
            }
        } catch(e) {}
    }

    // 2. Computed styles for key element types
    const targets = {
        h1:          'h1',
        h2:          'h2',
        h3:          'h3',
        body:        'body',
        btn:         'button, [class*="btn"], [class*="button"], [class*="Button"]',
        nav:         'nav, header',
        hero:        '[class*="hero"], [class*="Hero"], main > section:first-child',
        card:        '[class*="card"], [class*="Card"], article',
        input:       'input[type="text"], input[type="email"], input',
        footer:      'footer',
    };
    const props = [
        'fontFamily','fontSize','fontWeight','lineHeight','letterSpacing',
        'color','backgroundColor','borderRadius','padding','border','boxShadow',
    ];
    const computed = {};
    for (const [name, sel] of Object.entries(targets)) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const cs = window.getComputedStyle(el);
        const out = {};
        for (const p of props) out[p] = cs[p];
        computed[name] = out;
    }

    // 3. Google Fonts links
    const fontLinks = [...document.querySelectorAll('link[href*="fonts.googleapis.com"]')]
        .map(l => l.href);

    // 4. All distinct background colors used in visible sections
    const bgColors = new Set();
    document.querySelectorAll('section, main, header, footer, [class*="section"]').forEach(el => {
        const bg = window.getComputedStyle(el).backgroundColor;
        if (bg && bg !== 'rgba(0, 0, 0, 0)') bgColors.add(bg);
    });

    return {
        cssVars,
        computed,
        fontLinks,
        bgColors: [...bgColors].slice(0, 12),
        title: document.title,
        metaDesc: document.querySelector('meta[name="description"]')?.content || '',
        url: location.href,
    };
}
"""


def _rgb_to_hex(rgb: str) -> str:
    """Convert rgb(r, g, b) → #rrggbb. Returns original string if not parseable."""
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", rgb)
    if m:
        return f"#{int(m.group(1)):02x}{int(m.group(2)):02x}{int(m.group(3)):02x}"
    return rgb


def _format_tokens(tokens: dict) -> str:
    """Render extracted browser tokens as readable text for the LLM prompt."""
    lines = []

    css_vars = tokens.get("cssVars", {})
    if css_vars:
        lines.append("## CSS Custom Properties (:root)")
        for k, v in list(css_vars.items())[:60]:
            lines.append(f"  --{k}: {v}")

    computed = tokens.get("computed", {})
    if computed:
        lines.append("\n## Computed Styles")
        for el, props in computed.items():
            lines.append(f"\n### {el}")
            for p, v in props.items():
                if v and v not in ("", "normal", "none", "0px"):
                    lines.append(f"  {p}: {v}")

    bg = tokens.get("bgColors", [])
    if bg:
        lines.append("\n## Section Background Colors")
        for c in bg:
            lines.append(f"  {c}  →  {_rgb_to_hex(c)}")

    fonts = tokens.get("fontLinks", [])
    if fonts:
        lines.append("\n## Google Fonts")
        for f in fonts:
            lines.append(f"  {f}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Design System Extraction
# ---------------------------------------------------------------------------

_DESIGN_SYSTEM_PROMPT = """\
You are a frontend design analyst. A browser visited {url} and captured the following data.

CAPTURED DATA:
{tokens}

SCREENSHOT OBSERVATIONS:
{screenshot_desc}

SITE TITLE: {title}
META DESCRIPTION: {meta_desc}

---

Produce a structured design system document in markdown. Match the format of the example below EXACTLY — \
use the same section structure and level of detail. Be precise: use exact hex codes from computed colors, \
exact px/em values from computed typography, and exact border-radius from components.

Required sections (use these exact headings):
1. Overview — 2-3 sentence aesthetic description + Key Characteristics bullet list
2. Color System — tables for Background Surfaces, Text Colors, Accents, Gradients (as CSS), Borders
3. Typography System — Font Families, CDN link if Google Fonts detected, Hierarchy table, CSS Font Stacks
4. Spacing System — Scale table (4px base) + Layout table (max-width, padding)
5. Border Radius — token table
6. Components — CSS for primary button, secondary button, cards, inputs
7. Shadows — token table with CSS values
8. Animation System — transition vars + common patterns
9. Complete CSS Implementation — full :root block + reset + typography + button + container classes
10. Design Principles — table of 5-7 principles derived from the visual style

Font substitution: if proprietary fonts are detected, document a Google Fonts substitute in a note at the top.

Output ONLY the markdown document, no commentary before or after."""


def extract_design_system(
    url: str,
    model: str,
    vision_model: str,
    headed: bool = False,
    run_id: str = "",
) -> str:
    """
    Visit url with Playwright, extract CSS tokens + screenshots, synthesize
    a structured design system document. Returns markdown string.
    """
    from harness.inference import chat as _chat

    if not url.startswith("http"):
        url = "https://" + url

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright not installed — pip install playwright && playwright install chromium")

    tokens: dict = {}
    screenshots: list[str] = []
    section_shots: list[str] = []

    print(f"  [design] visiting {url}...")

    _pw_ctx = sync_playwright()
    pw = _pw_ctx.start()
    try:
        browser = pw.chromium.launch(headless=not headed, slow_mo=50 if headed else 0)
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        ctx  = browser.new_context(user_agent=ua, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(15_000)
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(2)  # let fonts/JS settle

        # Full-page screenshot
        from harness.skills.playwright_skill import _take_screenshot
        shot = _take_screenshot(page, run_id, 0, "design_full", full_page=True)
        if shot:
            screenshots.append(shot)

        # Above-fold screenshot (hero)
        page.evaluate("window.scrollTo(0, 0)")
        hero = _take_screenshot(page, run_id, 1, "design_hero")
        if hero:
            section_shots.append(hero)

        # Mid-page (components)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        time.sleep(0.5)
        mid = _take_screenshot(page, run_id, 2, "design_mid")
        if mid:
            section_shots.append(mid)

        # Extract CSS tokens
        try:
            tokens = page.evaluate(_EXTRACT_JS)
        except Exception as e:
            print(f"  [design] CSS extraction error: {e}")
            tokens = {}

        browser.close()
    finally:
        try:
            _pw_ctx.stop()  # type: ignore[attr-defined]
        except Exception:
            pass

    tokens_text = _format_tokens(tokens) if tokens else "(no CSS tokens extracted)"
    print(f"  [design] extracted {len(tokens.get('cssVars', {}))} CSS vars, "
          f"{len(tokens.get('computed', {}))} element styles, "
          f"{len(screenshots)} screenshots")

    # Vision analysis of screenshots — with timeout so GPU contention doesn't hang the pipeline
    _VISION_TIMEOUT = int(os.environ.get("HARNESS_VISION_TIMEOUT", "300"))
    screenshot_desc = ""
    if section_shots and vision_model:
        try:
            from harness.vision import extract_image_context
            descs: list[str] = []
            for i, sp in enumerate(section_shots[:2]):
                label = "hero section" if i == 0 else "mid-page components"
                goal  = (f"Describe the visual design of this {label}: "
                         f"colors, typography, layout, components, spacing, overall aesthetic.")
                print(f"  [design] vision analysis: {label} (timeout={_VISION_TIMEOUT}s)...")
                # Run in a daemon thread so it can't block the process.
                # Null out inference callbacks first so the background thread
                # doesn't call start/stop spinner and corrupt the asyncio loop.
                import threading as _th
                try:
                    from harness import inference as _inf_mod
                    _saved_start = _inf_mod._on_inf_start
                    _saved_end   = _inf_mod._on_inf_end
                    _inf_mod._on_inf_start = None
                    _inf_mod._on_inf_end   = None
                except Exception:
                    _saved_start = _saved_end = None
                    _inf_mod = None  # type: ignore[assignment]

                _result  = [None]
                _evt     = _th.Event()

                def _run():  # noqa: B023
                    try:
                        _result[0] = extract_image_context(sp, goal)  # noqa: B023
                    except Exception:
                        pass
                    finally:
                        _evt.set()

                _t = _th.Thread(target=_run, daemon=True)
                _t.start()
                _completed = _evt.wait(timeout=_VISION_TIMEOUT)

                # Restore callbacks on the main thread
                if _inf_mod is not None:
                    _inf_mod._on_inf_start = _saved_start
                    _inf_mod._on_inf_end   = _saved_end

                if _completed:
                    desc = _result[0]
                    if desc:
                        descs.append(f"[{label.upper()}]\n{desc}")
                else:
                    print(f"  [design] vision timeout after {_VISION_TIMEOUT}s (GPU likely busy/evicted) — proceeding with CSS tokens only")
                    break
            screenshot_desc = "\n\n".join(descs) if descs else "(vision timed out — CSS tokens only)"
        except Exception as e:
            print(f"  [design] vision analysis error: {e}")
            screenshot_desc = "(screenshot analysis unavailable)"
    else:
        screenshot_desc = "(no screenshots available)"

    prompt = _DESIGN_SYSTEM_PROMPT.format(
        url=tokens.get("url", url),
        tokens=tokens_text,
        screenshot_desc=screenshot_desc,
        title=tokens.get("title", ""),
        meta_desc=tokens.get("metaDesc", ""),
    )

    print("  [design] synthesizing design system...")
    resp = _chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "num_predict": 8192},
    )
    result = resp["message"]["content"].strip()
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()

    # Store screenshots in result frontmatter
    if screenshots:
        header = f"<!-- screenshots: {json.dumps(screenshots)} -->\n\n"
        result = header + result

    return result


# ---------------------------------------------------------------------------
# Page Generation
# ---------------------------------------------------------------------------

_BUILD_PAGE_PROMPT = """\
You are a frontend engineer. Build a complete, self-contained HTML page.

DESIGN SYSTEM:
{design_system}

CONTENT FILES:
{content}

INSTRUCTIONS:
- Single HTML file with all CSS inline in a <style> tag (no external files except Google Fonts CDN)
- Match the design system EXACTLY: use the CSS variables, typography, colors, spacing, and component styles
- Structure the content into logical page sections (hero, features, body content, footer)
- Each .md file becomes a distinct section or card; use the filename as a section hint
- Include a navigation bar with the site name extracted from the content
- Make it responsive: mobile-first, max-width container, fluid typography
- Use the exact font families and Google Fonts link from the design system
- Apply the button styles, card styles, and spacing tokens from the design system
- Output ONLY the complete HTML document starting with <!DOCTYPE html>
- No placeholder text — use only the provided content{refine_note}"""

_REFINE_PROMPT = """\
You are a frontend engineer refining an HTML page.

ORIGINAL SITE SCREENSHOT OBSERVATIONS:
{original_desc}

CURRENT PAGE SCREENSHOT OBSERVATIONS:
{current_desc}

SPECIFIC DIFFERENCES TO FIX:
{differences}

CURRENT HTML:
{html}

Apply ONLY the listed fixes. Output the complete updated HTML document starting with <!DOCTYPE html>.
Do not change content — only visual/layout properties."""

_ANALYSIS_PROMPT = """\
You are a content architect. Analyze these research documents and organize them into a coherent page structure.

DOCUMENTS (filename: title + opening):
{summaries}

Output ONLY valid JSON, no markdown fences:
{{
  "site_title": "short descriptive title for the page (≤6 words)",
  "site_subtitle": "one sentence describing what this collection covers",
  "clusters": [
    {{
      "name": "Cluster Display Name",
      "slug": "cluster-slug",
      "description": "one sentence describing this topic group",
      "files": [
        {{"name": "filename.md", "title": "Concise Paper Title", "role": "featured|card|compact"}}
      ]
    }}
  ]
}}

Rules:
- 3-6 clusters; group by research theme, not filename prefix
- role: "featured" = 1-2 most significant papers per cluster (full detail shown);
        "card" = standard papers (title + abstract + key findings);
        "compact" = supplementary/peripheral (title + one-liner only)
- Clusters ordered from most to least central to the collection
- All files must appear in exactly one cluster"""

_SHELL_PROMPT = """\
You are a frontend engineer building a research portal page shell.

DESIGN SYSTEM:
{design_system}

PAGE STRUCTURE (JSON):
{structure}

CRITICAL RULE: Do NOT generate card titles, abstracts, or any paper content.
Cards will be injected later. Each file gets ONE placeholder comment and nothing else.

PLACEHOLDER FORMAT — copy this exactly, substituting the filename:
  <!-- SECTION:filename.md -->

INSTRUCTIONS:
- Output a complete HTML document starting with <!DOCTYPE html>
- All CSS in a <style> tag (no external files except Google Fonts CDN)
- Match the design system EXACTLY: CSS variables, font, colors, spacing, borders
- Section headings use smaller font than hero (max 1.1rem for card titles)
- Letter-spacing on section headings: max 0.05em
- Include:
    • Fixed nav: site_title left, cluster names as jump-links right
    • Hero: site_title (large) + site_subtitle
    • For each cluster in the JSON:
        <section id="{{slug}}">
          <h2 class="cluster-name">{{name}}</h2>
          <p class="cluster-desc">{{description}}</p>
          <div class="card-grid">   ← for featured/card roles
            <!-- SECTION:first-file.md -->
            <!-- SECTION:second-file.md -->
          </div>
          <div class="card-compact-grid">   ← for compact roles only
            <!-- SECTION:compact-file.md -->
          </div>
        </section>
    • Footer
- CSS classes to define (section generator will use them):
    .card-featured   full-width, visible border, title 1.1rem
    .card-standard   2-col grid card, title 1rem
    .card-compact    dense 3-col row, title 0.85rem
    .tag             small pill label
- Output ONLY the HTML — no card content whatsoever, only placeholders"""

_ROLE_CLASS = {"featured": "card-featured", "card": "card-standard", "compact": "card-compact"}

_SECTION_PROMPT = """\
You are a frontend engineer generating one research card for a page.
The page CSS is already defined — do NOT add <style> tags or redefine any classes.

FILE: {filename}
CSS CLASS TO USE: {css_class}
DISPLAY ROLE: {role}
  featured  = full card: title, all body paragraphs, key findings list, tags
  card      = standard: title, 1 abstract paragraph, 3-5 key findings bullets, tags
  compact   = minimal: title + one sentence only, no bullets, no body

CONTENT:
{content}

INSTRUCTIONS:
- Output ONLY: <article class="{css_class}"> ... </article>
- No <section> wrapper, no <html>, no <style>
- Always include: <h3 class="card-title">title</h3>
- For "featured": include all sections of content as <p> and <ul> elements
- For "card": include abstract as <p> + key findings as <ul> (3-5 bullets) + .tag pills
- For "compact": include only <h3 class="card-title"> + one <p class="card-abstract"> sentence
- Output ONLY the <article>...</article> HTML"""


def _read_content_files(content_dir: str) -> list[tuple[str, str]]:
    """Return list of (filename, content) pairs for all .md files in content_dir."""
    p = Path(content_dir).expanduser()
    if not p.exists():
        raise ValueError(f"content directory not found: {content_dir}")
    files = sorted(p.glob("*.md"))
    if not files:
        raise ValueError(f"no .md files found in {content_dir}")
    pairs = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            pairs.append((f.name, text))
        except Exception:
            pass
    print(f"  [build-page] loaded {len(pairs)} content file(s) from {p}")
    return pairs


_SECTION_CHARS_MAX = 5_000   # per-section content cap (fits in 8k ctx with prompt overhead)
_DESIGN_SYSTEM_SHELL_MAX = 6_000


def _clean_html(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:html)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw


def _extract_summary(name: str, content: str, max_chars: int = 400) -> str:
    """Pull title (first H1/H2) + opening paragraph from a markdown file."""
    lines = content.splitlines()
    title = name
    body_lines: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("#") and title == name:
            title = stripped.lstrip("#").strip()
        elif stripped and not stripped.startswith("#") and len(body_lines) < 4:
            body_lines.append(stripped)
    body = " ".join(body_lines)[:max_chars]
    return f"{title} — {body}"


def generate_page(
    design_system: str,
    content_dir: str,
    model: str,
    vision_model: str,
    output_path: str,
    refine_iterations: int = 0,
    original_screenshots: list[str] | None = None,
    run_id: str = "",
) -> str:
    """
    Three-pass page generation:
      1. Analysis  — cluster files by topic, assign display roles (featured/card/compact)
      2. Shell     — HTML structure from the cluster plan, one placeholder per file
      3. Sections  — one LLM call per file, role-aware card HTML injected into shell
    """
    from harness.inference import chat as _chat

    files = _read_content_files(content_dir)
    ds = design_system[:_DESIGN_SYSTEM_SHELL_MAX]
    file_map = {name: content for name, content in files}

    # ── Pass 1: content analysis → cluster + role plan ───────────────────────
    summaries = "\n".join(
        f"{name}: {_extract_summary(name, content)}"
        for name, content in files
    )
    print(f"  [build-page] pass 1 — analysing {len(files)} files...")
    ana_resp = _chat(
        model=model,
        messages=[{"role": "user", "content": _ANALYSIS_PROMPT.format(summaries=summaries)}],
        options={"temperature": 0.0, "num_predict": 2048},
    )
    ana_raw = ana_resp["message"]["content"].strip()
    ana_raw = re.sub(r"<think>.*?</think>", "", ana_raw, flags=re.DOTALL).strip()
    ana_raw = re.sub(r"^```(?:json)?\s*", "", ana_raw)
    ana_raw = re.sub(r"\s*```$", "", ana_raw)
    try:
        structure = json.loads(ana_raw)
    except Exception as e:
        print(f"  [build-page] analysis JSON parse failed ({e}) — falling back to flat structure")
        structure = {
            "site_title": "Research Review",
            "site_subtitle": "Literature review collection",
            "clusters": [{"name": "All Papers", "slug": "papers", "description": "",
                          "files": [{"name": n, "title": n, "role": "card"} for n, _ in files]}],
        }

    # Build role lookup: filename -> role
    role_map: dict[str, str] = {}
    for cluster in structure.get("clusters", []):
        for f in cluster.get("files", []):
            role_map[f["name"]] = f.get("role", "card")

    # Log the plan
    for cl in structure.get("clusters", []):
        roles = ", ".join(f'{f["name"]}({f.get("role","card")})' for f in cl.get("files", []))
        print(f"  [build-page]   cluster '{cl['name']}': {roles[:120]}")

    # ── Pass 2: shell from plan ───────────────────────────────────────────────
    print("  [build-page] pass 2 — generating structured shell...")
    shell_resp = _chat(
        model=model,
        messages=[{"role": "user", "content": _SHELL_PROMPT.format(
            design_system=ds,
            structure=json.dumps(structure, indent=2)[:3000],
        )}],
        options={"temperature": 0.1, "num_predict": 4096},
    )
    shell = _clean_html(shell_resp["message"]["content"].strip())
    idx = shell.find("<!DOCTYPE")
    if idx == -1:
        idx = shell.find("<html")
    if idx != -1:
        shell = shell[idx:]

    # ── Pass 3: one card per file, injected into shell ────────────────────────
    total = len(files)
    for i, (name, content) in enumerate(files, 1):
        role = role_map.get(name, "card")
        # Role-based content cap: compact needs very little, featured gets more
        cap = {"featured": _SECTION_CHARS_MAX, "card": 3000, "compact": 800}.get(role, 3000)
        if len(content) > cap:
            content = content[:cap] + "\n\n[truncated]"

        css_class = _ROLE_CLASS.get(role, "card-standard")
        max_tok = {"featured": 3072, "card": 1536, "compact": 512}.get(role, 1536)
        print(f"  [build-page] pass 3 [{i}/{total}] {role} ({css_class}): {name}")
        sec_resp = _chat(
            model=model,
            messages=[{"role": "user", "content": _SECTION_PROMPT.format(
                filename=name,
                role=role,
                css_class=css_class,
                content=content,
            )}],
            options={"temperature": 0.1, "num_predict": max_tok},
        )
        card_html = _clean_html(sec_resp["message"]["content"].strip())
        if card_html and not card_html.lstrip().startswith("<article"):
            card_html = f'<article class="{css_class}">{card_html}</article>'

        placeholder = f"<!-- SECTION:{name} -->"
        if placeholder in shell:
            shell = shell.replace(placeholder, card_html, 1)
        else:
            shell = shell.replace("</main>", f"{card_html}\n</main>", 1)

    # ── Visual refinement ─────────────────────────────────────────────────────
    if refine_iterations > 0 and vision_model:
        shell = _refine_loop(
            shell, design_system, output_path, model, vision_model,
            original_screenshots, refine_iterations, run_id,
        )

    return shell


def _refine_loop(
    html: str,
    design_system: str,
    output_path: str,
    model: str,
    vision_model: str,
    original_screenshots: list[str] | None,
    iterations: int,
    run_id: str,
) -> str:
    """Open the HTML in a browser, screenshot it, compare with original, refine."""
    try:
        from playwright.sync_api import sync_playwright

        from harness.inference import chat as _chat
        from harness.skills.playwright_skill import _take_screenshot
        from harness.vision import extract_image_context
    except ImportError as e:
        print(f"  [build-page] refinement unavailable: {e}")
        return html

    # Write current HTML to a temp file for browsing
    tmp_path = Path(output_path).with_suffix("") / "_refine_tmp.html"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)

    original_desc = ""
    if original_screenshots:
        descs = []
        for sp in original_screenshots[:2]:
            d = extract_image_context(sp, "Describe the visual design: layout, colors, spacing, typography, components.")
            if d:
                descs.append(d)
        original_desc = "\n\n".join(descs)

    for iteration in range(1, iterations + 1):
        print(f"  [build-page] refinement iteration {iteration}/{iterations}...")
        tmp_path.write_text(html, encoding="utf-8")

        _pw_ctx = sync_playwright()
        pw = _pw_ctx.start()
        try:
            browser = pw.chromium.launch(headless=True)
            ctx  = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(f"file:///{tmp_path.as_posix()}", wait_until="domcontentloaded")
            time.sleep(1)
            current_shot = _take_screenshot(page, run_id, iteration, f"refine_{iteration}")
            browser.close()
        finally:
            try:
                _pw_ctx.stop()  # type: ignore[attr-defined]
            except Exception:
                pass

        if not current_shot:
            print("  [build-page] screenshot failed, stopping refinement")
            break

        current_desc = extract_image_context(
            current_shot,
            "Describe the visual design: layout, colors, spacing, typography, components."
        )

        # Ask the model to identify specific differences and fixes
        diff_prompt = (
            f"Compare these two page descriptions and list up to 5 SPECIFIC visual differences "
            f"to fix in the HTML (be precise: wrong color #hex, font-size should be Xpx, etc.).\n\n"
            f"ORIGINAL SITE:\n{original_desc or '(no original screenshots)'}\n\n"
            f"CURRENT PAGE:\n{current_desc}\n\n"
            f"List only actionable differences. If they look equivalent, write: NO CHANGES NEEDED."
        )
        diff_resp = _chat(
            model=model,
            messages=[{"role": "user", "content": diff_prompt}],
            options={"temperature": 0.0, "num_predict": 512},
        )
        differences = diff_resp["message"]["content"].strip()
        differences = re.sub(r"<think>.*?</think>", "", differences, flags=re.DOTALL).strip()

        if "NO CHANGES NEEDED" in differences.upper():
            print(f"  [build-page] refinement converged at iteration {iteration}")
            break

        print(f"  [build-page] differences: {differences[:200]}...")

        refine_resp = _chat(
            model=model,
            messages=[{"role": "user", "content": _REFINE_PROMPT.format(
                original_desc=original_desc or "(no original screenshots)",
                current_desc=current_desc,
                differences=differences,
                html=html[:24_000],
            )}],
            options={"temperature": 0.1, "num_predict": 16384},
        )
        new_html = refine_resp["message"]["content"].strip()
        new_html = re.sub(r"<think>.*?</think>", "", new_html, flags=re.DOTALL).strip()
        new_html = re.sub(r"^```(?:html)?\s*", "", new_html)
        new_html = re.sub(r"\s*```$", "", new_html)
        idx = new_html.find("<!DOCTYPE")
        if idx == -1:
            idx = new_html.find("<html")
        if idx != -1:
            new_html = new_html[idx:]
        if new_html.startswith("<"):
            html = new_html

    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass

    return html


# ---------------------------------------------------------------------------
# Task parser
# ---------------------------------------------------------------------------

def parse_site_task(task: str) -> dict:
    """
    Parse /design, /build-page, or /site task strings.

    Returns dict with keys: mode, url, content_dir, output_path, refine_iterations.

    /design https://vercel.com save to design.md
    /build-page design.md from content/ save to index.html
    /site https://stripe.com from content/ save to site/index.html [--refine N]
    """
    task = re.sub(r"^/(design|build-page|site)\s*", "", task.strip(), flags=re.IGNORECASE).strip()

    # Refine iterations
    refine = 0
    rm = re.search(r"--refine\s+(\d+)", task, re.IGNORECASE)
    if rm:
        refine = int(rm.group(1))
        task = task[:rm.start()].strip() + task[rm.end():].strip()

    # Output path
    output_path = None
    om = re.search(r"\bsave\s+to\s+(\S+)", task, re.IGNORECASE)
    if om:
        output_path = os.path.expanduser(om.group(1))
        task = task[:om.start()].strip() + task[om.end():].strip()

    # Content dir: "from <dir>"
    content_dir = None
    fm = re.search(r"\bfrom\s+(\S+)", task, re.IGNORECASE)
    if fm:
        content_dir = os.path.expanduser(fm.group(1))
        task = task[:fm.start()].strip() + task[fm.end():].strip()

    task = task.strip()

    # .md file present → build-page involved (check BEFORE URL to avoid misclassification)
    md_m = re.search(r"(\S+\.md)", task)
    design_system_path = md_m.group(1) if md_m else None

    # URL present → design extraction involved
    # Only use bare-domain heuristic when no .md file was found (avoids matching e.g. "design.md" as a URL)
    url = None
    url_m = re.match(r"(https?://\S+)", task)
    if url_m:
        url = url_m.group(1)
    elif not design_system_path:
        bare_m = re.match(r"(\S+\.\S{2,5}(?:/\S*)?)", task)
        if bare_m:
            cand = bare_m.group(1)
            if not re.search(r"\.(md|txt|json|html|htm|css|js|py)(?:[/?#]|$)", cand, re.IGNORECASE):
                url = "https://" + cand

    if url and content_dir:
        mode = "site"
    elif url:
        mode = "design"
    elif design_system_path or content_dir:
        mode = "build-page"
    else:
        raise ValueError(
            "Cannot parse task — expected a URL (/design or /site) or a .md file + content dir (/build-page). "
            "Examples:\n"
            "  oh /design https://vercel.com save to design.md\n"
            "  oh /build-page design.md from content/ save to index.html\n"
            "  oh /site https://stripe.com from content/ save to index.html"
        )

    return {
        "mode":                mode,
        "url":                 url,
        "design_system_path":  design_system_path,
        "content_dir":         content_dir,
        "output_path":         output_path,
        "refine_iterations":   refine,
    }
