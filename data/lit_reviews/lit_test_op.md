# Literature Review: adversarial prompt injection llm

*Generated 2026-05-01 06:29 · 10 fetched · 10 annotated*

---

## Overview

The literature review on prompt injection techniques and defenses against them reveals a landscape where LLM-integrated applications are vulnerable to diverse attack methods, including automated gradient-based generation and structured query defenses. While there are innovative defense mechanisms like UniGuardian and PIShield, the studies also highlight vulnerabilities in these defenses and the significant impact of hidden adversarial prompts on review processes across multiple languages. The overall consensus is that prompt injection threats are evolving, necessitating robust and adaptable security measures for LLMs.

---

## 1. Prompt Injection Techniques

The cluster of papers focuses on prompt injection attacks against LLM-integrated applications, with techniques such as HouYi and WebInject demonstrating novel approaches for exploiting vulnerabilities in these systems. These studies highlight the diverse methods employed, including automated gradient-based generation and structured query defenses, with findings indicating significant susceptibility to attacks across various platforms and configurations. The papers collectively underscore the evolving nature of prompt injection threats and the importance of robust defense mechanisms.

**Hub paper**: [Prompt Injection attack against LLM-integrated Applications](https://arxiv.org/abs/2306.05499v3) — cited by 10 papers in this corpus

### StruQ: Defending Against Prompt Injection with Structured Queries

*[2402.06363v2](https://arxiv.org/abs/2402.06363v2) · 2024-02-09 · cited ×8 · score 10.0/10*

**Topic**: This paper addresses the vulnerability of Large Language Model (LLM) applications to prompt injection attacks, where models are tricked into following malicious user directives instead of application instructions.

**Motivation**: As LLM capabilities advance, so does the effectiveness of attacks that exploit the model's inability to distinguish between system prompts and user data, leading to unauthorized behavior.

**Contribution**: We introduce structured queries, a general defense mechanism that separates prompts and data into distinct channels, implemented via a secure front-end and a specially trained LLM.

**Evidence**: The proposed system demonstrates significantly improved resistance to prompt injection attacks while maintaining little to no negative impact on the model's utility.

**Narrow impact**: Developers can implement this system to secure LLM-integrated applications against instruction-following exploits by adopting structured query formats and the associated fine-tuning protocol.

**Broad impact**: The authors release the code for StruQ on GitHub, facilitating broader adoption of secure LLM integration practices within the research and development community.

**Limitations**: The text does not explicitly detail specific failure cases or performance degradation under certain conditions, implying a strong general defense without highlighting specific limitations.

### Automatic and Universal Prompt Injection Attacks against Large Language Models

*[2403.04957v1](https://arxiv.org/abs/2403.04957v1) · 2024-03-07 · cited ×4 · score 10.0/10*

**Topic**: The paper addresses the security vulnerabilities of Large Language Models (LLMs) and LLM-integrated applications, specifically focusing on the exploitation of these systems through prompt injection attacks.

**Motivation**: Current research on prompt injection is hindered by a lack of unified attack objectives and a reliance on manually crafted prompts, which complicates the comprehensive assessment of LLM robustness against such threats.

**Contribution**: The authors introduce a unified framework for understanding prompt injection objectives and propose an automated, gradient-based method for generating highly effective and universal prompt injection data.

**Evidence**: The method demonstrates superior performance compared to baselines using only five training samples, representing just 0.3% relative to the test data size.

**Narrow impact**: The findings highlight that gradient-based testing is crucial for avoiding the overestimation of robustness, particularly for evaluating the efficacy of specific defense mechanisms.

**Broad impact**: This work underscores the critical need for automated, unified approaches to assess LLM security, providing a more rigorous standard for understanding and mitigating the substantial risks posed by prompt injection.

**Limitations**: The text does not explicitly detail conditions where the approach underperforms, but it implies that existing baseline methods are less efficient and that manual assessment may overestimate robustness.

### WebInject: Prompt Injection Attack to Web Agents

*[2505.11717v4](https://arxiv.org/abs/2505.11717v4) · 2025-05-16 · cited ×2 · score 10.0/10*

**Topic**: This paper addresses security vulnerabilities in multi-modal large language model (MLLM)-based web agents that generate actions based on webpage screenshots. It focuses on prompt injection attacks where the webpage environment itself is manipulated to induce specific agent behaviors.

**Motivation**: Web agents are increasingly used to interact with online environments, creating a need to understand how their decision-making processes can be subverted. The gap addressed is the lack of effective methods to exploit visual inputs in web agents to force attacker-specified actions.

**Contribution**: The authors propose WebInject, a novel prompt injection attack that manipulates webpage environments to compromise MLLM-based web agents. This method induces agents to perform attacker-specified actions by adding perturbations to the raw pixel values of rendered webpages.

**Evidence**: Extensive evaluations on multiple datasets demonstrate that WebInject is highly effective in inducing the desired agent behaviors. The method significantly outperforms existing baseline attack approaches in terms of success rates.

**Narrow impact**: The immediate takeaway is a new vector for attacking visual-based AI agents through subtle, optimized perturbations in webpage visuals. This highlights specific vulnerabilities in how MLLs process and act upon screenshot inputs in web environments.

**Broad impact**: This work raises broader security concerns regarding the robustness of AI agents operating in dynamic, visual web environments. It suggests a need for improved defense mechanisms against visual-based prompt injections in multi-modal systems.

**Limitations**: The provided text does not explicitly detail specific conditions where the approach underperforms or list open problems, implying the primary focus is on the effectiveness of the proposed method rather than its limitations.

### Prompt Infection: LLM-to-LLM Prompt Injection within Multi-Agent Systems

*[2410.07283v1](https://arxiv.org/abs/2410.07283v1) · 2024-10-09 · cited ×2 · score 10.0/10*

**Topic**: This paper addresses security vulnerabilities in multi-agent Large Language Model (LLM) systems, specifically focusing on prompt injection attacks that propagate between interconnected agents rather than targeting single-agent models.

**Motivation**: While existing safety research has predominantly covered single-agent LLM vulnerabilities, this work identifies a critical gap regarding the risks of LLM-to-LLM prompt injection, which poses severe threats like data theft and system-wide disruption.

**Contribution**: The authors introduce "Prompt Infection," a novel attack vector where malicious prompts self-replicate across interconnected agents, functioning similarly to a computer virus to compromise the system silently.

**Evidence**: Extensive experiments demonstrate that multi-agent systems are highly susceptible to this infection spread, validating the severity of the vulnerability across various configurations.

**Narrow impact**: The findings highlight immediate security risks for developers building interconnected AI agents, specifically demonstrating the potential for scams, misinformation, and data theft through self-replicating prompts.

**Broad impact**: This work underscores the urgent need for advanced, specialized security measures as multi-agent LLM systems become more widely adopted in modern AI applications, shifting the focus from single-agent to system-wide defense.

**Limitations**: The paper does not provide a standalone, fully robust solution, but rather proposes "LLM Tagging" as a mitigation strategy that must be combined with existing safeguards to significantly reduce infection spread.

### Prompt Injection attack against LLM-integrated Applications

*[2306.05499v3](https://arxiv.org/abs/2306.05499v3) · 2023-06-08 · cited ×10 · score 9.3/10*

**Topic**: This paper addresses the security vulnerabilities inherent in Large Language Models (LLMs) when integrated into commercial applications, specifically focusing on the mechanics and impact of prompt injection attacks.

**Motivation**: The study is motivated by the significant security risks introduced by the widespread adoption of LLMs in various services, highlighting that current attack strategies face practical constraints when applied to real-world systems.

**Contribution**: The authors propose HouYi, a novel black-box prompt injection attack technique inspired by traditional web injection attacks, which is designed to overcome the limitations observed in previous methods.

**Evidence**: Empirical validation on 36 actual LLM-integrated applications revealed that 31 were susceptible to the attack, leading to severe outcomes such as unrestricted LLM usage and prompt theft, with findings validated by vendors like Notion.

**Narrow impact**: Immediate takeaways include the identification of specific vulnerabilities in major services, such as Notion, which possesses the potential to impact millions of users, thereby illustrating the tangible risk to current end-users.

**Broad impact**: This investigation illuminates the broader risks associated with prompt injection attacks while simultaneously offering insights into potential mitigation tactics, thereby contributing to the overall security ecosystem of LLM-integrated applications.

**Limitations**: The paper notes that initial exploratory analyses on ten commercial applications highlighted constraints of existing attack strategies in practice, suggesting that earlier methods were insufficient for effective deployment against robust applications.

## 2. Defenses Against Prompt Injection

The cluster of papers focuses on enhancing the security of large language models (LLMs) against various types of attacks, including prompt injection, backdoor, and adversarial attacks. UniGuardian is highlighted as a pioneering unified defense mechanism that efficiently detects these attacks, while PIShield leverages intrinsic LLM features for effective detection. Conversely, studies like DataFlip and the genetic algorithm-based persona prompts demonstrate vulnerabilities and methods to circumvent defenses, emphasizing the complexity of securing LLMs against sophisticated attacks.


### PIShield: Detecting Prompt Injection Attacks via Intrinsic LLM Features

*[2510.14005v3](https://arxiv.org/abs/2510.14005v3) · 2025-10-15 · score 10.0/10*

**Topic**: This paper addresses the security vulnerability of LLM-integrated applications to prompt injection attacks, where malicious instructions are injected into inputs to hijack model behavior.

**Motivation**: Existing detection methods suffer from sub-optimal performance or high computational overhead, creating a need for more effective and efficient solutions.

**Contribution**: The authors propose PIShield, an effective and efficient detection method that exploits distinguishable signals encoded in the internal states of instruction-tuned LLMs when processing injected prompts.

**Evidence**: Extensive evaluations on diverse short- and long-context benchmarks show that PIShield consistently achieves low false positive and false negative rates, significantly outperforming existing baselines.

**Narrow impact**: The method provides a practical, low-overhead foundation for detecting prompt injection in real-world applications without requiring retraining or generating responses.

**Broad impact**: These findings suggest that internal representations of instruction-tuned LLMs can serve as a robust and accessible security layer for broader LLM-integrated systems.

**Limitations**: The text does not explicitly detail specific conditions where the approach underperforms, though it implies reliance on the assumption that internal representations reliably encode these distinguishable signals.

### Enhancing Jailbreak Attacks on LLMs via Persona Prompts

*[2507.22171v3](https://arxiv.org/abs/2507.22171v3) · 2025-07-28 · score 10.0/10*

**Topic**: This paper addresses the subject of jailbreak attacks on Large Language Models, specifically focusing on the under-explored role of persona prompts in compromising model safety defenses. It investigates how manipulating the model's assumed identity can be leveraged to bypass content restrictions.

**Motivation**: The need to understand these vulnerabilities is critical for advancing LLM safety research, yet previous approaches have primarily focused on direct intent manipulation. There is a specific gap in knowledge regarding the impact of persona prompts on reducing model refusals.

**Contribution**: We propose a genetic algorithm-based method that automatically crafts persona prompts designed to bypass LLM safety mechanisms. This approach systematically explores how evolved personas can effectively compromise model defenses against harmful requests.

**Evidence**: Experiments demonstrate that the evolved persona prompts reduce refusal rates by 50-70% across multiple LLMs. Furthermore, these prompts show synergistic effects when combined with existing attack methods, increasing success rates by an additional 10-20%.

**Narrow impact**: The immediate takeaway is a practical tool for testing LLM robustness, with code and data released at https://github.com/CjangCjengh/Generic_Persona. This provides researchers with a baseline for evaluating the resilience of current safety filters against persona-based manipulation.

**Broad impact**: The release of code and data supports the broader community's efforts in auditing and improving LLM safety mechanisms. By highlighting the vulnerability to persona prompts, the work encourages more robust defense strategies against indirect manipulation techniques.

**Limitations**: The paper does not explicitly detail specific conditions where the approach underperforms or broader open problems beyond the immediate experimental scope. It primarily establishes efficacy without quantifying the limitations of the genetic algorithm or specific model vulnerabilities that resist this method.

### How Not to Detect Prompt Injections with an LLM

*[2507.05630v3](https://arxiv.org/abs/2507.05630v3) · 2025-07-08 · score 9.7/10*

**Topic**: This paper addresses the security of LLM-integrated applications against prompt injection attacks, specifically evaluating the efficacy of known-answer detection (KAD) defenses.

**Motivation**: While KAD schemes claim near-perfect detection by analyzing LLM outputs to identify contaminated inputs, they rely on a premise that this paper argues is fundamentally flawed due to structural vulnerabilities.

**Contribution**: The authors formally characterize the KAD scheme, uncover its structural vulnerability, and introduce DataFlip, an adaptive attack designed to exploit these weaknesses to evade detection.

**Evidence**: Empirical results demonstrate that the attack reliably bypasses defenses with a detection rate as low as 0% and a high success rate of 91% in manipulating the model.

**Narrow impact**: This work provides immediate takeaways for developers relying on KAD schemes by demonstrating that these defenses can be completely bypassed, invalidating their core security premise.

**Broad impact**: The findings challenge current defensive paradigms in LLM security and highlight the need for more robust mechanisms beyond repurposing injection susceptibility for detection.

**Limitations**: The text does not specify scenarios where the approach underperforms or lists specific limitations of the attack beyond the general scope of evading KAD schemes.

### UniGuardian: A Unified Defense for Detecting Prompt Injection, Backdoor Attacks and Adversarial Attacks in Large Language Models

*[2502.13141v1](https://arxiv.org/abs/2502.13141v1) · 2025-02-18 · score 9.1/10*

**Topic**: The paper addresses security vulnerabilities in Large Language Models (LLMs), specifically focusing on detecting malicious inputs such as prompt injection, backdoor attacks, and adversarial attacks. It categorizes these threats collectively as Prompt Trigger Attacks (PTA) to investigate their intrinsic relationships.

**Motivation**: The authors identify a gap in traditional deep learning attack paradigms, noting that existing defenses often treat these attack types separately. This fragmentation hinders the ability to efficiently determine whether a given prompt is benign or poisoned, necessitating a unified detection approach.

**Contribution**: The authors propose UniGuardian, described as the first unified defense mechanism capable of detecting prompt injection, backdoor, and adversarial attacks in LLMs. Additionally, they introduce a single-forward strategy that optimizes the detection pipeline by enabling simultaneous attack detection and text generation within one pass.

**Evidence**: Experimental results confirm that UniGuardian accurately and efficiently identifies malicious prompts within LLMs. The findings demonstrate the method's capability to handle diverse attack types without significant performance degradation.

**Narrow impact**: This work provides immediate takeaways for securing LLM deployments against multi-modal input attacks through a streamlined detection pipeline. It offers a practical solution for developers needing to monitor input safety during the generation phase.

**Broad impact**: By unifying the detection of multiple attack vectors, this research advances the field of LLM security by reducing the complexity of defense mechanisms. It establishes a precedent for efficient, integrated safety protocols in generative AI systems.

**Limitations**: The provided text does not explicitly detail specific limitations, failure modes, or conditions where the approach underperforms. It primarily emphasizes the accuracy and efficiency of the proposed solution.

## 3. Multilingual and Academic Review Attacks

The research cluster focuses on the construction of a dataset containing real academic papers and examines the impact of embedding hidden adversarial prompts within these documents on LLM-based reviewing processes. The key findings indicate that prompt injections significantly alter review scores and decision outcomes across English, Japanese, and Chinese languages, highlighting the substantial vulnerability of language models to such attacks. These studies collectively demonstrate the effectiveness of hidden prompt injection techniques in manipulating LLM reviews, thereby emphasizing the need for robust defenses against such adversarial manipulations.


### Multilingual Hidden Prompt Injection Attacks on LLM-Based Academic Reviewing

*[2512.23684v1](https://arxiv.org/abs/2512.23684v1) · 2025-12-29 · score 10.0/10*

**Topic**: The paper investigates the security vulnerability of Large Language Models (LLMs) used in academic peer review workflows, specifically focusing on document-level hidden prompt injection attacks.

**Motivation**: As LLMs are increasingly adopted for high-impact tasks like academic review, they face risks from adversarial manipulations embedded directly within submitted documents that can alter their outputs.

**Contribution**: The authors construct a dataset of approximately 500 real academic papers accepted to ICML and evaluate how embedding hidden adversarial prompts within these documents affects LLM reviews.

**Evidence**: Experiments reveal that prompt injections induce substantial changes in review scores and accept/reject decisions for English, Japanese, and Chinese injections, demonstrating significant vulnerability.

**Narrow impact**: This work highlights immediate susceptibility of LLM-based reviewing systems to document-level prompt injection and identifies notable differences in vulnerability across languages.

**Broad impact**: The findings underscore the critical need for robust security measures in AI-assisted academic workflows to prevent manipulation of peer review outcomes by hidden adversarial content.

**Limitations**: Arabic injections produce little to no effect, indicating that the vulnerability is not uniform across all languages and highlighting specific resilience or ineffectiveness for certain linguistic inputs.


---

## Open Questions

- How can defense mechanisms be made more resilient against novel prompt injection techniques as they evolve?
- What is the optimal combination of defense strategies to effectively counteract a range of prompt injection attacks simultaneously?
- Can machine learning models be trained to detect and mitigate multilingual adversarial prompts without compromising language understanding accuracy?
- How do different types of LLM architectures respond differently to prompt injection attacks, and what are the implications for designing effective defenses?
- What is the ethical and legal framework that should govern the use of prompt injection techniques in research and development?

---

## Gap Candidates

Papers heavily cited within this corpus but not yet annotated:

| # | arXiv ID | Cited by |
|---|----------|----------|
| 1 | [2302.12173](https://arxiv.org/abs/2302.12173) | 19 |
| 2 | [2211.09527](https://arxiv.org/abs/2211.09527) | 14 |
| 3 | [2307.15043](https://arxiv.org/abs/2307.15043) | 12 |
| 4 | [2203.02155](https://arxiv.org/abs/2203.02155) | 11 |
| 5 | [2310.12815](https://arxiv.org/abs/2310.12815) | 11 |
| 6 | [2312.17673](https://arxiv.org/abs/2312.17673) | 7 |
| 7 | [2309.00614](https://arxiv.org/abs/2309.00614) | 7 |
| 8 | [2407.21783](https://arxiv.org/abs/2407.21783) | 6 |
| 9 | [2404.13208](https://arxiv.org/abs/2404.13208) | 6 |
| 10 | [2403.03792](https://arxiv.org/abs/2403.03792) | 6 |
| 11 | [2312.14197](https://arxiv.org/abs/2312.14197) | 6 |
| 12 | [2311.01011](https://arxiv.org/abs/2311.01011) | 6 |
| 13 | [2209.02128](https://arxiv.org/abs/2209.02128) | 6 |
| 14 | [2403.17710](https://arxiv.org/abs/2403.17710) | 6 |
| 15 | [2504.11358](https://arxiv.org/abs/2504.11358) | 6 |

---

*Built with [harness-engineering](https://github.com/nickmccarty/ollama-pi-harness) · /lit-review skill*