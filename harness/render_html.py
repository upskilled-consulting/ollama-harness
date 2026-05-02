"""
harness/render_html.py — deterministic markdown → HTML renderer with fixed design system.

Usage:
    python -m harness.render_html <output_dir>              # render all .md files in dir
    python -m harness.render_html <output_dir> --title "My Report"
    python -m harness.render_html <output_dir> --subtitle "A subtitle"
    python -m harness.render_html <output_dir> --no-individual   # landing page only

Produces:
    <output_dir>/index.html          — landing page with card grid
    <output_dir>/<slug>.html         — individual report pages (one per .md)

Design system:
    Background:  #0d1117
    Surface:     #161b22
    Border:      #30363d
    Accent:      #58a6ff
    Text:        #e6edf3
    Muted:       #8b949e
    Font:        system-ui, -apple-system, "Segoe UI", sans-serif
    Code font:   "SFMono-Regular", Consolas, monospace
"""

import argparse
import html as _html
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import markdown as _md_lib
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    print("[warn] 'markdown' package not found — pip install markdown. Falling back to basic converter.")

try:
    from jinja2 import BaseLoader, Environment
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    print("[warn] 'jinja2' package not found — pip install jinja2. Falling back to string templates.")


# ---------------------------------------------------------------------------
# Design system constants
# ---------------------------------------------------------------------------

DS = {
    "bg":        "#0d1117",
    "surface":   "#161b22",
    "surface2":  "#1c2128",
    "border":    "#30363d",
    "accent":    "#58a6ff",
    "accent2":   "#79c0ff",
    "text":      "#e6edf3",
    "muted":     "#8b949e",
    "success":   "#3fb950",
    "warn":      "#d29922",
    "danger":    "#f85149",
    "font":      "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    "mono":      "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
}

CSS = f"""
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
    background: {DS['bg']};
    color: {DS['text']};
    font-family: {DS['font']};
    font-size: 15px;
    line-height: 1.65;
    min-height: 100vh;
}}

a {{ color: {DS['accent']}; text-decoration: none; }}
a:hover {{ color: {DS['accent2']}; text-decoration: underline; }}

/* ── Layout ── */
.site-header {{
    background: {DS['surface']};
    border-bottom: 1px solid {DS['border']};
    padding: 0 2rem;
}}
.site-header-inner {{
    max-width: 1100px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 56px;
}}
.site-logo {{
    font-family: {DS['mono']};
    font-size: 0.85rem;
    color: {DS['muted']};
    letter-spacing: 0.05em;
}}
.site-logo span {{ color: {DS['accent']}; }}

.hero {{
    background: linear-gradient(180deg, {DS['surface']} 0%, {DS['bg']} 100%);
    border-bottom: 1px solid {DS['border']};
    padding: 4rem 2rem 3rem;
    text-align: center;
}}
.hero h1 {{
    font-size: clamp(1.6rem, 4vw, 2.4rem);
    font-weight: 700;
    color: {DS['text']};
    margin-bottom: 0.75rem;
    letter-spacing: -0.02em;
}}
.hero .subtitle {{
    color: {DS['muted']};
    font-size: 1rem;
    max-width: 640px;
    margin: 0 auto 1.5rem;
}}
.hero .meta {{
    font-family: {DS['mono']};
    font-size: 0.78rem;
    color: {DS['muted']};
}}
.hero .meta span {{ color: {DS['accent']}; }}

.container {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 2.5rem 2rem;
}}

/* ── Card grid (landing) ── */
.card-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 1.25rem;
    margin-bottom: 3rem;
}}
.card {{
    background: {DS['surface']};
    border: 1px solid {DS['border']};
    border-radius: 8px;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    transition: border-color 0.15s, transform 0.15s;
    cursor: pointer;
}}
.card:hover {{
    border-color: {DS['accent']};
    transform: translateY(-2px);
}}
.card-num {{
    font-family: {DS['mono']};
    font-size: 0.72rem;
    color: {DS['accent']};
    letter-spacing: 0.08em;
    margin-bottom: 0.5rem;
    text-transform: uppercase;
}}
.card h3 {{
    font-size: 1rem;
    font-weight: 600;
    color: {DS['text']};
    margin-bottom: 0.6rem;
    line-height: 1.35;
}}
.card .synopsis {{
    color: {DS['muted']};
    font-size: 0.875rem;
    line-height: 1.55;
    flex: 1;
    margin-bottom: 1rem;
}}
.card .preview {{
    display: none;
    background: {DS['surface2']};
    border: 1px solid {DS['border']};
    border-radius: 4px;
    padding: 0.75rem;
    font-size: 0.8rem;
    color: {DS['muted']};
    line-height: 1.5;
    font-family: {DS['mono']};
    white-space: pre-wrap;
    word-break: break-word;
    margin-bottom: 0.75rem;
    max-height: 200px;
    overflow-y: auto;
}}
.card.expanded .preview {{ display: block; }}
.card-footer {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: auto;
}}
.card-link {{
    font-size: 0.8rem;
    font-family: {DS['mono']};
    color: {DS['accent']};
}}
.card-toggle {{
    font-size: 0.75rem;
    color: {DS['muted']};
    background: none;
    border: 1px solid {DS['border']};
    border-radius: 4px;
    padding: 0.2rem 0.5rem;
    cursor: pointer;
    color: {DS['muted']};
    font-family: {DS['font']};
    transition: border-color 0.15s;
}}
.card-toggle:hover {{ border-color: {DS['accent']}; color: {DS['text']}; }}

/* ── Report page ── */
.report-nav {{
    background: {DS['surface']};
    border-bottom: 1px solid {DS['border']};
    padding: 0.75rem 2rem;
    font-size: 0.85rem;
    color: {DS['muted']};
}}
.report-nav a {{ color: {DS['accent']}; }}

.report-body {{
    max-width: 820px;
    margin: 0 auto;
    padding: 2.5rem 2rem 4rem;
}}
.report-body h1 {{ font-size: 1.75rem; font-weight: 700; margin-bottom: 1rem; border-bottom: 1px solid {DS['border']}; padding-bottom: 0.5rem; }}
.report-body h2 {{ font-size: 1.2rem; font-weight: 600; margin: 2rem 0 0.6rem; color: {DS['accent2']}; }}
.report-body h3 {{ font-size: 1rem; font-weight: 600; margin: 1.5rem 0 0.4rem; color: {DS['text']}; }}
.report-body p {{ margin-bottom: 1rem; color: {DS['muted']}; }}
.report-body ul, .report-body ol {{ margin: 0 0 1rem 1.5rem; color: {DS['muted']}; }}
.report-body li {{ margin-bottom: 0.3rem; }}
.report-body strong {{ color: {DS['text']}; font-weight: 600; }}
.report-body em {{ color: {DS['accent2']}; font-style: italic; }}
.report-body code {{
    font-family: {DS['mono']};
    font-size: 0.85em;
    background: {DS['surface2']};
    border: 1px solid {DS['border']};
    border-radius: 3px;
    padding: 0.1em 0.35em;
    color: {DS['accent2']};
}}
.report-body pre {{
    background: {DS['surface2']};
    border: 1px solid {DS['border']};
    border-radius: 6px;
    padding: 1rem 1.25rem;
    overflow-x: auto;
    margin-bottom: 1.25rem;
}}
.report-body pre code {{
    background: none;
    border: none;
    padding: 0;
    font-size: 0.82rem;
    color: {DS['text']};
}}
.report-body blockquote {{
    border-left: 3px solid {DS['accent']};
    padding-left: 1rem;
    color: {DS['muted']};
    margin-bottom: 1rem;
}}
.report-body table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1.25rem;
    font-size: 0.875rem;
}}
.report-body th {{
    background: {DS['surface2']};
    border: 1px solid {DS['border']};
    padding: 0.5rem 0.75rem;
    text-align: left;
    color: {DS['text']};
    font-weight: 600;
}}
.report-body td {{
    border: 1px solid {DS['border']};
    padding: 0.45rem 0.75rem;
    color: {DS['muted']};
}}
.report-body tr:nth-child(even) td {{ background: {DS['surface2']}; }}
.score-badge {{
    display: inline-block;
    font-family: {DS['mono']};
    font-size: 0.75rem;
    background: {DS['surface2']};
    border: 1px solid {DS['border']};
    border-radius: 4px;
    padding: 0.1rem 0.4rem;
    color: {DS['accent']};
    margin-left: 0.5rem;
}}

/* ── Footer ── */
.site-footer {{
    border-top: 1px solid {DS['border']};
    padding: 2rem;
    text-align: center;
    font-size: 0.8rem;
    color: {DS['muted']};
    font-family: {DS['mono']};
}}
.site-footer span {{ color: {DS['accent']}; }}
"""

LANDING_JS = """
document.querySelectorAll('.card').forEach(card => {
    const btn = card.querySelector('.card-toggle');
    if (!btn) return;
    btn.addEventListener('click', e => {
        e.stopPropagation();
        card.classList.toggle('expanded');
        btn.textContent = card.classList.contains('expanded') ? '▲ collapse' : '▼ preview';
    });
    card.addEventListener('click', () => {
        const link = card.querySelector('.card-link');
        if (link) window.location.href = link.href;
    });
});
"""


# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------

def md_to_html(text: str) -> str:
    if MARKDOWN_AVAILABLE:
        return _md_lib.markdown(
            text,
            extensions=["fenced_code", "tables", "toc", "attr_list"],
        )
    # Minimal fallback — handles headings, bold, code fences, paragraphs
    lines = text.splitlines()
    out = []
    in_pre = False
    for line in lines:
        if line.startswith("```"):
            if in_pre:
                out.append("</code></pre>")
                in_pre = False
            else:
                lang = line[3:].strip()
                cls = f' class="language-{lang}"' if lang else ""
                out.append(f"<pre><code{cls}>")
                in_pre = True
            continue
        if in_pre:
            out.append(_html.escape(line))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{m.group(2)}</h{lvl}>")
            continue
        if not line.strip():
            out.append("<br>")
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)
        out.append(f"<p>{line}</p>")
    return "\n".join(out)


def md_plain_preview(text: str, max_chars: int = 500) -> str:
    """Strip markdown syntax and return plain text preview."""
    text = re.sub(r"```[\s\S]*?```", "[code block]", text)
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def title_from_md(text: str, filename: str) -> str:
    """Extract H1 title from markdown, fall back to filename."""
    m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return filename.replace("-", " ").replace("_", " ").title()


def synopsis_from_md(text: str, max_chars: int = 220) -> str:
    """Extract first non-heading paragraph as synopsis."""
    lines = text.splitlines()
    para_lines = []
    for line in lines:
        if line.startswith("#"):
            if para_lines:
                break
            continue
        if line.strip():
            para_lines.append(line.strip())
        elif para_lines:
            break
    synopsis = " ".join(para_lines).strip()
    synopsis = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", synopsis)
    synopsis = re.sub(r"`(.+?)`", r"\1", synopsis)
    if len(synopsis) > max_chars:
        synopsis = synopsis[:max_chars].rsplit(" ", 1)[0] + "…"
    return synopsis or "See full report for details."


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

LANDING_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>{{ css }}</style>
</head>
<body>
<header class="site-header">
  <div class="site-header-inner">
    <div class="site-logo">harness<span>/</span>engineering</div>
    <div class="site-logo">{{ report_count }} reports &mdash; {{ date }}</div>
  </div>
</header>

<div class="hero">
  <h1>{{ title }}</h1>
  {% if subtitle %}<p class="subtitle">{{ subtitle }}</p>{% endif %}
  <div class="meta">Generated autonomously &mdash; <span>local LLMs, no cloud APIs</span></div>
</div>

<div class="container">
  <div class="card-grid">
  {% for r in reports %}
    <div class="card" data-slug="{{ r.slug }}">
      <div class="card-num">{{ "%02d"|format(loop.index) }} / {{ "%02d"|format(reports|length) }}</div>
      <h3>{{ r.title }}</h3>
      <p class="synopsis">{{ r.synopsis }}</p>
      <div class="preview">{{ r.preview }}</div>
      <div class="card-footer">
        <a class="card-link" href="{{ r.slug }}.html" onclick="event.stopPropagation()">
          open report &rarr;
        </a>
        <button class="card-toggle">&#9660; preview</button>
      </div>
    </div>
  {% endfor %}
  </div>
</div>

<footer class="site-footer">
  Generated by <span>harness-engineering</span> &mdash; local LLM pipeline &mdash; {{ date }}
</footer>
<script>{{ js }}</script>
</body>
</html>
"""

REPORT_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} &mdash; harness/engineering</title>
<style>{{ css }}</style>
</head>
<body>
<header class="site-header">
  <div class="site-header-inner">
    <div class="site-logo">harness<span>/</span>engineering</div>
    <div class="site-logo">{{ date }}</div>
  </div>
</header>

<div class="report-nav">
  <a href="index.html">&larr; back to index</a>
  &nbsp;&mdash;&nbsp; {{ title }}
</div>

<div class="report-body">
{{ body_html }}
</div>

<footer class="site-footer">
  Generated by <span>harness-engineering</span> &mdash; local LLM pipeline
</footer>
</body>
</html>
"""


def _render(template_str: str, **ctx) -> str:
    if JINJA2_AVAILABLE:
        env = Environment(loader=BaseLoader())
        tmpl = env.from_string(template_str)
        return tmpl.render(**ctx)
    result = template_str
    for k, v in ctx.items():
        result = result.replace("{{ " + k + " }}", str(v))
        result = result.replace("{{" + k + "}}", str(v))
    return result


# ---------------------------------------------------------------------------
# Main rendering logic
# ---------------------------------------------------------------------------

def render_dir(
    out_dir: Path,
    title: str = "Research Output",
    subtitle: str = "",
    individual: bool = True,
):
    md_files = sorted(f for f in out_dir.glob("*.md") if f.name != "index.md")
    if not md_files:
        print(f"[render] no .md files found in {out_dir}")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    reports = []

    for i, md_file in enumerate(md_files, 1):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        slug = md_file.stem
        r_title = title_from_md(text, slug)
        r_synopsis = synopsis_from_md(text)
        r_preview = md_plain_preview(text, max_chars=500)
        body_html = md_to_html(text)

        reports.append({
            "slug": slug,
            "title": r_title,
            "synopsis": r_synopsis,
            "preview": r_preview,
            "body_html": body_html,
            "source": md_file.name,
        })

        if individual:
            report_html = _render(
                REPORT_TEMPLATE,
                css=CSS,
                title=r_title,
                date=date_str,
                body_html=body_html,
            )
            out_path = out_dir / f"{slug}.html"
            out_path.write_text(report_html, encoding="utf-8")
            print(f"  [render] {out_path.name}  ({len(report_html):,} bytes)")

    landing_html = _render(
        LANDING_TEMPLATE,
        css=CSS,
        js=LANDING_JS,
        title=title,
        subtitle=subtitle,
        date=date_str,
        report_count=len(reports),
        reports=reports,
    )
    index_path = out_dir / "index.html"
    index_path.write_text(landing_html, encoding="utf-8")
    print(f"  [render] index.html  ({len(landing_html):,} bytes)  ← landing page")
    print(f"  [render] done — {len(reports)} reports + index")
    return index_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Render markdown reports to styled HTML")
    parser.add_argument("output_dir", help="Directory containing .md report files")
    parser.add_argument("--title", default="Research Output", help="Landing page title")
    parser.add_argument("--subtitle", default="", help="Landing page subtitle")
    parser.add_argument("--no-individual", action="store_true", help="Skip individual report pages")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    if not out_dir.is_dir():
        print(f"[error] not a directory: {out_dir}")
        sys.exit(1)

    print(f"[render] rendering {out_dir} ...")
    render_dir(
        out_dir,
        title=args.title,
        subtitle=args.subtitle,
        individual=not args.no_individual,
    )


if __name__ == "__main__":
    main()
