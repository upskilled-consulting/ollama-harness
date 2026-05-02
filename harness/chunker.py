"""
harness/chunker.py — context extraction for large documents.

Two strategies, selected automatically:

  Structured (≥3 markdown headings)
    Section extraction: finds Abstract, Conclusion, Introduction, Results, etc.
    and assembles them in priority order within a char budget.
    Fast — no model, no embeddings.

  Unstructured (PDFs without headings, long HTML dumps, etc.)
    Chunk retrieval: splits into overlapping character windows, embeds with
    sentence-transformers via an ephemeral ChromaDB collection, retrieves
    the top-K chunks most relevant to the task query, and reassembles in
    original reading order within the budget.

Each chunk/section carries provenance metadata (source, url, page, paragraph,
char_offset, section) embedded as inline tags in the assembled output so the
model can cite specific passages.

Entry point:
    from harness.chunker import extract_paper_context
    context = extract_paper_context(
        text, task="...", budget=12_000,
        source="paper.pdf", url="https://...", page_size=3000,
    )

Used by read_file_context() in agent.py for any file > LARGE_FILE_THRESHOLD chars.
"""

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LARGE_FILE_THRESHOLD = 12_000   # chars — below this, return as-is
DEFAULT_BUDGET       = 12_000   # chars assembled from retrieved content
CHUNK_SIZE           = 600      # chars per chunk before overlap trim
CHUNK_OVERLAP        = 80       # chars of overlap between adjacent chunks
TOP_K                = 20       # candidate chunks to retrieve before budget trim

# Section patterns for structured extraction — priority order
# (label, heading_regex, max_chars_for_this_section)
SECTION_PATTERNS = [
    ("Abstract",     r"(?i)^#+\s*abstract",                                      2_000),
    ("Summary",      r"(?i)^#+\s*summary",                                        1_500),
    ("Conclusion",   r"(?i)^#+\s*conclusions?",                                   2_500),
    ("Introduction", r"(?i)^#+\s*\d*\.?\s*introduction",                         2_500),
    ("Results",      r"(?i)^#+\s*\d*\.?\s*(results?|experiments?|evaluation)",   2_500),
    ("Discussion",   r"(?i)^#+\s*\d*\.?\s*discussion",                           1_500),
    ("Methods",      r"(?i)^#+\s*\d*\.?\s*(methods?|methodology|approach)",      1_500),
    ("Related",      r"(?i)^#+\s*\d*\.?\s*related",                              1_000),
]

SECTION_PRIORITY = ["Abstract", "Summary", "Conclusion", "Introduction",
                    "Results", "Discussion", "Methods", "Related"]


# ---------------------------------------------------------------------------
# Chunk dataclass — provenance carrier
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    text:        str
    source:      str       = ""    # filename or document identifier
    url:         str       = ""    # web URL if applicable
    page:        int | None = None # page number (estimated from page_size hint)
    paragraph:   int       = 0    # paragraph index in original document (count of \\n\\n)
    char_offset: int       = 0    # start position in original text
    section:     str       = ""   # section label (structured extraction only)

    def provenance_tag(self) -> str:
        """Compact inline provenance string embedded in assembled output."""
        parts = []
        if self.source:
            parts.append(f"source:{self.source}")
        if self.url:
            parts.append(f"url:{self.url}")
        if self.page is not None:
            parts.append(f"p.{self.page}")
        if self.paragraph:
            parts.append(f"¶{self.paragraph}")
        if self.section:
            parts.append(f"§{self.section}")
        if self.char_offset:
            parts.append(f"@{self.char_offset:,}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Section extraction (structured documents)
# ---------------------------------------------------------------------------

def _extract_sections(
    text:      str,
    budget:    int,
    source:    str       = "",
    url:       str       = "",
    page_size: int | None = None,
) -> str | None:
    """
    Find named sections and assemble within budget in priority order.
    Returns None if fewer than 2 sections found (fall through to chunk retrieval).
    Provenance tags are embedded in each section header.
    """
    lines      = text.splitlines()
    heading_re = re.compile(r"^#+\s")

    # Precompute char offset for each line
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1   # +1 for the newline

    found: dict[str, Chunk] = {}

    for label, pattern, max_chars in SECTION_PATTERNS:
        for idx, line in enumerate(lines):
            if re.match(pattern, line.strip()):
                chunk_lines: list[str] = []
                for ln in lines[idx:]:
                    if chunk_lines and heading_re.match(ln):
                        break
                    chunk_lines.append(ln)
                char_off  = line_offsets[idx]
                para_idx  = text[:char_off].count("\n\n")
                page      = (char_off // page_size) + 1 if page_size else None
                found[label] = Chunk(
                    text        = "\n".join(chunk_lines)[:max_chars],
                    source      = source,
                    url         = url,
                    page        = page,
                    paragraph   = para_idx,
                    char_offset = char_off,
                    section     = label,
                )
                break

    if len(found) < 2:
        return None

    assembled = []
    remaining = budget
    for label in SECTION_PRIORITY:
        if label not in found or remaining <= 0:
            continue
        chunk = found[label]
        part  = chunk.text[:remaining]
        tag   = chunk.provenance_tag()
        header = f"=== {label}" + (f" [{tag}]" if tag else "") + " ==="
        assembled.append(f"{header}\n{part}")
        remaining -= len(part)

    return "\n\n".join(assembled) if assembled else None


# ---------------------------------------------------------------------------
# Chunk retrieval (unstructured documents)
# ---------------------------------------------------------------------------

def _split_chunks(
    text:       str,
    chunk_size: int       = CHUNK_SIZE,
    overlap:    int       = CHUNK_OVERLAP,
    source:     str       = "",
    url:        str       = "",
    page_size:  int | None = None,
) -> list[Chunk]:
    """
    Split text into overlapping character windows, breaking at sentence/paragraph
    boundaries where possible.  Each Chunk carries full provenance metadata.
    """
    chunks: list[Chunk] = []
    start  = 0
    n      = len(text)

    while start < n:
        end        = min(start + chunk_size, n)
        chunk_text = text[start:end]

        # Try to end at a natural boundary
        if end < n:
            for sep in ("\n\n", ". ", ".\n", "\n"):
                pos = chunk_text.rfind(sep)
                if pos > chunk_size // 2:
                    end        = start + pos + len(sep)
                    chunk_text = text[start:end]
                    break

        stripped = chunk_text.strip()
        if len(stripped) > 30:
            para_idx = text[:start].count("\n\n")
            page     = (start // page_size) + 1 if page_size else None
            chunks.append(Chunk(
                text        = stripped,
                source      = source,
                url         = url,
                page        = page,
                paragraph   = para_idx,
                char_offset = start,
            ))
        start = max(start + 1, end - overlap)

    return chunks


def _chunk_retrieve(
    text:      str,
    query:     str,
    budget:    int        = DEFAULT_BUDGET,
    source:    str        = "",
    url:       str        = "",
    page_size: int | None = None,
) -> str:
    """
    Embed text chunks and retrieve the most query-relevant ones.
    Provenance metadata is stored in ChromaDB and embedded in the assembled output.
    Reassembles in original reading order within budget.
    Falls back to head+tail truncation if ChromaDB is unavailable.
    """
    chunks = _split_chunks(text, source=source, url=url, page_size=page_size)
    if not chunks:
        return text[:budget]

    print(f"  [chunker] {len(chunks)} chunks — retrieving top-{TOP_K} by relevance...")

    try:
        import chromadb
        from harness.memory import _get_chroma_ef

        ef     = _get_chroma_ef()
        client = chromadb.EphemeralClient()
        col    = client.get_or_create_collection(
            name="doc_chunks",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

        metadatas = []
        for c in chunks:
            m: dict = {
                "source":      c.source,
                "url":         c.url,
                "paragraph":   c.paragraph,
                "char_offset": c.char_offset,
                "section":     c.section,
            }
            if c.page is not None:
                m["page"] = c.page
            metadatas.append(m)

        col.upsert(
            ids       = [f"c{i}" for i in range(len(chunks))],
            documents = [c.text for c in chunks],
            metadatas = metadatas,
        )

        n_results = min(TOP_K, len(chunks))
        results   = col.query(
            query_texts = [query],
            n_results   = n_results,
            include     = ["documents", "metadatas"],
        )
        ret_texts = results["documents"][0]
        ret_metas = results["metadatas"][0]

        # Rebuild Chunk objects from retrieval results
        retrieved: list[Chunk] = []
        for doc, meta in zip(ret_texts, ret_metas):
            retrieved.append(Chunk(
                text        = doc,
                source      = meta.get("source", source),
                url         = meta.get("url", url),
                page        = meta.get("page"),
                paragraph   = meta.get("paragraph", 0),
                char_offset = meta.get("char_offset", 0),
                section     = meta.get("section", ""),
            ))

        # Re-sort by original position (preserve reading order)
        retrieved.sort(key=lambda c: c.char_offset)

        # Assemble within budget, embedding provenance tags
        parts     = []
        remaining = budget
        for chunk in retrieved:
            if remaining <= 0:
                break
            tag    = chunk.provenance_tag()
            header = f"[{tag}]" if tag else ""
            body   = chunk.text[:remaining]
            block  = f"{header}\n{body}" if header else body
            parts.append(block)
            remaining -= len(block)

        return "\n\n".join(parts)

    except Exception as e:
        print(f"  [chunker] ChromaDB unavailable ({e}) — head+tail fallback")
        head = text[:budget * 6 // 10]
        tail = text[-(budget * 4 // 10):]
        src_tag = f"[source:{source}]" if source else ""
        return (
            f"{src_tag}\n{head}" if src_tag else head
        ) + "\n\n[...]\n\n" + tail


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_paper_context(
    text:      str,
    task:      str        = "",
    budget:    int        = DEFAULT_BUDGET,
    source:    str        = "",   # filename or document identifier
    url:       str        = "",   # web URL if applicable
    page_size: int | None = None, # chars per page for page-number estimation
) -> str:
    """
    Return the most task-relevant portion of text within budget chars.
    Provenance metadata (source, url, page, paragraph, section, char_offset)
    is embedded inline so the model can attribute specific passages.

    Strategy selection:
      - text ≤ budget              → return as-is (no processing needed)
      - ≥3 markdown headings found → section extraction (fast, preserves structure)
      - otherwise                  → chunk retrieval via ChromaDB embeddings

    Args:
        text:      Full document text (markdown, plain text, markitdown output).
        task:      Task description used as the retrieval query for unstructured docs.
        budget:    Max chars to return.
        source:    Filename or document identifier for provenance tags.
        url:       Web URL of the document if applicable.
        page_size: Estimated chars per page (e.g. 3000) for page number attribution.
                   None = omit page numbers.
    """
    if len(text) <= budget:
        return text

    heading_count = len(re.findall(r"^#+\s", text, re.MULTILINE))

    if heading_count >= 3:
        extracted = _extract_sections(text, budget, source=source, url=url, page_size=page_size)
        if extracted:
            ratio = len(extracted) / len(text) * 100
            print(f"  [chunker] section extraction: {len(extracted):,}/{len(text):,} chars ({ratio:.0f}%)")
            return extracted

    # Unstructured or section extraction yielded < 2 sections
    query = task.strip() or text[:300]
    return _chunk_retrieve(text, query=query, budget=budget, source=source, url=url, page_size=page_size)
