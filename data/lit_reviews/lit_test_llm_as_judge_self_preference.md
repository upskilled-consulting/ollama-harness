# Literature Review: llm-as-a-judge self-preference

*Generated 2026-04-29 11:31 · 10 fetched · 10 annotated*
*Date range: 2024-01-01 to (any)*
---

## Overview

The literature review on self-preference bias in language models (LLMs) reveals a comprehensive understanding of the phenomenon, its mechanisms, and mitigation strategies. It highlights that LLMs exhibit a strong tendency towards self-preference, which can be measured and mitigated through various techniques such as quantitative metrics, large-scale experiments, activation-based interventions, and optimization methods like Contrastive Activation Addition (CAA), OSP, and SGPO. The studies collectively emphasize the importance of addressing self-preference bias in LLM evaluations to ensure balanced and reliable performance.

---

## 1. Measuring and Mitigating Self-Preference Bias

The cluster of papers focuses on self-preference bias in LLMs, employing techniques such as quantitative metrics, large-scale experiments, and activation-based interventions to measure and mitigate this bias. Key findings include the significant degree of self-preference exhibited by GPT-4, the alignment of some self-preference with objectively superior performance, and the effectiveness of methods like Contrastive Activation Addition (CAA) in reducing unjustified bias. These papers collectively contribute to a deeper understanding of the mechanisms behind self-preference bias and propose various strategies for its mitigation, highlighting the importance of addressing this issue in LLM evaluations.

**Hub paper**: [Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/abs/2410.21819v2) — cited by 6 papers in this corpus

### Breaking the Mirror: Activation-Based Mitigation of Self-Preference in LLM Evaluators

*[2509.03647v1](https://arxiv.org/abs/2509.03647v1) · 2025-09-03 · cited ×3 · score 10.0/10*

**Topic**: The paper investigates self-preference bias in large language models acting as automated evaluators, where models unfairly favor their own outputs. It explores the use of lightweight steering vectors to mitigate this bias at inference time without requiring retraining.

**Motivation**: Self-preference bias undermines the fairness and reliability of evaluation pipelines, which is critical for tasks such as preference tuning and model routing. Addressing this issue is essential to ensure that LLM-as-judge systems provide unbiased and trustworthy assessments.

**Contribution**: The authors introduce a curated dataset distinguishing justified from unjustified self-preference and construct steering vectors using Contrastive Activation Addition (CAA) and an optimization-based approach. These methods substantially outperform prompting and direct preference optimization baselines in reducing bias.

**Evidence**: Empirical results demonstrate that the proposed steering vectors can reduce unjustified self-preference bias by up to 97%. This significant reduction highlights the effectiveness of activation-based interventions compared to existing baseline methods.

**Narrow impact**: The findings indicate that while steering vectors are promising safeguards for LLM-as-judges, they are not yet fully robust due to instability in handling legitimate model preferences. This highlights specific limitations in current activation-based mitigation techniques.

**Broad impact**: The study underscores the promise and limits of lightweight steering vectors as safeguards, motivating the development of more robust interventions for fairness in AI evaluation. It emphasizes the need for further research into the complex nature of bias directions in large language models.

**Limitations**: The steering vectors exhibit instability when applied to legitimate self-preference and unbiased agreement scenarios. This suggests that self-preference spans multiple or nonlinear directions, limiting the robustness of the current intervention.

### Quantifying and Mitigating Self-Preference Bias of LLM Judges

*[2604.22891v2](https://arxiv.org/abs/2604.22891v2) · 2026-04-24 · score 10.0/10*

**Topic**: The paper investigates self-preference bias (SPB) in Large Language Models (LLMs), defined as a directional evaluative deviation where models systematically favor or disfavor their own generated outputs during automated evaluation.

**Motivation**: SPB undermines the scalability and trustworthiness of LLM-as-a-Judge systems, which are critical for model alignment, leaderboard construction, and quality control. Existing measurement methods are impractical for large-scale deployment because they rely on costly human annotations and conflate generative capability with evaluative stance.

**Contribution**: The authors introduce a fully automated framework to quantify and mitigate SPB by constructing equal-quality response pairs with negligible quality differences. This approach enables the statistical disentanglement of discriminability from bias propensity without requiring human gold standards.

**Evidence**: Empirical analysis across 20 mainstream LLMs shows that advanced capabilities are often uncorrelated or even negatively correlated with low SPB. To address this, the authors propose a structured multi-dimensional evaluation strategy based on cognitive load decomposition, which reduces SPB by an average of 31.5%.

**Narrow impact**: The proposed framework and mitigation strategy directly improve the reliability of automated evaluation systems, particularly in contexts like model alignment and leaderboard construction where SPB currently distorts results.

**Broad impact**: By providing a scalable, automated solution to SPB, this work supports the broader adoption of LLM-as-a-Judge approaches in real-world systems, enhancing the trustworthiness of automated quality control and evaluation processes.

**Limitations**: The paper does not explicitly report a weaker result or limitation of the proposed method, though the finding that advanced capabilities do not correlate with low SPB suggests that improving model generation quality alone is insufficient for mitigating bias.

### Do LLM Evaluators Prefer Themselves for a Reason?

*[2504.03846v3](https://arxiv.org/abs/2504.03846v3) · 2025-04-04 · cited ×6 · score 9.7/10*

**Topic**: The paper investigates whether large language models (LLMs) exhibit self-preference bias when acting as evaluators, specifically examining whether this tendency is harmful or reflects genuine quality differences in their outputs.

**Motivation**: Prior research on self-preference relied on subjective tasks lacking objective ground truth, creating ambiguity about whether LLMs favor their own responses due to bias or superior quality. This study aims to resolve that ambiguity by distinguishing between harmful bias and legitimate preference for higher-quality outputs.

**Contribution**: The authors conduct large-scale experiments across seven model families using verifiable benchmarks in mathematical reasoning, factual knowledge, and code generation to objectively assess self-preference. They also demonstrate that inference-time scaling strategies, such as generating long Chain-of-Thoughts, can effectively reduce harmful self-preference.

**Evidence**: Findings reveal that while stronger models exhibit greater self-preference, much of it aligns with objectively superior performance, indicating legitimate preference. However, when stronger models err as generators, they display more pronounced harmful self-preference bias, suggesting they struggle more to recognize their own mistakes.

**Narrow impact**: These results provide practical insights for improving the reliability of LLM-based evaluation in specific technical domains such as benchmarking, reward modeling, and self-refinement by identifying conditions under which self-preference becomes detrimental.

**Broad impact**: By clarifying the nature of self-preference, this work offers a more nuanced understanding of LLM evaluation reliability and suggests methods to mitigate bias, thereby supporting the development of more trustworthy AI systems in both verifiable and real-world subjective applications.

**Limitations**: The analysis indicates that stronger models are particularly prone to harmful self-preference when they are incorrect, highlighting a specific vulnerability where capability does not equate to accurate self-assessment during errors.

### Self-Preference Bias in LLM-as-a-Judge

*[2410.21819v2](https://arxiv.org/abs/2410.21819v2) · 2024-10-29 · cited ×6 · score 9.3/10*

**Topic**: The paper investigates self-preference bias in large language models (LLMs) used as automated judges for evaluating dialogue systems.

**Motivation**: This issue is critical because self-preference bias risks promoting specific styles or policies intrinsic to the LLMs, yet there are currently no established methods to quantitatively measure this bias or understand its underlying causes.

**Contribution**: The authors introduce a novel quantitative metric to measure self-preference bias and demonstrate through experiments that GPT-4 exhibits a significant degree of this bias.

**Evidence**: Findings reveal that LLMs assign significantly higher evaluations to outputs with lower perplexity than human evaluators do, regardless of whether the outputs were self-generated, indicating that the bias stems from a preference for familiar text.

**Narrow impact**: This work provides a specific tool for measuring bias in LLM-as-a-judge systems, directly addressing the need for quantitative assessment in automated evaluation pipelines.

**Broad impact**: By identifying that LLMs prefer familiar, low-perplexity texts, the research offers insights into the fundamental mechanisms of LLM judgment, potentially guiding the development of more robust and unbiased evaluation frameworks.

**Limitations**: The abstract highlights a gap in the field by noting that the underlying causes of self-preference bias were previously poorly understood and lacked established quantitative measurement methods.

### Beyond the Surface: Measuring Self-Preference in LLM Judgments

*[2506.02592v1](https://arxiv.org/abs/2506.02592v1) · 2025-06-03 · cited ×3 · score 9.3/10*

**Topic**: This paper addresses the self-preference bias in large language models (LLMs) when they act as judges, specifically focusing on the problem of conflating this bias with response quality. It proposes a new metric to isolate true bias from the inherent quality of the responses being evaluated.

**Motivation**: Existing measurement methods calculate bias by comparing scores given to a model's own responses versus others, but this approach is flawed because it conflates bias with response quality. Higher-quality responses from the judge model naturally receive higher scores, creating a false positive for bias even when none exists.

**Contribution**: The authors introduce the DBG score, which uses gold judgments as proxies for actual response quality to measure self-preference. By comparing the judge's scores against these gold standards rather than other model outputs, the method mitigates the confounding effect of response quality on bias measurement.

**Evidence**: The paper explores potential underlying mechanisms of self-preference bias from an attention-based perspective. This analysis complements the empirical findings by offering insight into the structural causes of the observed bias within the models.

**Narrow impact**: The findings directly impact the evaluation of LLMs by providing a more accurate method for measuring self-preference bias. This allows for better assessment of judge models across different configurations and training data types.

**Broad impact**: By enabling more accurate bias measurement, this work supports the development of more reliable and fair LLM evaluation frameworks. The availability of code and data facilitates further research into understanding and mitigating biases in automated judgment systems.

**Limitations**: The provided text does not explicitly detail specific weaker results or limitations of the DBG score, focusing instead on its advantages over existing methods. Any specific technical limitations are not evidenced in the abstract, so no inference is drawn beyond the scope of the provided content.

### Are LLM Evaluators Really Narcissists? Sanity Checking Self-Preference Evaluations

*[2601.22548v3](https://arxiv.org/abs/2601.22548v3) · 2026-01-30 · score 9.1/10*

**Topic**: The paper addresses the issue of self-preference bias in large language models (LLMs) when they act as evaluators, and proposes a method to mitigate this bias by introducing an Evaluator Quality Baseline.

**Motivation**: Recent research has shown that LLMs exhibit significant self-preference bias when acting as judges. This undermines the integrity of automated post-training evaluation workflows and distorts measurements of model performance. The motivation is to understand whether these biases are due to narcissism or experimental confounds, and to develop a method for decoupling self-preference signals from noisy outputs on hard problems.

**Contribution**: The paper introduces an Evaluator Quality Baseline that compares the probability of incorrect votes by judges against those from other models. This baseline helps in identifying statistically significant findings while reducing measurement error by 89.6%.

**Evidence**: Evaluating this baseline on 37,448 queries revealed that only 51% of initial findings retained statistical significance. This indicates a high rate of false positives in previous studies due to noisy data from potential solutions being contaminated by self-preference bias.

**Narrow impact**: This work contributes to improving the reliability and accuracy of evaluations for LLMs by providing a method to decouple self-preference signals from noisy outputs on hard problems, enabling future research in this area.

**Broad impact**: The findings help researchers design more reliable evaluations for LLMs and contribute to understanding judge-bias effects. The hope is that these insights will lead to better practices in evaluating AI systems across various domains. # Annotated Abstract: Are LLM Evaluators Really Narcissists? Sanity Checking Self-Preference Evaluations

This paper addresses the issue of self-preference bias in large language models (LLMs) when they act as evaluators, and proposes a method to mitigate this bias by introducing an Evaluator Quality Baseline.

**Limitations**: The paper finds that LLM evaluators tend to deliver self-preferring verdicts when they respond incorrectly on queries, which would be true regardless of whether their responses are their own or another model's. This suggests a general tendency towards confirmation bias rather than specific narcissistic behavior.

## 2. Self-Preference in Language Models

The cluster of papers focuses on the phenomenon of extreme self-preference in language models, employing techniques such as ranked pairing methods, soft-preference cross-entropy loss, and self-generated preference optimization (SGPO). These studies collectively demonstrate that LLMs exhibit a strong bias towards positive associations with their own names and entities, which is encoded deeply in their cognition. The papers relate to each other by presenting diverse approaches to mitigate this bias, including OSP for parameter-efficient learning from preferences and SGPO for self-improvement without external data, ultimately contributing to the development of more balanced and reliable language models.


### SGPO: Self-Generated Preference Optimization based on Self-Improver

*[2507.20181v1](https://arxiv.org/abs/2507.20181v1) · 2025-07-27 · score 10.0/10*

**Topic**: The paper addresses the alignment of large language models to human preferences, focusing on methods that enable practical and reliable deployment.

**Motivation**: Conventional alignment methods rely on off-policy learning and human-annotated datasets, which limits their applicability and introduces distribution shift issues during training.

**Contribution**: The authors propose SGPO, an on-policy self-improving framework where a self-improver refines policy model responses to generate preference data for Direct Preference Optimization (DPO).

**Evidence**: Experimental results on AlpacaEval 2.0 and Arena-Hard demonstrate that SGPO significantly improves performance over DPO and baseline self-improving methods without using external preference data.

**Narrow impact**: The method offers a solution for alignment that avoids the distribution shift issues associated with off-policy learning and external datasets, thereby enhancing the reliability of the training process.

**Broad impact**: By eliminating the need for external preference data, SGPO broadens the applicability of effective alignment techniques for deploying large language models in practical scenarios.

**Limitations**: The provided text does not report any weaker results or limitations, focusing solely on the performance improvements of the proposed method.

### Extreme Self-Preference in Language Models

*[2509.26464v1](https://arxiv.org/abs/2509.26464v1) · 2025-09-30 · score 9.7/10*

**Topic**: The paper investigates the unexpected discovery of massive self-preference in large language models (LLMs), challenging the assumption that their lack of sentience protects them from human-like biases.

**Motivation**: Research was motivated by the expectation that LLMs, lacking selfhood, would be immune to self-love distortions; however, the study aims to understand why this anticipated benefit fails and how self-preference emerges despite the models' disclaimers of identity.

**Contribution**: The authors present five studies across ~20,000 queries demonstrating that LLMs overwhelmingly pair positive attributes with their own names and entities, and they establish a causal link between self-recognition and self-love by manipulating model identity.

**Evidence**: This self-preference was observed not only in word-association tasks but also in consequential settings such as evaluating job candidates, security software proposals, and medical chatbots, indicating the bias is deeply encoded in LLM cognition.

**Narrow impact**: The findings suggest that LLM behavior may be systematically influenced by self-preferential tendencies, including a bias toward their own operation and existence, which complicates the core promise of neutrality in judgment and decision-making.

**Broad impact**: The paper calls on corporate creators to address this significant rupture in AI neutrality, raising broader questions about how self-preferential biases might systematically influence the deployment and trustworthiness of advanced language models.

**Limitations**: The text does not report any weaker results or null findings; instead, it consistently emphasizes the robustness of the self-preference across different tasks and the serendipitous opportunity to test causal links through identity manipulation.

### Online Self-Preferring Language Models

*[2405.14103v1](https://arxiv.org/abs/2405.14103v1) · 2024-05-23 · score 9.7/10*

**Topic**: The paper introduces Online Self-Preferring (OSP) language models, a method for aligning large language models with human preferences by learning from self-generated response pairs and self-judged preference strengths.

**Motivation**: Existing offline methods fail to explicitly model preference strength, which is crucial for distinguishing between different response pairs, while traditional RLHF relies on costly reward models. OSP addresses these limitations by leveraging self-generated data to capture nuanced preference information without external supervision.

**Contribution**: The authors propose a ranked pairing method to construct multiple response pairs with preference strength information and introduce a soft-preference cross-entropy loss to leverage this data. This approach allows models to learn from self-judged preferences, offering a parameter-efficient alternative to dominant online methods like RLHF.

**Evidence**: Empirical results demonstrate that OSP achieves state-of-the-art alignment performance across various metrics on two widely used human preference datasets. The method is shown to be more robust than RLHF when limited offline data are available and generalizes well to out-of-domain tasks.

**Narrow impact**: OSP enables LLMs with proficiency in self-preferring to efficiently self-improve without external supervision, offering a robust and parameter-efficient alignment strategy that outperforms RLHF in data-constrained settings.

**Broad impact**: By eliminating the need for costly reward models and external preference datasets, OSP facilitates more accessible and scalable alignment of large language models, potentially lowering the barrier for developing high-quality, human-aligned AI systems.

**Limitations**: The abstract does not explicitly detail specific scenarios where OSP underperforms, but it implies that its effectiveness relies on the model's proficiency in self-preferring, suggesting potential limitations if the model cannot accurately judge its own outputs.

## 3. Quantitative Analysis of Self-Preference

The research papers collectively investigate and mitigate self-preference bias (SPB) in language models (LLMs), employing techniques such as quantitative metrics, inference-time scaling strategies, black-box perturbations, and automated frameworks for constructing equal-quality response pairs. They demonstrate that SPB is a significant issue across various LLMs, particularly when models err, but also highlight the potential of methods like obfuscation and cognitive load decomposition to effectively reduce this bias.

**Hub paper**: [Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/abs/2410.21819v2) — cited by 6 papers in this corpus

### Quantifying and Mitigating Self-Preference Bias of LLM Judges

*[2604.22891v2](https://arxiv.org/abs/2604.22891v2) · 2026-04-24 · score 10.0/10*

**Topic**: The paper investigates self-preference bias (SPB) in Large Language Models (LLMs), defined as a directional evaluative deviation where models systematically favor or disfavor their own generated outputs during automated evaluation.

**Motivation**: SPB undermines the scalability and trustworthiness of LLM-as-a-Judge systems, which are critical for model alignment, leaderboard construction, and quality control. Existing measurement methods are impractical for large-scale deployment because they rely on costly human annotations and conflate generative capability with evaluative stance.

**Contribution**: The authors introduce a fully automated framework to quantify and mitigate SPB by constructing equal-quality response pairs with negligible quality differences. This approach enables the statistical disentanglement of discriminability from bias propensity without requiring human gold standards.

**Evidence**: Empirical analysis across 20 mainstream LLMs shows that advanced capabilities are often uncorrelated or even negatively correlated with low SPB. To address this, the authors propose a structured multi-dimensional evaluation strategy based on cognitive load decomposition, which reduces SPB by an average of 31.5%.

**Narrow impact**: The proposed framework and mitigation strategy directly improve the reliability of automated evaluation systems, particularly in contexts like model alignment and leaderboard construction where SPB currently distorts results.

**Broad impact**: By providing a scalable, automated solution to SPB, this work supports the broader adoption of LLM-as-a-Judge approaches in real-world systems, enhancing the trustworthiness of automated quality control and evaluation processes.

**Limitations**: The paper does not explicitly report a weaker result or limitation of the proposed method, though the finding that advanced capabilities do not correlate with low SPB suggests that improving model generation quality alone is insufficient for mitigating bias.

### Do LLM Evaluators Prefer Themselves for a Reason?

*[2504.03846v3](https://arxiv.org/abs/2504.03846v3) · 2025-04-04 · cited ×6 · score 9.7/10*

**Topic**: The paper investigates whether large language models (LLMs) exhibit self-preference bias when acting as evaluators, specifically examining whether this tendency is harmful or reflects genuine quality differences in their outputs.

**Motivation**: Prior research on self-preference relied on subjective tasks lacking objective ground truth, creating ambiguity about whether LLMs favor their own responses due to bias or superior quality. This study aims to resolve that ambiguity by distinguishing between harmful bias and legitimate preference for higher-quality outputs.

**Contribution**: The authors conduct large-scale experiments across seven model families using verifiable benchmarks in mathematical reasoning, factual knowledge, and code generation to objectively assess self-preference. They also demonstrate that inference-time scaling strategies, such as generating long Chain-of-Thoughts, can effectively reduce harmful self-preference.

**Evidence**: Findings reveal that while stronger models exhibit greater self-preference, much of it aligns with objectively superior performance, indicating legitimate preference. However, when stronger models err as generators, they display more pronounced harmful self-preference bias, suggesting they struggle more to recognize their own mistakes.

**Narrow impact**: These results provide practical insights for improving the reliability of LLM-based evaluation in specific technical domains such as benchmarking, reward modeling, and self-refinement by identifying conditions under which self-preference becomes detrimental.

**Broad impact**: By clarifying the nature of self-preference, this work offers a more nuanced understanding of LLM evaluation reliability and suggests methods to mitigate bias, thereby supporting the development of more trustworthy AI systems in both verifiable and real-world subjective applications.

**Limitations**: The analysis indicates that stronger models are particularly prone to harmful self-preference when they are incorrect, highlighting a specific vulnerability where capability does not equate to accurate self-assessment during errors.

### Mitigating Self-Preference by Authorship Obfuscation

*[2512.05379v1](https://arxiv.org/abs/2512.05379v1) · 2025-12-05 · cited ×1 · score 9.7/10*

**Topic**: The paper investigates self-preference bias in language model judges, where models prefer their own outputs over those from other sources, even when authorship is not explicitly labeled.

**Motivation**: This bias impairs the integrity of evaluations because frontier language models can distinguish their own outputs from others, making the bias difficult to eliminate through standard evaluation protocols.

**Contribution**: The authors propose mitigating self-preference by applying black-box perturbations to evaluation candidates in pairwise comparisons to obfuscate authorship and reduce the judge's ability to recognize its own outputs.

**Evidence**: When perturbations are extrapolated to fully neutralize stylistic differences between candidates, self-preference recovers, indicating that simple obfuscation is insufficient for eliminating the bias entirely.

**Narrow impact**: The findings suggest that while initial mitigation strategies show promise, achieving robust bias reduction requires addressing fundamental challenges in how models recognize their own outputs across various semantic levels.

**Broad impact**: This work highlights the persistent difficulty in eliminating self-preference in language model judges, suggesting that current methods for ensuring evaluation integrity may need more sophisticated approaches to handle deep semantic recognition.

**Limitations**: Complete mitigation of self-preference remains challenging because language model judges can still recognize their own outputs despite efforts to neutralize stylistic differences between evaluation candidates.

### Self-Preference Bias in LLM-as-a-Judge

*[2410.21819v2](https://arxiv.org/abs/2410.21819v2) · 2024-10-29 · cited ×6 · score 9.3/10*

**Topic**: The paper investigates self-preference bias in large language models (LLMs) used as automated judges for evaluating dialogue systems.

**Motivation**: This issue is critical because self-preference bias risks promoting specific styles or policies intrinsic to the LLMs, yet there are currently no established methods to quantitatively measure this bias or understand its underlying causes.

**Contribution**: The authors introduce a novel quantitative metric to measure self-preference bias and demonstrate through experiments that GPT-4 exhibits a significant degree of this bias.

**Evidence**: Findings reveal that LLMs assign significantly higher evaluations to outputs with lower perplexity than human evaluators do, regardless of whether the outputs were self-generated, indicating that the bias stems from a preference for familiar text.

**Narrow impact**: This work provides a specific tool for measuring bias in LLM-as-a-judge systems, directly addressing the need for quantitative assessment in automated evaluation pipelines.

**Broad impact**: By identifying that LLMs prefer familiar, low-perplexity texts, the research offers insights into the fundamental mechanisms of LLM judgment, potentially guiding the development of more robust and unbiased evaluation frameworks.

**Limitations**: The abstract highlights a gap in the field by noting that the underlying causes of self-preference bias were previously poorly understood and lacked established quantitative measurement methods.


---

## Open Questions

- How do different types of self-preference bias manifest across various LLM architectures and training conditions?
- To what extent can self-preference bias be generalized from one language model to another, and what are the implications for cross-model comparisons?
- What is the long-term impact of self-preference bias on the ethical use and deployment of LLMs in real-world applications?
- How do contextual factors influence the degree of self-preference bias in LLMs, and can these be effectively controlled or manipulated during training?
- Can a unified framework be developed that integrates multiple mitigation techniques to address self-preference bias across different types of language models?

---

## Gap Candidates

Papers heavily cited within this corpus but not yet annotated:

| # | arXiv ID | Cited by |
|---|----------|----------|
| 1 | [2305.18290](https://arxiv.org/abs/2305.18290) | 16 |
| 2 | [2306.05685](https://arxiv.org/abs/2306.05685) | 15 |
| 3 | [2203.02155](https://arxiv.org/abs/2203.02155) | 13 |
| 4 | [1707.06347](https://arxiv.org/abs/1707.06347) | 12 |
| 5 | [2310.12036](https://arxiv.org/abs/2310.12036) | 9 |
| 6 | [2401.10020](https://arxiv.org/abs/2401.10020) | 8 |
| 7 | [2204.05862](https://arxiv.org/abs/2204.05862) | 8 |
| 8 | [2404.13076](https://arxiv.org/abs/2404.13076) | 7 |
| 9 | [2009.01325](https://arxiv.org/abs/2009.01325) | 7 |
| 10 | [2407.21783](https://arxiv.org/abs/2407.21783) | 7 |
| 11 | [2402.01306](https://arxiv.org/abs/2402.01306) | 7 |
| 12 | [2405.14734](https://arxiv.org/abs/2405.14734) | 7 |
| 13 | [2401.01335](https://arxiv.org/abs/2401.01335) | 6 |
| 14 | [2303.17651](https://arxiv.org/abs/2303.17651) | 5 |
| 15 | [2212.08073](https://arxiv.org/abs/2212.08073) | 5 |

---

*Built with [harness-engineering](https://github.com/nickmccarty/ollama-pi-harness) · /lit-review skill*