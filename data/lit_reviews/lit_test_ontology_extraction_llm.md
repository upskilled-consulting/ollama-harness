# Literature Review: ontology extraction llm

*Generated 2026-04-29 14:39 · 1 fetched · 1 annotated*

---

## Overview

The cluster on Low-Resource Model Fine-Tuning explores the use of ETLCH, an LLaMA-based model fine-tuned with low-rank adaptation for multi-task structured information extraction. These studies showcase that small-scale models can achieve competitive performance against strong baselines with minimal data and reduced computational costs, emphasizing the potential of such approaches in resource-constrained environments.

---

## 1. Cluster name: Low-Resource Model Fine-Tuning

The cluster of papers focuses on the development and application of ETLCH, an LLaMA-based model fine-tuned with low-rank adaptation for multi-task structured information extraction using minimal data. This technique demonstrates significant outperformance over strong baselines across various evaluation metrics, highlighting the effectiveness of small-scale models in achieving reliable results at reduced computational costs compared to larger architectures.


### Low-Resource Fine-Tuning for Multi-Task Structured Information Extraction with a Billion-Parameter Instruction-Tuned Model

*[2509.08381v1](https://arxiv.org/abs/2509.08381v1) · 2025-09-10 · score 9.7/10*

**Topic**: Low-resource fine-tuning of large language models for multi-task structured information extraction, specifically addressing JSON extraction, knowledge graph extraction, and named entity recognition.

**Motivation**: Deploying large language models for structured data extraction is often impractical for smaller teams due to high computational costs and the difficulty of preparing large, high-quality datasets. Existing instruction-tuning studies predominantly focus on seven-billion-parameter or larger models, leaving a gap in evidence regarding the reliability of much smaller models under low-resource conditions.

**Contribution**: This work presents ETLCH, a billion-parameter LLaMA-based model fine-tuned with low-rank adaptation on only a few hundred to one thousand samples per task. The study demonstrates that this small-scale model outperforms strong baselines across most evaluation metrics, achieving substantial gains even at the lowest data scales.

**Evidence**: Empirical results show that ETLCH outperforms strong baselines across most evaluation metrics, with substantial gains observed even when trained on the lowest data scale. These findings confirm that well-tuned small models can provide reliable structured outputs at a fraction of the computational cost required by larger architectures.

**Narrow impact**: The findings enable cost-effective and reliable information extraction pipelines for resource-constrained environments, such as smaller teams working in financial compliance reporting, legal document analytics, and multilingual knowledge base construction.

**Broad impact**: This work demonstrates that well-tuned small models can deliver stable and accurate structured outputs at a fraction of the computational cost, potentially democratizing access to efficient AI tools for domains where large-scale infrastructure is prohibitive.

**Limitations**: The provided text does not explicitly detail specific weaker results or failure cases for the model, focusing instead on its overall outperformance of baselines and stability across tasks.


---

## Open Questions

- How does the effectiveness of ETLCH vary across different types of structured information extraction tasks?
- What are the limitations of low-rank adaptation when fine-tuning models with extremely limited datasets?
- Can the principles behind ETLCH be effectively applied to other domains or types of data beyond structured information extraction?
- To what extent can the computational efficiency of small-scale models be improved without compromising their performance?
- How does the performance of low-resource models compare to larger architectures in real-world applications, considering factors like robustness and generalizability?

---

## Gap Candidates

Papers heavily cited within this corpus but not yet annotated:

| # | arXiv ID | Cited by |
|---|----------|----------|
| 1 | [2005.14165](https://arxiv.org/abs/2005.14165) | 6 |
| 2 | [2303.08774](https://arxiv.org/abs/2303.08774) | 5 |
| 3 | [2302.13971](https://arxiv.org/abs/2302.13971) | 4 |
| 4 | [2306.05685](https://arxiv.org/abs/2306.05685) | 4 |
| 5 | [2307.09288](https://arxiv.org/abs/2307.09288) | 4 |
| 6 | [1810.04805](https://arxiv.org/abs/1810.04805) | 3 |
| 7 | [2204.02311](https://arxiv.org/abs/2204.02311) | 3 |
| 8 | [2411.15594](https://arxiv.org/abs/2411.15594) | 3 |
| 9 | [2407.21783](https://arxiv.org/abs/2407.21783) | 3 |
| 10 | [2305.17926](https://arxiv.org/abs/2305.17926) | 3 |
| 11 | [2402.06196](https://arxiv.org/abs/2402.06196) | 2 |
| 12 | [2203.02155](https://arxiv.org/abs/2203.02155) | 2 |
| 13 | [2112.09332](https://arxiv.org/abs/2112.09332) | 2 |
| 14 | [2412.15115](https://arxiv.org/abs/2412.15115) | 2 |
| 15 | [2406.12624](https://arxiv.org/abs/2406.12624) | 2 |

---

*Built with [harness-engineering](https://github.com/nickmccarty/ollama-pi-harness) · /lit-review skill*