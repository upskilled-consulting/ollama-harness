"""
kg_gen.py — Knowledge graph generator for the harness.

Generates an interactive D3.js knowledge graph from article text using Ollama.
Supports a critique-refine loop to iteratively improve graph quality.

Usage:
    python kg_gen.py "Article text here..."
    python kg_gen.py --file path/to/article.txt
    python kg_gen.py --file article.txt --output graphs/my_kg.html
    python kg_gen.py --file article.txt --refine 2
    python kg_gen.py --nodes 12 --edges 4 --model pi-qwen-32b "text"
    echo "article..." | python kg_gen.py

Environment:
    conda activate ollama-pi
"""

import argparse
import json
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from harness import inference as ollama

MODEL = "pi-qwen-32b"
DEFAULT_NODES = 10
DEFAULT_EDGE_DENSITY = 3
MAX_CHARS = 4000
OUTPUT_DIR = Path(__file__).parent.parent / "eval-output" / "graphs"
TEMPLATE_FILE = "kg_template.html.j2"

GENERATE_PROMPT = """\
You are a knowledge graph expert. Given the article below, extract a knowledge graph that:
- Captures the most important concepts as nodes
- Shows meaningful directed relationships between them as edges
- Uses concise, descriptive labels (≤4 words per label)

Constraints:
- Maximum {num_nodes} nodes
- Maximum {max_edge_density} edges per node (total edges ≤ {max_edges})
- Node colors: distinct light pastel HEX codes (#RRGGBB) that look good with black text

Return ONLY a valid JSON object with this exact structure, nothing else:
{{
  "nodes": [{{"id": 1, "label": "concept", "color": "#FFE4B5"}}, ...],
  "edges": [{{"src": 1, "dst": 2, "label": "relationship"}}, ...]
}}

Article:
{article}
"""

CRITIQUE_PROMPT = """\
Review this knowledge graph generated from the article below.

Current graph:
{graph_json}

Critique it specifically:
1. Missing important concepts (name them)
2. Redundant or vague nodes (name them)
3. Incorrectly directed edges (which ones, and why)
4. Unclear edge labels (which ones)
5. Density issues (too sparse or too dense in which areas)

Article:
{article}

Be specific and brief — list exactly what to add, remove, or change.
"""

REFINE_PROMPT = """\
Refine this knowledge graph based on the critique.

Original graph:
{graph_json}

Critique:
{critique}

Article:
{article}

Apply the critique improvements while keeping what works.
Constraints: max {num_nodes} nodes, max {max_edge_density} edges per node.

Return ONLY a valid JSON object, nothing else:
{{
  "nodes": [{{"id": 1, "label": "concept", "color": "#HEXCODE"}}, ...],
  "edges": [{{"src": 1, "dst": 2, "label": "relationship"}}, ...]
}}
"""


def extract_json(text: str) -> dict:
    """Extract and parse JSON from model output, handling markdown code blocks."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try code block extraction
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in:\n{text[:400]}")


def validate_graph(data: dict) -> dict:
    """Validate and normalize graph structure. Returns cleaned data or raises."""
    if not isinstance(data, dict):
        raise ValueError("Graph data is not a dict")
    if "nodes" not in data or "edges" not in data:
        raise ValueError(f"Missing 'nodes' or 'edges'. Keys: {list(data.keys())}")

    node_ids = {n["id"] for n in data["nodes"]}
    # Drop edges referencing unknown node ids
    valid_edges = [e for e in data["edges"] if e["src"] in node_ids and e["dst"] in node_ids]
    dropped = len(data["edges"]) - len(valid_edges)
    if dropped:
        print(f"  [kg_gen] dropped {dropped} edge(s) with unknown node ids")
    data["edges"] = valid_edges
    return data


def generate_kg(article: str, model: str, num_nodes: int, max_edge_density: int) -> dict:
    """Call Ollama to generate a knowledge graph JSON."""
    max_edges = num_nodes * max_edge_density
    prompt = GENERATE_PROMPT.format(
        num_nodes=num_nodes,
        max_edge_density=max_edge_density,
        max_edges=max_edges,
        article=article,
    )

    for attempt in range(3):
        if attempt > 0:
            print(f"  [kg_gen] retry attempt {attempt + 1}...")
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.3},
        )
        text = response["message"]["content"]
        try:
            data = extract_json(text)
            data = validate_graph(data)
            print(f"  [kg_gen] generated {len(data['nodes'])} nodes, {len(data['edges'])} edges")
            return data
        except (ValueError, KeyError) as e:
            print(f"  [kg_gen] parse error (attempt {attempt + 1}): {e}")

    raise RuntimeError("Failed to generate valid KG JSON after 3 attempts")


def critique_kg(article: str, graph_data: dict, model: str) -> str:
    """Ask the model to critique the current graph."""
    print("  [kg_gen] critiquing...")
    prompt = CRITIQUE_PROMPT.format(
        graph_json=json.dumps(graph_data, indent=2),
        article=article,
    )
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.3},
    )
    critique = response["message"]["content"].strip()
    # Print first 150 chars as preview
    preview = critique[:150].replace("\n", " ")
    print(f"  [kg_gen] critique preview: {preview}...")
    return critique


def refine_kg(article: str, graph_data: dict, critique: str, model: str, num_nodes: int, max_edge_density: int) -> dict:
    """Refine the graph based on critique."""
    print("  [kg_gen] refining...")
    prompt = REFINE_PROMPT.format(
        graph_json=json.dumps(graph_data, indent=2),
        critique=critique,
        article=article,
        num_nodes=num_nodes,
        max_edge_density=max_edge_density,
    )
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0.2},
    )
    text = response["message"]["content"]
    data = extract_json(text)
    data = validate_graph(data)
    print(f"  [kg_gen] refined: {len(data['nodes'])} nodes, {len(data['edges'])} edges")
    return data


def screenshot_kg(html_path: Path, output_path: Path = None) -> Path:
    """
    Render the KG HTML in a headless Chromium browser via Playwright and save a PNG screenshot.

    Waits for the D3 force simulation and zoom-to-fit transition to complete
    (signalled by `data-kg-ready` on <body>) before capturing.

    Requires:
        pip install playwright
        playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed — run: pip install playwright && playwright install chromium"
        )

    if output_path is None:
        output_path = html_path.with_suffix(".png")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.goto(html_path.resolve().as_uri())
        # Wait for simulation + zoom-to-fit transition to finish (up to 30s)
        page.wait_for_selector("[data-kg-ready]", timeout=30_000)
        page.screenshot(path=str(output_path))
        browser.close()

    return output_path


def render_html(graph_data: dict, output_path: Path, title: str, model: str, article_snippet: str) -> Path:
    """Render the knowledge graph to a self-contained HTML file via Jinja2."""
    template_path = Path(__file__).parent / TEMPLATE_FILE
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=True,
    )
    template = env.get_template(TEMPLATE_FILE)

    snippet = article_snippet[:200] + ("..." if len(article_snippet) > 200 else "")

    html = template.render(
        graph_json=Markup(json.dumps(graph_data)),
        title=title,
        model=model,
        article_snippet=snippet,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        node_count=len(graph_data["nodes"]),
        edge_count=len(graph_data["edges"]),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate an interactive knowledge graph from article text.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("text", nargs="?", help="Article text (or omit and use --file / stdin)")
    parser.add_argument("--file", "-f", help="Path to article text file")
    parser.add_argument("--output", "-o", help="Output HTML path (default: graphs/kg_<timestamp>.html)")
    parser.add_argument("--nodes", "-n", type=int, default=DEFAULT_NODES,
                        help=f"Max nodes (default: {DEFAULT_NODES})")
    parser.add_argument("--edges", "-e", type=int, default=DEFAULT_EDGE_DENSITY,
                        help=f"Max edges per node (default: {DEFAULT_EDGE_DENSITY})")
    parser.add_argument("--model", "-m", default=MODEL,
                        help=f"Ollama model (default: {MODEL})")
    parser.add_argument("--refine", "-r", type=int, default=0,
                        help="Number of critique-refine cycles (default: 0)")
    parser.add_argument("--title", "-t", default="Knowledge Graph",
                        help="Graph title shown in the UI")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't auto-open in browser after rendering")
    parser.add_argument("--screenshot", "-s", action="store_true",
                        help="Take a PNG screenshot via Playwright headless Chromium")
    args = parser.parse_args()

    # Load article text
    if args.file:
        article = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        article = args.text
    elif not sys.stdin.isatty():
        article = sys.stdin.read()
    else:
        parser.print_help()
        sys.exit(1)

    if len(article) > MAX_CHARS:
        print(f"  [kg_gen] truncating article from {len(article)} to {MAX_CHARS} chars")
        article = article[:MAX_CHARS]

    # Output path
    if args.output:
        output_path = Path(args.output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"kg_{ts}.html"

    print(f"\n[kg_gen] model={args.model}  nodes={args.nodes}  edge_density={args.edges}  refine={args.refine}\n")

    # Generate
    print("[turn 1] generating knowledge graph...")
    graph_data = generate_kg(article, args.model, args.nodes, args.edges)

    # Critique-refine loop
    for i in range(args.refine):
        print(f"\n[refine {i + 1}/{args.refine}]")
        critique = critique_kg(article, graph_data, args.model)
        graph_data = refine_kg(article, graph_data, critique, args.model, args.nodes, args.edges)

    # Render
    print("\n[turn 2] rendering HTML...")
    output_path = render_html(graph_data, output_path, args.title, args.model, article)

    size_kb = output_path.stat().st_size // 1024
    print(f"\n[done] {output_path.resolve()}")
    print(f"       {len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges, {size_kb} KB")

    if args.screenshot:
        print("\n[screenshot] launching headless Chromium...")
        try:
            shot_path = screenshot_kg(output_path)
            print(f"[screenshot] saved: {shot_path.resolve()}")
            print(f"             markdown: ![{args.title}]({shot_path.resolve().as_posix()})")
        except RuntimeError as e:
            print(f"[screenshot] skipped — {e}")

    if not args.no_open:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
