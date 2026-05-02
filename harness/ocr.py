"""
harness/ocr.py — OCR preprocessing fallback for scanned/image-heavy PDFs.

Cascade (in order):
  1. MarkItDown (pdfminer) — current default; caller already runs this
  2. PyMuPDF (fitz) — better two-column / complex-layout extraction, no model cost
  3. llama-server OCR — dedicated OCR model (GLM-OCR, Deepseek-OCR, etc.)
                        via llama-server at LLAMA_OCR_BASE_URL (optional)
  4. Vision model (llama3.2-vision via Ollama) — last-resort for truly scanned pages

Integration point: agent.py read_file_context() calls is_sparse() after
MarkItDown conversion; if sparse, calls ocr_pdf() for a better extraction.

Usage (module):
    from harness.ocr import is_sparse, ocr_pdf
    content = markitdown_result.text_content or ""
    if is_sparse(content, pdf_path):
        content = ocr_pdf(pdf_path, task=task)

Usage (standalone smoke test):
    python -m harness.ocr <path/to/paper.pdf>

Environment variables:
    LLAMA_OCR_BASE_URL   llama-server base URL, e.g. http://localhost:8080
    LLAMA_OCR_MODEL      model name (default: auto-detect from /v1/models)
"""

import base64
import os
import sys

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

LLAMA_OCR_BASE_URL = os.environ.get("LLAMA_OCR_BASE_URL", "").rstrip("/")
VISION_MODEL = "llama3.2-vision"

SPARSE_CHARS_PER_PAGE = 300
SPARSE_ABSOLUTE_FLOOR = 200


def _estimate_page_count(pdf_path: str) -> int:
    """Quick page count via PyMuPDF if available, else rough heuristic from file size."""
    if PYMUPDF_AVAILABLE:
        try:
            with fitz.open(pdf_path) as doc:
                return len(doc)
        except Exception:
            pass
    try:
        size = os.path.getsize(pdf_path)
        return max(1, size // 10_000)
    except OSError:
        return 1


def is_sparse(content: str, pdf_path: str) -> bool:
    """
    Return True if the MarkItDown output looks too sparse to be a good extraction.
    Used to decide whether to attempt OCR fallback.
    """
    chars = len(content.strip())
    if chars < SPARSE_ABSOLUTE_FLOOR:
        return True
    pages = _estimate_page_count(pdf_path)
    return (chars / pages) < SPARSE_CHARS_PER_PAGE


MAX_PAGES = 30


def _extract_pymupdf(pdf_path: str) -> str:
    """
    Extract text from a PDF using PyMuPDF.

    Uses get_text("markdown") which handles multi-column layout, bold/italic
    preservation, and table detection. Falls back to get_text("text") if needed.
    """
    doc = fitz.open(pdf_path)
    pages = list(doc)[:MAX_PAGES]
    blocks = []
    for page in pages:
        try:
            text = page.get_text("markdown")
        except Exception:
            text = page.get_text("text")
        text = text.strip()
        if text:
            blocks.append(text)
    doc.close()
    return "\n\n".join(blocks)


_LLAMA_OCR_PROMPT = "OCR markdown"
OCR_DPI = 150
MAX_OCR_PAGES = 10


def _get_llama_ocr_model(base_url: str) -> str:
    """Query /v1/models to find the loaded model ID, or return 'default'."""
    try:
        import requests as _req
        resp = _req.get(f"{base_url}/v1/models", timeout=3)
        data = resp.json()
        models = data.get("data", [])
        if models:
            return models[0]["id"]
    except Exception:
        pass
    return "default"


def _page_to_b64_png(page) -> str:
    """Render a PyMuPDF page to a base64-encoded PNG."""
    mat = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    return base64.b64encode(pix.tobytes("png")).decode("utf-8")


def _extract_llama_ocr(pdf_path: str) -> str:
    """
    OCR via a dedicated llama-server OCR model (e.g. GLM-OCR-GGUF).

    Uses the OpenAI-compatible /v1/chat/completions endpoint with
    multipart image_url content — the format llama-server expects.
    Requires: LLAMA_OCR_BASE_URL env var set to running llama-server URL.
    Requires: PyMuPDF (for page rendering).
    """
    if not PYMUPDF_AVAILABLE:
        return ""

    import requests as _req

    model_id = _get_llama_ocr_model(LLAMA_OCR_BASE_URL)
    url = f"{LLAMA_OCR_BASE_URL}/v1/chat/completions"

    doc = fitz.open(pdf_path)
    pages = list(doc)[:MAX_OCR_PAGES]
    blocks = []

    for i, page in enumerate(pages, 1):
        print(f"    [ocr:llama] page {i}/{len(pages)}...")
        b64 = _page_to_b64_png(page)
        data_uri = f"data:image/png;base64,{b64}"

        payload = {
            "model": model_id,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": _LLAMA_OCR_PROMPT},
                ],
            }],
            "temperature": 0.1,
            "top_k": 1,
        }

        try:
            resp = _req.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text:
                blocks.append(text)
        except Exception as e:
            print(f"    [ocr:llama] page {i} failed: {e}")

    doc.close()
    return "\n\n".join(blocks)


_OLLAMA_OCR_PROMPT = """\
This is page {page_num} of a research paper PDF. Extract all text content as clean markdown.
Preserve: section headings (## level), paragraph structure, bullet lists, code/math blocks.
Output ONLY the extracted text — no commentary, no page number header."""


def _extract_vision(pdf_path: str, task: str = "") -> str:
    """
    OCR a PDF by rendering each page to an image and sending to llama3.2-vision.
    Used as last-resort fallback when PyMuPDF also yields sparse output and
    llama-server is not configured.
    """
    if not PYMUPDF_AVAILABLE:
        return ""

    from harness import inference as _inf

    doc = fitz.open(pdf_path)
    pages = list(doc)[:MAX_OCR_PAGES]
    blocks = []
    task_hint = f"\nTask context: {task[:200]}" if task else ""

    for i, page in enumerate(pages, 1):
        print(f"    [ocr:vision] page {i}/{len(pages)}...")
        b64 = _page_to_b64_png(page)
        prompt = _OLLAMA_OCR_PROMPT.format(page_num=i) + task_hint
        try:
            response = _inf.chat(
                model=VISION_MODEL,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [b64],
                }],
                options={"temperature": 0.0},
            )
            text = response["message"]["content"].strip()
            if text:
                blocks.append(text)
        except Exception as e:
            print(f"    [ocr:vision] page {i} failed: {e}")

    doc.close()
    return "\n\n".join(blocks)


def ocr_pdf(pdf_path: str, task: str = "", markitdown_content: str = "") -> str:
    """
    Attempt a better text extraction from a PDF that MarkItDown rendered sparsely.

    Cascade:
      1. PyMuPDF — fast, no model cost, handles multi-column layouts
      2. llama-server OCR — dedicated OCR model if LLAMA_OCR_BASE_URL is set
      3. llama3.2-vision via Ollama — last resort for truly scanned pages

    Returns the best extraction found, or the original markitdown_content
    if all backends fail or produce no improvement.
    """
    expanded = os.path.expanduser(pdf_path)
    basename = os.path.basename(expanded)

    if PYMUPDF_AVAILABLE:
        try:
            pymupdf_text = _extract_pymupdf(expanded)
            if pymupdf_text and not is_sparse(pymupdf_text, expanded):
                print(f"  [ocr:pymupdf] {basename} → {len(pymupdf_text)} chars")
                return pymupdf_text
            if pymupdf_text and len(pymupdf_text) > len(markitdown_content) * 1.5:
                print(f"  [ocr:pymupdf] {basename} → {len(pymupdf_text)} chars (partial improvement)")
                return pymupdf_text
            print(f"  [ocr:pymupdf] {basename} still sparse ({len(pymupdf_text)} chars) — trying next backend")
        except Exception as e:
            print(f"  [ocr:pymupdf] {basename} failed: {e} — trying next backend")
    else:
        print("  [ocr] PyMuPDF not available — skipping to model-based OCR")

    if LLAMA_OCR_BASE_URL:
        print(f"  [ocr:llama] {basename} → {LLAMA_OCR_BASE_URL} ({MAX_OCR_PAGES} page(s) max)...")
        try:
            llama_text = _extract_llama_ocr(expanded)
            if llama_text and not is_sparse(llama_text, expanded):
                print(f"  [ocr:llama] {basename} → {len(llama_text)} chars")
                return llama_text
            if llama_text and len(llama_text) > len(markitdown_content):
                print(f"  [ocr:llama] {basename} → {len(llama_text)} chars (partial improvement)")
                return llama_text
            print("  [ocr:llama] still sparse — falling back to vision")
        except Exception as e:
            print(f"  [ocr:llama] failed: {e} — falling back to vision")
    else:
        print("  [ocr] LLAMA_OCR_BASE_URL not set — skipping llama-server backend")

    print(f"  [ocr:vision] {_estimate_page_count(expanded)} page(s) → {VISION_MODEL}...")
    try:
        vision_text = _extract_vision(expanded, task=task)
        if vision_text and len(vision_text) > len(markitdown_content):
            print(f"  [ocr:vision] {basename} → {len(vision_text)} chars")
            return vision_text
    except Exception as e:
        print(f"  [ocr:vision] failed: {e}")

    print(f"  [ocr] all backends exhausted for {basename} — using original MarkItDown output")
    return markitdown_content


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m harness.ocr <path/to/paper.pdf> [task description]")
        print("\nBackends available:")
        print(f"  PyMuPDF:      {'yes' if PYMUPDF_AVAILABLE else 'no (pip install pymupdf)'}")
        print(f"  llama-server: {'yes — ' + LLAMA_OCR_BASE_URL if LLAMA_OCR_BASE_URL else 'no (set LLAMA_OCR_BASE_URL)'}")
        print("  Ollama vision: yes (llama3.2-vision)")
        sys.exit(1)

    path = sys.argv[1]
    task_desc = sys.argv[2] if len(sys.argv) > 2 else ""

    print(f"[ocr] testing on: {path}")
    print(f"[ocr] backends: pymupdf={PYMUPDF_AVAILABLE}  llama-server={bool(LLAMA_OCR_BASE_URL)}  vision=yes")

    try:
        from markitdown import MarkItDown
        md = MarkItDown(enable_plugins=False)
        baseline = md.convert(os.path.expanduser(path)).text_content or ""
        print(f"[ocr] MarkItDown baseline: {len(baseline)} chars")
        sparse = is_sparse(baseline, path)
        print(f"[ocr] sparse={sparse}")
    except Exception as e:
        baseline = ""
        sparse = True
        print(f"[ocr] MarkItDown failed: {e}")

    if sparse:
        result = ocr_pdf(path, task=task_desc, markitdown_content=baseline)
        print(f"\n[ocr] final result: {len(result)} chars")
        print("\n--- first 1000 chars ---")
        print(result[:1000])
    else:
        print("[ocr] not sparse — OCR not needed")
        print(baseline[:500])
