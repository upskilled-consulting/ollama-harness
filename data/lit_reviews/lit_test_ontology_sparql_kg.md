# Literature Review: ontology sparql knowledge graph

*Generated 2026-04-29 16:07 · 1 fetched · 1 annotated*

---

## Overview

The literature review on knowledge graph query generation reveals a consistent trend towards using large language models to enhance knowledge graph exploration through SPARQL queries. The technique known as GRASP stands out for its effectiveness in zero-shot settings and has demonstrated state-of-the-art performance on Wikidata and competitive results on Freebase, showcasing its adaptability across diverse knowledge graph domains.

---

## 1. Knowledge Graph Query Generation

The common theme among these papers is the application of large language models for knowledge graph exploration using strategic SPARQL queries, with GRASP being a notable technique that excels in zero-shot settings across various benchmarks. These studies collectively demonstrate the effectiveness of GRASP in achieving state-of-the-art results on Wikidata and competitive performance on Freebase, highlighting its versatility in different knowledge graph domains.


### GRASP: Generic Reasoning And SPARQL Generation across Knowledge Graphs

*[2507.08107v2](https://arxiv.org/abs/2507.08107v2) · 2025-07-10 · score 9.7/10*

**Topic**: The paper introduces GRASP, a method for generating SPARQL queries from natural language or keyword queries using large language models without requiring fine-tuning. It leverages the model to explore knowledge graphs by strategically executing SPARQL queries to find relevant IRIs and literals.

**Motivation**: The authors aim to provide a generic approach for SPARQL generation that avoids the need for dataset-specific fine-tuning, relying instead on the exploratory capabilities of large language models.

**Contribution**: GRASP utilizes large language models to explore RDF knowledge graphs by executing strategic SPARQL queries and searching for relevant IRIs and literals. This zero-shot approach is evaluated across various benchmarks and model types, demonstrating strong performance without fine-tuning.

**Evidence**: On Wikidata, the method achieves state-of-the-art results on multiple benchmarks in a zero-shot setting. On Freebase, it performs close to the best few-shot methods, and it also performs well overall on other less commonly evaluated knowledge graphs and benchmarks.

**Narrow impact**: The approach enables effective SPARQL generation across diverse knowledge graphs and language models, offering a viable alternative to fine-tuned methods by leveraging zero-shot exploration capabilities.

**Broad impact**: By providing a generic, fine-tuning-free solution for interacting with knowledge graphs, this work facilitates broader access to structured data through natural language queries, potentially lowering the barrier for using semantic web resources.

**Limitations**: The text does not report any significant weaknesses or failures; it states that the approach performs well overall on less commonly evaluated knowledge graphs and comes close to the best few-shot methods on Freebase.


---

## Open Questions

- How can the performance of GRASP be further improved when applied to more complex or domain-specific knowledge graphs?
- What are the limitations of large language models in generating accurate SPARQL queries for knowledge graphs with sparse data?
- To what extent can the principles behind GRASP be generalized and applied to other types of graph-based databases beyond knowledge graphs?
- How do different architectural choices in large language models affect the quality of generated SPARQL queries, and which configurations yield the best results?
- What are the ethical implications and biases that might arise from using large language models for query generation in knowledge graphs?

---

## Gap Candidates

Papers heavily cited within this corpus but not yet annotated:

| # | arXiv ID | Cited by |
|---|----------|----------|
| 1 | [2003.02320](https://arxiv.org/abs/2003.02320) | 7 |
| 2 | [2005.11401](https://arxiv.org/abs/2005.11401) | 5 |
| 3 | [1606.06357](https://arxiv.org/abs/1606.06357) | 5 |
| 4 | [1412.6575](https://arxiv.org/abs/1412.6575) | 5 |
| 5 | [1902.10197](https://arxiv.org/abs/1902.10197) | 4 |
| 6 | [1706.03762](https://arxiv.org/abs/1706.03762) | 4 |
| 7 | [1707.01476](https://arxiv.org/abs/1707.01476) | 3 |
| 8 | [1703.06103](https://arxiv.org/abs/1703.06103) | 3 |
| 9 | [2410.21276](https://arxiv.org/abs/2410.21276) | 2 |
| 10 | [2312.17617](https://arxiv.org/abs/2312.17617) | 2 |
| 11 | [2307.03109](https://arxiv.org/abs/2307.03109) | 2 |
| 12 | [2305.04676](https://arxiv.org/abs/2305.04676) | 2 |
| 13 | [1809.08887](https://arxiv.org/abs/1809.08887) | 2 |
| 14 | [2311.09841](https://arxiv.org/abs/2311.09841) | 2 |
| 15 | [2308.11730](https://arxiv.org/abs/2308.11730) | 2 |

---

*Built with [harness-engineering](https://github.com/nickmccarty/ollama-pi-harness) · /lit-review skill*