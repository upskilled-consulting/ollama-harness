---
title: Evaluation — Wiggum Loop
introspect: true
---

# Evaluation — Wiggum Loop

The wiggum loop is an evaluate→revise cycle that runs automatically after synthesis unless `--no-wiggum` is passed. Up to `MAX_ROUNDS = 3` rounds run; rounds 1–2 capture ~75% of reachable improvement.

## Pass threshold

`PASS_THRESHOLD = 9.0` — the loop halts early when the composite score meets or exceeds this value. The evaluator's `passed` field in its JSON response uses a lower threshold of `8.0`; these are independent: `passed=true` in the eval JSON does not stop the loop.

## Dimensions and weights

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| `depth` | **0.25** | Concreteness — does each item have a worked example, specific parameter, or mechanism? |
| `relevance` | 0.20 | Does the output address the correct topic and complete the task as specified? |
| `completeness` | 0.20 | Are all required items present? Nothing important missing? |
| `grounded` | 0.15 | Are specific claims traceable to real systems, documented APIs, or published benchmarks? |
| `specificity` | 0.10 | Are claims precise and actionable, not vague and generic? |
| `structure` | 0.10 | Is the document clearly organized and readable? |

**Composite formula:**
```
composite = round(0.20×relevance + 0.20×completeness + 0.25×depth + 0.15×grounded + 0.10×specificity + 0.10×structure, 1)
```

## Depth calibration anchors (most important dimension)

| Score | Meaning |
|-------|---------|
| 3 | Paragraph per item, no example, no mechanism, no numbers — pure definition |
| 5 | 1–2 sentences of explanation but no worked example, no specific threshold, no named tool |
| 6 | Some items have a partial example (names a tool but not how to use it) |
| 7 | Most items have a concrete example OR specific implementation note; at least one still surface-level |
| 8 | Every item has a concrete example AND a mechanism (why it works, what can go wrong); practitioner can act on any section |
| 9 | Every item has a worked example with specific parameters, thresholds, or decisions; expert finds nothing to add |
| 10 | Reserved for genuinely exceptional depth — essentially never awarded |

## Grounded calibration anchors

| Score | Meaning |
|-------|---------|
| 9–10 | Every specific claim names a real system, documented API, or published outcome |
| 7–8 | Most claims grounded; 1–2 plausible but unverifiable specifics |
| 5–6 | Mix of real and invented specifics; at least one code block with undocumented method calls |
| 3–4 | Most specifics generic or hallucinated; code blocks use invented method names |
| 1–2 | Almost all specifics fabricated |

## General scoring rules

- A bullet list of one-liners with no implementation detail: `depth ≤ 5`
- A document covering the topic broadly but omitting 2+ major subtopics: `completeness = 6`
- Claims with no source, number, or named system: `specificity = 5`
- Do not award 9+ on any dimension unless no concrete improvement can be identified
- Language consistency: any non-English characters cap `structure ≤ 3`

## Task-type-specific criteria

The evaluator receives a `task_criteria` block tailored to the task type:

- **enumerated** — output must contain exactly the requested number of items; more or fewer caps score at 5 and forces `passed=false`
- **best_practices** — items must be self-contained, independently actionable recommendations
- **research** — expects synthesis of multiple sources, not just one; requires source attribution
- **email** — evaluated on personalization, tone match, and factual accuracy to the provided contact context

## Hallucination penalty

The wiggum loop runs a pre-evaluation hallucination detector (`_count_stub_blocks`) that identifies code blocks containing ≥2 standalone method calls with names ≥12 characters on objects not in a known-real namespace. Each such block adds up to 2 points of penalty to the composite score (capped). This catches LLM-fabricated API stubs that describe what a function "should" do rather than a real documented call.

## Output normalization

Before evaluation, output is normalized to plain markdown:
- HTML/HTM: rendered with headless Playwright to extract visible text
- PDF, DOCX, PPTX, XLSX: converted via MarkItDown
- Markdown/plain text: read directly

## Evaluator model

Set via `WIGGUM_EVALUATOR_MODEL` or `HARNESS_EVALUATOR_MODEL`. Default: `atla/selene-mini`. The evaluator responds in JSON; a prose fallback parser handles evaluators that ignore the JSON instruction.
