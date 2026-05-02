# Literature Review: llm as judge uncertainty

*Generated 2026-04-29 11:54 · 5 fetched · 5 annotated*

---

## Overview

The literature review synthesizes findings across three clusters that collectively explore various aspects of AI evaluation. The first cluster emphasizes the use of conformal prediction and verbal uncertainty estimation to enhance the reliability and expressiveness of language models (LLMs) in judgment roles. The second cluster investigates agent-based AI evaluation frameworks, particularly the Agent-as-a-Judge approach, which demonstrates high reliability and outperforms LLMs in certain tasks. The third cluster focuses on uncertainty analysis in multimodal models, highlighting challenges in quantifying uncertainty across different modalities and architectures.

---

## 1. LLM Evaluation Uncertainty

The papers collectively explore enhancing the reliability and expressiveness of LLMs in judgment roles by integrating conformal prediction techniques to construct continuous prediction intervals and verbal uncertainty estimation. The first study employs conformal prediction for interval evaluations, providing valid intervals with guaranteed coverage and suggesting interval midpoint as a low-bias measure, while the second integrates verbal uncertainty into the personalized judge framework, achieving high agreement on certain tasks and surpassing human performance in some cases. These approaches demonstrate the potential of using advanced statistical methods to improve LLM judgment quality and expressiveness.

**Hub paper**: [Analyzing Uncertainty of LLM-as-a-Judge: Interval Evaluations with Conformal Prediction](https://arxiv.org/abs/2509.18658v1) — cited by 1 paper in this corpus

### Analyzing Uncertainty of LLM-as-a-Judge: Interval Evaluations with Conformal Prediction

*[2509.18658v1](https://arxiv.org/abs/2509.18658v1) · 2025-09-23 · cited ×1 · score 9.7/10*

**Topic**: The paper addresses the underexplored uncertainty in using large language models (LLMs) as judges for evaluating natural language generation (NLG). It introduces a framework to analyze this uncertainty by providing prediction intervals for LLM-based scoring.

**Motivation**: The reliability of LLM-as-a-judge evaluations is currently limited by a lack of understanding regarding their uncertainty, which hinders deployment in many applications. This work aims to improve reliability by offering a method to quantify evaluation uncertainty through prediction intervals.

**Contribution**: The authors present the first framework to analyze LLM evaluation uncertainty using conformal prediction to construct continuous prediction intervals from a single run. They also design an ordinal boundary adjustment for discrete rating tasks and suggest using the interval midpoint as a low-bias alternative to raw scores or weighted averages.

**Evidence**: Extensive experiments and analysis demonstrate that the proposed conformal prediction approach successfully provides valid prediction intervals with guaranteed coverage. The study also explores the practical utility of using the interval midpoint and judge reprompting to enhance judgment quality.

**Narrow impact**: The framework directly impacts the field of NLG evaluation by providing a standardized method to assess and quantify the uncertainty of LLM judges. This allows for more informed decision-making when interpreting LLM-generated scores in automated evaluation pipelines.

**Broad impact**: By addressing the reliability gap in LLM-as-a-judge systems, this work supports the broader deployment of LLMs in applications where evaluation uncertainty is critical. It establishes a foundation for more trustworthy automated assessment of natural language generation outputs.

**Limitations**: The abstract does not explicitly report specific performance deficits or weaker results of the proposed method, such as interval width or computational overhead. Consequently, no specific weaker result can be extracted from the provided text.

### Can LLM be a Personalized Judge?

*[2406.11657v1](https://arxiv.org/abs/2406.11657v1) · 2024-06-17 · cited ×1 · score 9.7/10*

**Topic**: The paper investigates the reliability of using large language models as personalized judges to evaluate user preferences based on personas.

**Motivation**: As LLM user bases expand globally, ensuring models reflect diverse values is crucial, yet current research often relies on LLM-as-a-Judge approaches without thoroughly examining their validity for personalization.

**Contribution**: The authors introduce verbal uncertainty estimation into the LLM-as-a-Personalized-Judge pipeline, allowing the model to express low confidence on uncertain judgments to address issues of low reliability.

**Evidence**: By incorporating verbal uncertainty estimation, the method achieves agreement above 80% on high-certainty samples for binary tasks, with human evaluations showing it matches or surpasses third-party human performance on these samples.

**Narrow impact**: The work suggests that certainty-enhanced LLM-as-a-Personalized-Judge offers a promising direction for developing more reliable methods for evaluating LLM personalization within the scope of the studied tasks.

**Broad impact**: This research highlights the importance of addressing reliability in LLM personalization evaluation, providing a scalable approach that improves alignment with human values as LLMs are deployed globally.

**Limitations**: The text does not explicitly detail specific weaker results beyond the general finding that direct application of the method is less reliable than assumed and suffers from low agreement with human ground truth.

## 2. Agent-Based AI Evaluation Frameworks

The research papers collectively explore the Agent-as-a-Judge framework and DevAI benchmark, which employs a novel approach to evaluate agents by having them judge other agents in 55 automated AI development tasks with detailed user requirements. This study demonstrates that Agent-as-a-Judge significantly outperforms LLM-as-a-Judge and achieves reliability comparable to human evaluations, highlighting its potential for reliable agent assessment.


### Agent-as-a-Judge: Evaluate Agents with Agents

*[2410.10934v2](https://arxiv.org/abs/2410.10934v2) · 2024-10-14 · score 9.7/10*

**Topic**: The paper introduces the Agent-as-a-Judge framework, an organic extension of LLM-as-a-Judge that uses agentic systems to evaluate other agentic systems. This approach is specifically applied to the domain of code generation to address the step-by-step nature of such tasks.

**Motivation**: Contemporary evaluation techniques are inadequate because they either ignore the intermediate steps of agentic systems or require excessive manual labor. The framework aims to provide intermediate feedback for the entire task-solving process, thereby overcoming these limitations.

**Contribution**: The authors introduce the Agent-as-a-Judge framework and present DevAI, a new benchmark comprising 55 realistic automated AI development tasks with 365 hierarchical user requirements. This provides a proof-of-concept testbed that includes rich manual annotations to support reliable evaluation.

**Evidence**: Benchmarking three popular agentic systems reveals that Agent-as-a-Judge dramatically outperforms LLM-as-a-Judge. Furthermore, the method proves to be as reliable as the human evaluation baseline, validating its effectiveness.

**Narrow impact**: The immediate impact is confined to the evaluation of agentic systems within the specific context of code generation and the DevAI benchmark. It provides a reliable mechanism for assessing performance on realistic automated AI development tasks.

**Broad impact**: The framework offers rich and reliable reward signals necessary for the dynamic and scalable self-improvement of modern agentic systems. This marks a concrete step forward in enabling continuous improvement for these systems.

**Limitations**: The abstract does not explicitly state any weaknesses or limitations of the framework, presenting it instead as a concrete step forward. Consequently, no specific weaker result can be extracted from the provided text.

## 3. Uncertainty Analysis in Multimodal Models

The papers "Uncertainty-o" and "VLM Judges Can Rank but Cannot Score" both focus on the quantification of uncertainty in large multimodal models (LMMs). Uncertainty-o introduces a model-agnostic framework for estimating LMM uncertainty across various modalities and architectures, while VLM Judges delves into task-dependent uncertainty in multimodal evaluation using conformal prediction. Both studies highlight the challenges in accurately assessing uncertainty, with Uncertainty-o emphasizing the reliability of its framework through empirical benchmarks and VLM Judges demonstrating the limitations of traditional ranking methods when scoring is not feasible.


### Uncertainty-o: One Model-agnostic Framework for Unveiling Uncertainty in Large Multimodal Models

*[2506.07575v1](https://arxiv.org/abs/2506.07575v1) · 2025-06-09 · score 10.0/10*

**Topic**: This paper investigates the evaluation and quantification of uncertainty within Large Multimodal Models (LMMs), addressing the gap in understanding how these models recognize their own limitations across diverse modalities.

**Motivation**: The research is driven by three open questions: how to unify uncertainty evaluation across different LMMs, how to prompt models to reveal their uncertainty, and how to quantify this uncertainty for practical downstream applications.

**Contribution**: The authors introduce Uncertainty-o, a model-agnostic framework that reveals uncertainty regardless of modality, architecture, or capability, alongside an empirical exploration of multimodal prompt perturbations and a derived formulation for multimodal semantic uncertainty.

**Evidence**: Experiments conducted across 18 benchmarks spanning various modalities and 10 LMMs, including both open- and closed-source models, demonstrate the framework's effectiveness in reliably estimating LMM uncertainty.

**Narrow impact**: The framework enhances specific downstream tasks such as hallucination detection, hallucination mitigation, and uncertainty-aware Chain-of-Thought reasoning by providing reliable uncertainty estimates.

**Broad impact**: By enabling the reliable estimation of uncertainty in diverse LMMs, this work supports the development of more robust and trustworthy multimodal AI systems capable of better managing their limitations in complex tasks.

**Limitations**: The provided abstract does not explicitly detail specific limitations or weaker results, focusing instead on the demonstrated effectiveness of the framework in estimating uncertainty.

### VLM Judges Can Rank but Cannot Score: Task-Dependent Uncertainty in Multimodal Evaluation

*[2604.25235v1](https://arxiv.org/abs/2604.25235v1) · 2026-04-28 · score 9.7/10*

**Topic**: The paper examines the reliability of vision-language models (VLMs) acting as automated judges for multimodal systems, specifically addressing the lack of reliability indicators in their scoring outputs.

**Motivation**: As VLMs are increasingly adopted for automated evaluation, their point scores fail to convey reliability, creating a need for frameworks that can quantify this uncertainty without requiring model retraining.

**Contribution**: The authors present the first systematic analysis of conformal prediction for VLM-as-a-Judge across three judges and fourteen visual task categories, converting point scores into calibrated prediction intervals using only log-probabilities.

**Evidence**: The study identifies a failure mode called ranking-scoring decoupling, where judges achieve high ranking correlation despite producing wide, uninformative intervals, and demonstrates that interval width is driven by task difficulty and annotation quality, yielding 4.5x narrower intervals on clean, multi-annotator benchmarks.

**Narrow impact**: These findings provide a quantitative reliability map for multimodal evaluation, offering specific insights into how different visual task categories affect the precision and calibration of VLM judges.

**Broad impact**: By exposing the disconnect between ranking accuracy and scoring reliability, this work highlights critical limitations in using VLMs as automated evaluators and underscores the necessity of uncertainty quantification for trustworthy multimodal AI systems.

**Limitations**: The analysis reveals that while VLMs can effectively rank responses, their ability to assign reliable absolute scores is limited by significant uncertainty, particularly in complex tasks like mathematical reasoning where intervals become excessively wide.


---

## Open Questions

- How can conformal prediction techniques be further refined to ensure consistent and accurate verbal uncertainty estimation in LLM evaluations?
- What are the limitations of the Agent-as-a-Judge framework when applied to diverse AI development tasks with varying complexity and user requirements?
- Can the principles from Uncertainty-o and VLM Judges be generalized to other types of multimodal models, and if so, how can this be achieved without compromising model performance?
- How do different evaluation frameworks compare in terms of their ability to assess the expressiveness and reliability of LLMs across various judgment tasks?
- What are the implications of the limitations observed in uncertainty analysis for the development and deployment of reliable multimodal AI systems?

---

## Gap Candidates

Papers heavily cited within this corpus but not yet annotated:

| # | arXiv ID | Cited by |
|---|----------|----------|
| 1 | [2306.05685](https://arxiv.org/abs/2306.05685) | 5 |
| 2 | [2306.13063](https://arxiv.org/abs/2306.13063) | 4 |
| 3 | [1506.02142](https://arxiv.org/abs/1506.02142) | 4 |
| 4 | [2305.14975](https://arxiv.org/abs/2305.14975) | 3 |
| 5 | [2303.16634](https://arxiv.org/abs/2303.16634) | 3 |
| 6 | [2404.18796](https://arxiv.org/abs/2404.18796) | 3 |
| 7 | [1612.01474](https://arxiv.org/abs/1612.01474) | 3 |
| 8 | [2411.15594](https://arxiv.org/abs/2411.15594) | 2 |
| 9 | [2404.08168](https://arxiv.org/abs/2404.08168) | 2 |
| 10 | [2403.01216](https://arxiv.org/abs/2403.01216) | 2 |
| 11 | [2310.00074](https://arxiv.org/abs/2310.00074) | 2 |
| 12 | [2306.10193](https://arxiv.org/abs/2306.10193) | 2 |
| 13 | [2305.18404](https://arxiv.org/abs/2305.18404) | 2 |
| 14 | [2110.01052](https://arxiv.org/abs/2110.01052) | 2 |
| 15 | [2106.00225](https://arxiv.org/abs/2106.00225) | 2 |

---

*Built with [harness-engineering](https://github.com/nickmccarty/ollama-pi-harness) · /lit-review skill*