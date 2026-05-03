"""Load slide content from a URL, folder of .md files, or PDF."""
from __future__ import annotations

import time
from pathlib import Path

_EXTRACT_JS = """
() => {
    const sections = [];
    let cur = { heading: document.querySelector('h1')?.textContent?.trim() || document.title, paragraphs: [], level: 'h1' };

    const walk = el => {
        const tag = el.tagName?.toLowerCase();
        if (!tag) return;
        if (['h2','h3','h4'].includes(tag)) {
            if (cur.paragraphs.length) sections.push(cur);
            cur = { heading: el.textContent.trim(), paragraphs: [], level: tag };
        } else if (['p','li'].includes(tag)) {
            const t = el.textContent.trim();
            if (t.length > 20) cur.paragraphs.push(t);
        } else if (tag === 'blockquote') {
            cur.paragraphs.push('> ' + el.textContent.trim());
        }
    };

    const root = document.querySelector('main, article, .content, #content') || document.body;
    root.querySelectorAll('h2,h3,h4,p,li,blockquote').forEach(walk);
    sections.push(cur);

    return {
        title: document.querySelector('h1')?.textContent?.trim() || document.title,
        url: location.href,
        sections: sections.filter(s => s.paragraphs.length > 0).slice(0, 30),
    };
}
"""


def _sections_to_markdown(data: dict) -> str:
    lines = [f"# {data['title']}", ""]
    for sec in data.get("sections", []):
        heading = sec.get("heading", "")
        level   = sec.get("level", "h2")
        prefix  = "##" if level in ("h2", "h3") else "###"
        if heading:
            lines.append(f"{prefix} {heading}")
            lines.append("")
        for para in sec.get("paragraphs", [])[:8]:
            lines.append(para)
            lines.append("")
    return "\n".join(lines)


def _load_url(url: str) -> list[tuple[str, str]]:
    from playwright.sync_api import sync_playwright

    if not url.startswith("http"):
        url = "https://" + url

    _pw_ctx = sync_playwright()
    pw = _pw_ctx.start()
    try:
        browser = pw.chromium.launch(headless=True)
        ctx  = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        page.set_default_timeout(15_000)
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(2)
        data = page.evaluate(_EXTRACT_JS)
        browser.close()
    finally:
        try:
            _pw_ctx.stop()  # type: ignore[attr-defined]
        except Exception:
            pass

    md = _sections_to_markdown(data)
    title = data.get("title", url)
    print(f"  [deck] scraped {len(data.get('sections', []))} sections from {url}")
    return [(title, md)]


def _load_folder(folder: str) -> list[tuple[str, str]]:
    p = Path(folder).expanduser()
    if not p.exists():
        raise ValueError(f"folder not found: {folder}")
    files = sorted(p.glob("*.md")) + sorted(p.glob("*.txt"))
    if not files:
        raise ValueError(f"no .md or .txt files in {folder}")
    pairs = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            pairs.append((f.stem, text))
        except Exception:
            pass
    print(f"  [deck] loaded {len(pairs)} file(s) from {p}")
    return pairs


def _load_pdf(pdf_path: str) -> list[tuple[str, str]]:
    p = Path(pdf_path).expanduser()
    if not p.exists():
        raise ValueError(f"PDF not found: {pdf_path}")
    try:
        from markitdown import MarkItDown
        result = MarkItDown().convert(str(p))
        text = result.text_content
    except ImportError as exc:
        raise RuntimeError("markitdown not installed — pip install markitdown") from exc
    print(f"  [deck] converted PDF ({len(text):,} chars): {p.name}")
    return [(p.stem, text)]


def _load_pdf_url(url: str) -> list[tuple[str, str]]:
    """Convert a PDF URL directly via MarkItDown (handles download internally)."""
    try:
        from markitdown import MarkItDown
        result = MarkItDown().convert(url)
        text = result.text_content
    except ImportError as exc:
        raise RuntimeError("markitdown not installed") from exc
    slug = url.rstrip("/").split("/")[-1].replace(".pdf", "")
    print(f"  [deck] converted PDF URL ({len(text):,} chars): {slug}")
    return [(slug, text)]


def load_content(source: str) -> list[tuple[str, str]]:
    """Auto-detect source type and return list of (name, markdown) pairs."""
    s = source.strip()
    if s.startswith("http://") or s.startswith("https://"):
        # PDF URL — download and convert rather than scraping as a web page
        if s.lower().split("?")[0].endswith(".pdf"):
            return _load_pdf_url(s)
        return _load_url(s)
    p = Path(s).expanduser()
    if p.is_dir():
        return _load_folder(str(p))
    suf = p.suffix.lower()
    if suf == ".pdf":
        return _load_pdf(str(p))
    if suf in (".md", ".txt"):
        text = p.read_text(encoding="utf-8", errors="replace")
        return [(p.stem, text)]
    raise ValueError(
        f"Unrecognized content source: {source!r}\n"
        "Use a URL, folder path, .pdf, or .md file."
    )
