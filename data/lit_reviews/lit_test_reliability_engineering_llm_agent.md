# Literature Review: reliability engineering llm agent

*Generated 2026-04-29 15:47 · 2 fetched · 2 annotated*

---

## Overview

The literature review on language model systems analysis and LLM inference engine bugs and improvements reveals a focus on the evolution of externalization techniques in language learning models and the challenges associated with their cognitive infrastructure. It underscores the importance of robust external cognitive infrastructure over mere model strength, while also highlighting the prevalent issues in LLM inference engines such as memory leaks and performance degradation. The need for improved testing frameworks and monitoring tools is emphasized to enhance the robustness of these systems.

---

## 1. Language Model Systems Analysis

The reviewed papers collectively explore the evolution of externalization techniques in language learning model (LLM) agents, emphasizing the interplay between memory, skills, protocols, and harness engineering as key components of agent cognition. They highlight the importance of a robust external cognitive infrastructure over mere model strength for practical agent progress, with a focus on self-evolving harnesses and shared agent infrastructure, while acknowledging challenges in evaluation and governance that connect these various aspects of agent development.


### Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering

*[2604.08224v1](https://arxiv.org/abs/2604.08224v1) · 2026-04-09 · score 9.3/10*

**Topic**: The paper examines the shift in large language model (LLM) agent development from relying on internal model weights to organizing runtime infrastructure around externalized cognitive artifacts. It categorizes these artifacts into memory stores, reusable skills, interaction protocols, and harness engineering.

**Motivation**: The authors are motivated by the observation that agent capabilities are increasingly externalized to transform hard cognitive burdens into forms that models can solve more reliably. This perspective leverages the concept of cognitive artifacts to explain why agent infrastructure matters beyond merely adding auxiliary components.

**Contribution**: The paper provides a systems-level framework that traces the historical progression from weights to context to harness, analyzing memory, skills, and protocols as distinct but coupled forms of externalization. It further identifies emerging directions such as self-evolving harnesses and shared agent infrastructure, while discussing open challenges in evaluation and governance.

**Evidence**: The analysis is grounded in a unified review of how practical agent progress depends on better external cognitive infrastructure rather than just stronger models. The text supports this by examining the interaction of these externalized modules and their role in making agent systems reliable in practice.

**Narrow impact**: The work offers a conceptual framework for researchers and engineers designing LLM agents, helping them understand how to structure runtime environments for reliability. It specifically aids in navigating the design choices between internal model parameters and externalized memory, skills, and protocols.

**Broad impact**: By framing agent infrastructure as a critical component of practical progress, the paper influences the broader understanding of how AI systems are built and evolved. It suggests that future advancements will depend as much on the quality of external cognitive infrastructure as on the underlying model capabilities.

**Limitations**: The paper identifies the trade-off between parametric and externalized capability as a key consideration, suggesting that reliance on external infrastructure introduces complexities in evaluation and governance that are not fully resolved. It highlights open challenges in the long-term co-evolution of models and external infrastructure as areas requiring further attention.

## 2. LLM Inference Engine Bugs and Improvements

The cluster of papers collectively investigates the prevalent bugs in LLM inference engines through a comprehensive empirical analysis using real-world data from five major engines. They pinpoint common issues such as memory leaks, out-of-memory errors, incorrect tensor shapes, and performance degradation, emphasizing the necessity for enhanced testing frameworks and monitoring tools to improve the robustness of these systems.


### A First Look at Bugs in LLM Inference Engines

*[2506.09713v2](https://arxiv.org/abs/2506.09713v2) · 2025-06-11 · score 9.1/10*

**Topic**: This paper investigates bugs within large language model (LLM) inference engines used for deploying AI-powered applications.

**Motivation**: The study addresses the critical yet underexplored area of bugs in LLM inference engines, which are essential but complex components that enable scalable deployment across various devices. Understanding these issues is crucial as they can significantly impact the reliability and performance of LLM apps.

**Contribution**: This research provides a comprehensive empirical analysis based on real-world data from five widely adopted LLM inference engines, offering insights into bug symptoms, root causes, fix strategies, temporal evolution, commonality, and effort required for resolution. The findings aim to guide both academic studies and practical improvements in the development of these critical systems.

**Evidence**: The research identifies common issues like memory leaks, out-of-memory errors, incorrect tensor shapes or sizes, and performance degradation due to suboptimal configuration settings. These findings highlight the need for more robust testing frameworks and continuous monitoring tools in LLM inference engine development processes.

**Narrow impact**: The findings are primarily relevant for developers working on LLM applications who rely heavily on these infrastructure components. However, broader implications might extend to other domains where high-performance computing environments require precise control over resource allocation and parallel processing tasks.

**Broad impact**: By providing a systematic understanding of bug prevalence and characteristics in LLM inference engines, this research can inform future developments aimed at enhancing robustness through improved design practices or automated tools for detecting common pitfalls early in the development lifecycle. Such advancements would benefit not only specific applications but potentially influence broader standards within the AI ecosystem. The publicly released dataset supports further investigation by other researchers seeking to replicate these findings or build upon them with additional analyses.

**Limitations**: While this study offers valuable insights into bug characteristics within specific inference engines, it may not fully capture all potential edge cases or less common scenarios that could arise with different hardware configurations or software versions not represented by the selected samples.


---

## Open Questions

- How can self-evolving harnesses be effectively integrated into shared agent infrastructure without compromising the learning process or introducing new bugs?
- What are the most effective evaluation metrics and governance strategies for ensuring the ethical use and development of language learning model agents?
- To what extent do externalization techniques in LLMs contribute to improved performance over traditional machine learning approaches, and how can this be quantitatively measured?
- How can real-world data from diverse domains be effectively utilized to identify and mitigate specific bugs in LLM inference engines?
- What are the long-term implications of widespread adoption of robust LLM inference engines on the broader landscape of artificial intelligence systems?

---

## Gap Candidates

Papers heavily cited within this corpus but not yet annotated:

| # | arXiv ID | Cited by |
|---|----------|----------|
| 1 | [2307.07221](https://arxiv.org/abs/2307.07221) | 4 |
| 2 | [2304.03442](https://arxiv.org/abs/2304.03442) | 3 |
| 3 | [2005.14165](https://arxiv.org/abs/2005.14165) | 3 |
| 4 | [2305.01210](https://arxiv.org/abs/2305.01210) | 3 |
| 5 | [2308.11432](https://arxiv.org/abs/2308.11432) | 3 |
| 6 | [2308.00352](https://arxiv.org/abs/2308.00352) | 3 |
| 7 | [2210.03629](https://arxiv.org/abs/2210.03629) | 3 |
| 8 | [2303.11366](https://arxiv.org/abs/2303.11366) | 3 |
| 9 | [2305.10601](https://arxiv.org/abs/2305.10601) | 2 |
| 10 | [2310.13976](https://arxiv.org/abs/2310.13976) | 2 |
| 11 | [2309.07864](https://arxiv.org/abs/2309.07864) | 2 |
| 12 | [2308.08155](https://arxiv.org/abs/2308.08155) | 2 |
| 13 | [2303.11381](https://arxiv.org/abs/2303.11381) | 2 |
| 14 | [2302.04761](https://arxiv.org/abs/2302.04761) | 2 |
| 15 | [2210.11416](https://arxiv.org/abs/2210.11416) | 2 |

---

*Built with [harness-engineering](https://github.com/nickmccarty/ollama-pi-harness) · /lit-review skill*