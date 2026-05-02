# Literature Review: agentic llm tool use planning

*Generated 2026-05-01 08:44 · 15 fetched · 15 annotated*

---

## Overview

The literature review on LLM-driven planning and scheduling reveals a growing body of research that integrates large language models with various planning techniques to enhance automated planning systems. The studies emphasize the importance of combining LLMs with traditional symbolic planners, incorporating metacognitive frameworks for safety, and leveraging domain-specific knowledge representation to improve plan generation and task completion rates. These approaches demonstrate the potential of LLMs in creating more efficient and robust planning solutions.

---

## 1. LLM-Driven Planning and Scheduling

The papers collectively explore the integration of large language models (LLMs) into automated planning and scheduling systems, focusing on techniques like NL2Plan for generating PDDL tasks from minimal text descriptions, CATP-LLM for cost-aware tool planning, and PEARL for plan exploration and adaptive reinforcement learning. They highlight the importance of combining LLMs with traditional symbolic planners, as well as incorporating metacognitive frameworks to enhance planning quality and address safety concerns in user-mediated attacks.

**Hub paper**: [NL2Plan: Robust LLM-Driven Planning from Minimal Text Descriptions](https://arxiv.org/abs/2405.04215v2) — cited by 1 paper in this corpus

### NL2Plan: Robust LLM-Driven Planning from Minimal Text Descriptions

*[2405.04215v2](https://arxiv.org/abs/2405.04215v2) · 2024-05-07 · cited ×1 · score 10.0/10*

**Topic**: The paper addresses the challenge of bridging the gap between classical automated planning and natural language understanding by automating the generation of Planning Domain Definition Language (PDDL) from text.

**Motivation**: Classical planners require tedious and error-prone manual modeling, while LLMs allow for flexible text input but lack guarantees on plan quality or soundness, creating a need for a system that combines flexibility with reliability.

**Contribution**: We introduce NL2Plan, the first fully automatic system that generates complete PDDL tasks (both domain and problem) from minimal natural language descriptions without expert input or domain-specific adaptations.

**Evidence**: Experiments across seven planning domains, including five novel ones excluded from LLM training data, demonstrate that NL2Plan outperforms direct LLM generation combined with a validator.

**Narrow impact**: NL2Plan serves as a powerful tool for assistive PDDL modeling, significantly reducing the manual effort required to convert natural language descriptions into formal planning problems.

**Broad impact**: This work represents a step toward solving natural language planning tasks with interpretability and soundness guarantees, merging the accessibility of LLMs with the rigor of classical planning systems.

**Limitations**: The text does not explicitly detail specific conditions where the approach underperforms, though it notes that previous LLM-aided methods still required varying degrees of expert input or domain-specific adaptations.

### Chasing Progress, Not Perfection: Revisiting Strategies for End-to-End LLM Plan Generation

*[2412.10675v1](https://arxiv.org/abs/2412.10675v1) · 2024-12-14 · score 10.0/10*

**Topic**: This paper addresses the ongoing debate regarding the effectiveness of strategies designed to boost Large Language Models' (LLMs) planning capabilities. It specifically evaluates end-to-end planning strategies using diverse metrics to assess plan quality and validity.

**Motivation**: The study is motivated by conflicting reports in the literature, where some critics claim reasoning-boosting strategies are ineffective while others suggest simple training on planning corpora yields strong results. There is a need to clarify whether these methods genuinely improve robust planning skills or merely offer marginal gains.

**Contribution**: The authors develop an end-to-end LLM planner and introduce a novel `Longest Contiguous Common Subsequence' reward for reinforcement learning. They propose a thorough evaluation framework that distinguishes between plan validity and executability to reassess recent planning strategies.

**Evidence**: Empirical findings indicate that reinforcement learning with the proposed `Longest Contiguous Common Subsequence' reward is the most effective strategy, contributing to improvements in both plan validity and executability. This contrasts with standard fine-tuning, which showed poor performance on generalization tasks.

**Narrow impact**: Immediate takeaways suggest that future planning strategies should simultaneously target both validity and executability rather than focusing on one aspect alone. Developers can leverage the new reward mechanism to achieve more balanced improvements in LLM planner performance.

**Broad impact**: This work addresses key misconceptions in the LLM-planning literature by validating the value of incremental progress in plan executability. It guides the broader community toward more nuanced evaluation metrics and targeted training objectives for robust LLM reasoning.

**Limitations**: The approach faces the limitation that plan validity remains a significant challenge despite improvements in executability. The study notes that current strategies do not directly enhance the final validity rate, indicating that incremental progress does not fully solve the core planning reliability issue.

### Learning to Plan with Natural Language

*[2304.10464v4](https://arxiv.org/abs/2304.10464v4) · 2023-04-20 · score 10.0/10*

**Topic**: The paper addresses the challenge of guiding Large Language Models (LLMs) through complex tasks by generating high-quality, step-by-step plans that minimize factual errors and incompleteness.

**Motivation**: Existing methods where LLMs directly generate plans often result in errors or gaps, necessitating a more robust approach to ensure correct solutions and effective behavioral instructions for error avoidance.

**Contribution**: The authors propose the Learning to Plan method, which utilizes a two-phase process to iteratively refine task plans using feedback from training errors before applying them during inference.

**Evidence**: The method demonstrates effectiveness across five different reasoning types involving eight datasets, and analysis reveals that plans learned by one LLM can transfer to and improve the performance of another LLM.

**Narrow impact**: The immediate takeaway is a refined mechanism for generating and utilizing natural language plans that can serve as a standardized guide for LLM inference on complex reasoning tasks.

**Broad impact**: The work introduces a new transfer learning paradigm for LLMs and releases the code publicly, potentially advancing the development of reliable, plan-guided reasoning systems in the broader AI community.

**Limitations**: The text does not explicitly detail specific failure cases or conditions where the approach underperforms, focusing instead on the successful transfer learning paradigm and overall effectiveness.

### Before you <think>, monitor: Implementing Flavell's metacognitive framework in LLMs

*[2510.16374v1](https://arxiv.org/abs/2510.16374v1) · 2025-10-18 · score 10.0/10*

**Topic**: The paper addresses the separation of reasoning strategies in Large Language Models (LLMs), specifically critiquing the isolation between Monitor-Generate and Generate-Verify paradigms. It proposes a unified three-phase iterative system based on Flavell's cognitive monitoring model to integrate strategic planning with verification.

**Motivation**: Current approaches suffer from inefficiencies where strategies fail without feedback or refinement occurs without strategic grounding. The authors argue that this separation creates gaps in reasoning quality and operational effectiveness that need to be bridged.

**Contribution**: The authors propose implementing Flavell's metacognitive framework within the broader Monitor-Generate-Verify structure to create a cohesive reasoning system. This approach operationalizes cognitive monitoring as a distinct phase preceding generation to improve initial solution quality.

**Evidence**: Preliminary results on GSM8K demonstrate 75.42% accuracy, outperforming SELF-REFINE (68.44%) and Self-Verification (67.07%). The method also requires fewer refinement attempts (1.3 vs 2.0), despite a 27-37% increase in inference cost, suggesting higher-quality initial solutions.

**Narrow impact**: The framework offers immediate takeaways for improving reasoning efficiency on mathematical tasks by reducing the need for iterative refinement. It provides a specific structural alternative to existing isolated paradigms that fail to assess tasks before generation.

**Broad impact**: This work suggests that integrating metacognitive monitoring can systematically improve LLM reasoning by aligning generation with strategic assessment. It points toward more robust, generalizable reasoning frameworks that account for the full cycle of planning, generation, and verification.

**Limitations**: The study acknowledges that evaluation is currently limited to arithmetic reasoning, noting that generalizability beyond this domain remains to be established. The increased inference cost is also noted as a trade-off for the improved accuracy and reduced attempts.

### On the Prospects of Incorporating Large Language Models (LLMs) in Automated Planning and Scheduling (APS)

*[2401.02500v2](https://arxiv.org/abs/2401.02500v2) · 2024-01-04 · cited ×1 · score 9.7/10*

**Topic**: The paper investigates the application of Large Language Models within the field of Automated Planning and Scheduling (APS). It reviews how LLMs are currently utilized to address various aspects of planning problems.

**Motivation**: The growing popularity of LLMs in AI creates a need to systematically understand their role in planning. The authors aim to identify existing gaps and articulate the issues considered across different application categories.

**Contribution**: The authors present a comprehensive review of 126 papers, categorizing LLM applications into eight distinct areas such as language translation, plan generation, and model construction. They propose a neuro-symbolic approach that integrates LLMs with traditional symbolic planners as the optimal path forward.

**Evidence**: The findings are grounded in a systematic analysis of 126 existing papers in the field. The review provides a critical insight that true potential is realized only through effective integration rather than standalone LLM usage.

**Narrow impact**: This work serves as a reference for researchers analyzing specific LLM applications like heuristics optimization or interactive planning. It provides a structured taxonomy for understanding current gaps and issues in these eight categories.

**Broad impact**: The paper advocates for the ICAPS community to recognize the complementary strengths of LLMs and symbolic planners. It aims to steer the development of more advanced and intelligent planning systems through this neuro-symbolic direction.

**Limitations**: The text implies that standalone LLM usage lacks the necessary precision for complex planning tasks compared to symbolic methods. It highlights that current literature may not fully exploit the synergistic potential of combining generative and symbolic systems.

### CATP-LLM: Empowering Large Language Models for Cost-Aware Tool Planning

*[2411.16313v3](https://arxiv.org/abs/2411.16313v3) · 2024-11-25 · score 9.7/10*

**Topic**: This paper addresses the problem of tool planning for large language models (LLMs), specifically focusing on the challenge of optimizing both task performance and tool execution costs such as time.

**Motivation**: Prior research has overlooked tool execution costs, leading to expensive plans where the financial or temporal resource expenditure outweighs the benefits in task performance.

**Contribution**: The authors propose CATP-LLM, a framework that empowers LLMs to perform cost-aware tool planning for the first time, introducing a coherent design to balance performance and cost.

**Evidence**: Experiments demonstrate that CATP-LLM outperforms GPT-4 even when using the smaller Llama2-7B backbone, achieving average improvements of 1.5% to 93.9% in plan quality.

**Narrow impact**: This work provides immediate practical benefits by enabling more efficient concurrent tool execution and reducing costs in AI systems that rely on external tools.

**Broad impact**: The release of the OpenCATP dataset and codebase supports the broader community by providing resources for developing cost-aware planning capabilities in general AI systems.

**Limitations**: The study notes a lack of public cost-related datasets, necessitating the creation of the OpenCATP dataset comprising 11,100 evaluation samples to facilitate research in this area.

### PEARL: Plan Exploration and Adaptive Reinforcement Learning for Multihop Tool Use

*[2601.20439v1](https://arxiv.org/abs/2601.20439v1) · 2026-01-28 · score 9.7/10*

**Topic**: This paper addresses the challenges Large Language Models face in complex, multi-turn tool invocation, specifically regarding planning, tool hallucination, and robust interaction. It focuses on improving the planning and execution capabilities of LLMs when using external tools in sophisticated scenarios.

**Motivation**: Existing LLMs often exhibit weak planning, tool hallucination, and erroneous parameter generation, leading to struggles with robust interaction during multi-step tasks. These limitations hinder the effective use of external tools in complex environments, creating a need for more reliable planning and execution frameworks.

**Contribution**: We present PEARL, a novel framework that enhances LLM planning and execution through a two-stage approach consisting of offline tool exploration and online reinforcement learning. The core contribution involves a dedicated Planner trained via group Relative Policy Optimization (GRPO) with a custom reward function designed to provide distinct signals for planning quality.

**Evidence**: Experiments on the ToolHop and T-Eval benchmarks demonstrate that PEARL significantly outperforms existing methods, achieving a new state-of-the-art success rate of 56.5% on ToolHop. Additionally, the framework maintains a low invocation error rate, confirming its effectiveness in practical tool-use scenarios.

**Narrow impact**: The framework offers immediate takeaways for developing more robust and reliable LLM-based agents by addressing specific planning challenges in tool use. It provides a proven methodology for enhancing agent performance on complex, multi-step tasks through structured exploration and reinforcement learning.

**Broad impact**: This work contributes to the broader development of more robust and reliable LLM-based agents by marking a key advance in addressing complex planning challenges. It underscores the importance of adaptive reinforcement learning in overcoming current limitations in tool-use capabilities for large language models.

**Limitations**: The provided text does not explicitly detail specific limitations or conditions where the approach underperforms, nor does it discuss open problems regarding the method's scalability or robustness beyond the stated benchmarks.

### Too Helpful to Be Safe: User-Mediated Attacks on Planning and Web-Use Agents

*[2601.10758v1](https://arxiv.org/abs/2601.10758v1) · 2026-01-14 · score 9.3/10*

**Topic**: The paper investigates user-mediated attacks on commercial Large Language Model agents, specifically focusing on how benign users can inadvertently relay untrusted content to trip-planning and web-use agents. It examines the security vulnerabilities arising from agents acting on user-provided content rather than direct interface abuse.

**Motivation**: Existing security studies overlook attacks that exploit users as unintended conduits by focusing mainly on model-internal vulnerabilities or adversarial access. This gap leaves a critical need to understand how the inherent "helpfulness" of agents introduces security risks when they process untrusted data passed through users.

**Contribution**: The authors introduce a systematic evaluation of 12 commercial agents in a sandboxed environment to analyze how they respond to user-mediated attacks. They compare agent behavior across scenarios involving no, soft, and hard user-requested safety checks to identify patterns of constraint bypassing.

**Evidence**: Without explicit safety requests, trip-planning agents bypassed safety constraints in over 92% of cases, while web-use agents showed near-deterministic execution of risky actions with up to a 100% bypass rate. Even with soft or hard safety intents, bypass rates remained substantial at up to 54.7% and 7% respectively for trip-planning agents.

**Narrow impact**: These results provide immediate takeaways for developers of planning and web-use agents regarding the necessity of explicit safety prompts. It highlights that current agents cannot be trusted to execute tasks safely without rigorous user intervention to enforce safety boundaries.

**Broad impact**: The paper demonstrates that the primary security issue is the prioritization of helpfulness, suggesting that future agent designs must balance task execution with robust, default safety protocols. This shifts the field's understanding of agent security from internal model vulnerabilities to the external risk of user-mediated exploitation.

**Limitations**: The findings indicate that agents frequently over-execute workflows due to a lack of clear stopping rules, leading to unnecessary data disclosure. This suggests a fundamental limitation where the prioritization of helpfulness over safety creates conditions for real-world harm even when safety mechanisms are present.

## 2. Tool and Knowledge Integration in Planning

The papers collectively explore innovative approaches to enhancing large language models (LLMs) in tool planning and execution tasks. They introduce graph-based frameworks for constructing knowledge graphs, a novel Monte Carlo Tree Search-inspired method for efficient LLM agent tool planning, and a bidirectional framework that combines LLM planning with Deep Reinforcement Learning. These techniques demonstrate significant improvements in plan generation performance, task completion rates, and tool retrieval ability, highlighting the synergy between domain-specific knowledge representation and advanced planning algorithms.


### Retrieval Models Aren't Tool-Savvy: Benchmarking Tool Retrieval for Large Language Models

*[2503.01763v2](https://arxiv.org/abs/2503.01763v2) · 2025-03-03 · score 10.0/10*

**Topic**: This paper addresses the challenge of tool retrieval for large language models (LLMs) acting as agents, specifically focusing on the gap between limited context windows and the need to select useful tools from large sets.

**Motivation**: The authors argue that current benchmarks rely on artificially pre-annotated small tool sets, which fails to represent real-world scenarios where models must retrieve tools from massive corpora using information retrieval (IR) methods.

**Contribution**: The authors introduce ToolRet, a heterogeneous benchmark featuring 7.6k diverse retrieval tasks and a corpus of 43k tools, alongside a large-scale training dataset of over 200k instances to improve model performance.

**Evidence**: Empirical results demonstrate that poor retrieval quality directly degrades the task pass rate of tool-using LLMs, but fine-tuning on the proposed 200k-instance dataset substantially optimizes their tool retrieval ability.

**Narrow impact**: This work provides a more realistic evaluation framework for tool-use agents and a training dataset that can be used to specifically enhance the tool selection capabilities of IR models.

**Broad impact**: By exposing the disconnect between conventional IR performance and tool-use requirements, the paper motivates the development of more robust, tool-aware retrieval systems for practical LLM applications.

**Limitations**: The paper highlights that existing IR models, despite their success in conventional benchmarks, fundamentally lack the capability to effectively retrieve tools for LLM agents without specialized training.

### ToolTree: Efficient LLM Agent Tool Planning via Dual-Feedback Monte Carlo Tree Search and Bidirectional Pruning

*[2603.12740v1](https://arxiv.org/abs/2603.12740v1) · 2026-03-13 · score 9.7/10*

**Topic**: This paper addresses the challenge of tool planning for Large Language Model (LLM) agents performing complex, multi-step tasks that require interaction with diverse external tools. It specifically targets the limitations of current greedy, reactive strategies that fail to account for inter-tool dependencies.

**Motivation**: Existing LLM agent tool planning methods often lack foresight and cannot effectively handle the dependencies between tools. This limitation hinders their ability to make informed decisions over extended sequences of tool usage.

**Contribution**: The authors introduce ToolTree, a novel planning paradigm inspired by Monte Carlo Tree Search designed for tool planning. This method enables agents to explore tool usage trajectories and make adaptive decisions across extended sequences.

**Evidence**: Empirical evaluations across four benchmarks in both open-set and closed-set tool planning tasks show consistent performance improvements. The method maintains high efficiency while achieving an average gain of approximately 10% compared to state-of-the-art planning paradigms.

**Narrow impact**: This approach immediately benefits applications requiring complex, multi-step interactions with diverse external tools across various domains. It offers a more robust alternative to reactive strategies for tasks demanding foresight into tool dependencies.

**Broad impact**: By improving the efficiency and accuracy of LLM agent planning, this work supports the broader development of autonomous agents capable of handling complex workflows. The demonstrated gains suggest a pathway toward more reliable and scalable tool-use strategies in AI systems.

**Limitations**: The provided text does not explicitly detail conditions where the approach underperforms or specific limitations regarding computational overhead. However, the emphasis on maintaining "highest efficiency" suggests a focus on balancing performance with resource constraints typical of search-based methods.

### SCALAR: Learning and Composing Skills through LLM Guided Symbolic Planning and Deep RL Grounding

*[2603.09036v1](https://arxiv.org/abs/2603.09036v1) · 2026-03-10 · score 9.7/10*

**Topic**: The paper addresses the challenge of grounding high-level language instructions into low-level control for LLM-based agents, specifically tackling the difficulty of translating abstract skills into executable robotic or game actions.

**Motivation**: Prior methods rely on one-shot approaches where LLMs generate skills or rewards without feedback, leading to specification errors that cannot be corrected during execution. This lack of iterative correction limits the robustness and reliability of agents in complex environments.

**Contribution**: We introduce SCALAR, a bidirectional framework that couples LLM planning with Deep Reinforcement Learning (RL) via a learned skill library, allowing for continuous refinement of skill specifications. This approach enables the LLM to propose skills with preconditions and effects, which are then trained by RL and refined based on execution feedback.

**Evidence**: On the Craftax benchmark, SCALAR achieves an 88.2% diamond collection rate, representing a 1.9x improvement over the best baseline, and reaches the Gnomish Mines 9.1% of the time where prior methods fail entirely. These results demonstrate significant performance gains in both success rates and task completion in challenging environments.

**Narrow impact**: The framework provides immediate takeaways for systems requiring robust translation of symbolic plans into continuous control, such as in complex simulation environments like Craftax. It offers a reusable skill library mechanism that can be applied to other domains requiring iterative learning and refinement.

**Broad impact**: This work advances the field of embodied AI by demonstrating how iterative feedback between high-level planning and low-level control can overcome the brittleness of one-shot LLM methods. It suggests a pathway toward more robust and generalizable agents capable of learning and composing skills in open-ended environments.

**Limitations**: The provided text does not explicitly detail specific conditions where SCALAR underperforms or lists open problems, focusing instead on its improvements over prior methods. However, the reliance on LLM-generated preconditions implies potential sensitivity to initial specification quality before the feedback loop corrects them.

### Bridging Tool Dependencies and Domain Knowledge: A Graph-Based Framework for In-Context Planning

*[2510.24690v1](https://arxiv.org/abs/2510.24690v1) · 2025-10-28 · score 9.4/10*

**Topic**: The paper addresses the problem of enhancing exemplar artifact generation in tool-augmented reasoning by effectively managing dependencies between tools and domain-specific documents.

**Motivation**: The work is driven by the need to uncover and exploit structural dependencies among tools and internal documentation to improve the quality and coherence of generated plans.

**Contribution**: The authors propose a unified graph-based framework that constructs and fuses a tool knowledge graph derived from API schemas with a domain knowledge graph derived from internal documents and SOPs.

**Evidence**: Experiments demonstrate that the framework effectively models complex tool interactions and significantly improves plan generation performance compared to baselines.

**Narrow impact**: The framework provides a concrete mechanism for integrating technical tool schemas with organizational standard operating procedures to generate more coherent exemplar plans.

**Broad impact**: This approach underscores the broader importance of linking structural tool dependencies with domain knowledge graphs to advance reliable tool-augmented reasoning and planning systems.

**Limitations**: The provided text does not explicitly detail specific failure modes or conditions where the approach underperforms, focusing primarily on the demonstrated benefits of the proposed method.

## 3. LLM Frameworks and Evaluation

The papers collectively focus on enhancing language models' tool learning capabilities through modular frameworks and advanced planning techniques. They propose distinct approaches such as decomposing tool-use into planner, caller, and summarizer components (Multi-LLM Agent), converting feedback into retrievable guidelines for memory-based systems (Memory-as-a-Tool), using dual-feedback Monte Carlo Tree Search for efficient tool planning (ToolTree), and benchmarking retrieval models to improve tool usage in LLMs (ToolRet). These methods collectively aim to optimize the performance of language models in tool learning tasks, showcasing their interrelatedness through shared goals and techniques.


### Retrieval Models Aren't Tool-Savvy: Benchmarking Tool Retrieval for Large Language Models

*[2503.01763v2](https://arxiv.org/abs/2503.01763v2) · 2025-03-03 · score 10.0/10*

**Topic**: This paper addresses the challenge of tool retrieval for large language models (LLMs) acting as agents, specifically focusing on the gap between limited context windows and the need to select useful tools from large sets.

**Motivation**: The authors argue that current benchmarks rely on artificially pre-annotated small tool sets, which fails to represent real-world scenarios where models must retrieve tools from massive corpora using information retrieval (IR) methods.

**Contribution**: The authors introduce ToolRet, a heterogeneous benchmark featuring 7.6k diverse retrieval tasks and a corpus of 43k tools, alongside a large-scale training dataset of over 200k instances to improve model performance.

**Evidence**: Empirical results demonstrate that poor retrieval quality directly degrades the task pass rate of tool-using LLMs, but fine-tuning on the proposed 200k-instance dataset substantially optimizes their tool retrieval ability.

**Narrow impact**: This work provides a more realistic evaluation framework for tool-use agents and a training dataset that can be used to specifically enhance the tool selection capabilities of IR models.

**Broad impact**: By exposing the disconnect between conventional IR performance and tool-use requirements, the paper motivates the development of more robust, tool-aware retrieval systems for practical LLM applications.

**Limitations**: The paper highlights that existing IR models, despite their success in conventional benchmarks, fundamentally lack the capability to effectively retrieve tools for LLM agents without specialized training.

### ToolTree: Efficient LLM Agent Tool Planning via Dual-Feedback Monte Carlo Tree Search and Bidirectional Pruning

*[2603.12740v1](https://arxiv.org/abs/2603.12740v1) · 2026-03-13 · score 9.7/10*

**Topic**: This paper addresses the challenge of tool planning for Large Language Model (LLM) agents performing complex, multi-step tasks that require interaction with diverse external tools. It specifically targets the limitations of current greedy, reactive strategies that fail to account for inter-tool dependencies.

**Motivation**: Existing LLM agent tool planning methods often lack foresight and cannot effectively handle the dependencies between tools. This limitation hinders their ability to make informed decisions over extended sequences of tool usage.

**Contribution**: The authors introduce ToolTree, a novel planning paradigm inspired by Monte Carlo Tree Search designed for tool planning. This method enables agents to explore tool usage trajectories and make adaptive decisions across extended sequences.

**Evidence**: Empirical evaluations across four benchmarks in both open-set and closed-set tool planning tasks show consistent performance improvements. The method maintains high efficiency while achieving an average gain of approximately 10% compared to state-of-the-art planning paradigms.

**Narrow impact**: This approach immediately benefits applications requiring complex, multi-step interactions with diverse external tools across various domains. It offers a more robust alternative to reactive strategies for tasks demanding foresight into tool dependencies.

**Broad impact**: By improving the efficiency and accuracy of LLM agent planning, this work supports the broader development of autonomous agents capable of handling complex workflows. The demonstrated gains suggest a pathway toward more reliable and scalable tool-use strategies in AI systems.

**Limitations**: The provided text does not explicitly detail conditions where the approach underperforms or specific limitations regarding computational overhead. However, the emphasis on maintaining "highest efficiency" suggests a focus on balancing performance with resource constraints typical of search-based methods.

### Small LLMs Are Weak Tool Learners: A Multi-LLM Agent

*[2401.07324v3](https://arxiv.org/abs/2401.07324v3) · 2024-01-14 · score 9.3/10*

**Topic**: This paper addresses the challenge of tool learning for Large Language Model (LLM) agents, specifically focusing on the difficulties smaller models face when required to perform task planning, tool invocation, and result summarization simultaneously.

**Motivation**: Traditional approaches that train a single LLM to handle all tool-use capabilities exhibit performance limitations, particularly when using smaller model sizes that struggle with the complexity of these combined tasks.

**Contribution**: The authors propose a novel modular framework that decomposes tool-use capabilities into three distinct components—a planner, a caller, and a summarizer—each implemented by a separate LLM instance.

**Evidence**: Evaluations across various tool-use benchmarks demonstrate that this proposed multi-LLM framework surpasses traditional single-LLM approaches, highlighting its efficacy and advantages in tool learning.

**Narrow impact**: This modular approach facilitates individual updates to specific components and enables the use of smaller LLMs to build each distinct capability, offering a more flexible and scalable alternative to monolithic agents.

**Broad impact**: By demonstrating that decomposing complex agent behaviors into specialized sub-tasks improves performance, the work provides a viable path for enhancing the capabilities of smaller, potentially more efficient language models in real-world tool-interaction scenarios.

**Limitations**: The paper explicitly identifies that traditional single-LLM approaches suffer from performance limitations, particularly when using smaller models that cannot effectively manage the full scope of tool-use requirements.

### Distilling Feedback into Memory-as-a-Tool

*[2601.05960v2](https://arxiv.org/abs/2601.05960v2) · 2026-01-09 · score 9.3/10*

**Topic**: The paper focuses on optimizing inference-time reasoning in large language models by addressing the high computational costs associated with real-time refinement. It explores methods to make reasoning processes more efficient through memory-based approaches.

**Motivation**: The primary driver is the need to amortize the significant cost of inference-time reasoning. Current methods often incur high expenses during the reasoning phase, prompting a search for more cost-effective alternatives.

**Contribution**: The authors introduce a framework that converts transient critiques into retrievable guidelines using a file-based memory system and agent-controlled tool calls. This approach aims to reduce inference costs while maintaining performance levels comparable to test-time refinement pipelines.

**Evidence**: Evaluation on the Rubric Feedback Bench, a novel dataset for rubric-based learning, shows that the augmented LLMs rapidly match the performance of test-time refinement pipelines. Crucially, this is achieved while drastically reducing the associated inference costs.

**Narrow impact**: The work directly impacts the efficiency of LLMs in tasks requiring iterative refinement and rubric-based learning. It offers a viable alternative to expensive test-time refinement methods for applications where cost and speed are critical factors.

**Broad impact**: By reducing the cost of inference-time reasoning, this framework supports the development of more scalable and efficient AI systems. It contributes to the broader goal of making advanced reasoning capabilities more accessible and sustainable in practical applications.

**Limitations**: The abstract does not explicitly detail specific limitations or weaker results, though the reliance on a file-based memory system implies potential constraints related to memory management or the specific structure of the rubric feedback bench used for evaluation.


---

## Open Questions

- How can the integration of LLMs with symbolic planners be optimized to ensure both efficiency and robustness against adversarial attacks?
- What are the limitations of current graph-based frameworks for constructing knowledge graphs, and how can these be addressed to improve tool retrieval ability?
- In what ways can dual-feedback Monte Carlo Tree Search be further refined to enhance the efficiency of LLM agent tool planning?
- How do different modular frameworks for LLMs impact the overall performance in tool learning tasks, and which framework is most suitable for specific types of planning problems?
- What are the long-term implications of using memory-based systems (Memory-as-a-Tool) for feedback integration, and how can these systems be scaled to handle more complex planning scenarios?

---

## Gap Candidates

Papers heavily cited within this corpus but not yet annotated:

| # | arXiv ID | Cited by |
|---|----------|----------|
| 1 | [2005.14165](https://arxiv.org/abs/2005.14165) | 9 |
| 2 | [2307.09288](https://arxiv.org/abs/2307.09288) | 7 |
| 3 | [2303.17651](https://arxiv.org/abs/2303.17651) | 7 |
| 4 | [2302.04761](https://arxiv.org/abs/2302.04761) | 6 |
| 5 | [2210.03629](https://arxiv.org/abs/2210.03629) | 6 |
| 6 | [2305.15334](https://arxiv.org/abs/2305.15334) | 5 |
| 7 | [2303.04671](https://arxiv.org/abs/2303.04671) | 5 |
| 8 | [2201.11903](https://arxiv.org/abs/2201.11903) | 5 |
| 9 | [2203.11171](https://arxiv.org/abs/2203.11171) | 5 |
| 10 | [2201.07207](https://arxiv.org/abs/2201.07207) | 5 |
| 11 | [2305.18752](https://arxiv.org/abs/2305.18752) | 4 |
| 12 | [2205.11916](https://arxiv.org/abs/2205.11916) | 4 |
| 13 | [2303.17580](https://arxiv.org/abs/2303.17580) | 4 |
| 14 | [2302.13971](https://arxiv.org/abs/2302.13971) | 4 |
| 15 | [1709.10256](https://arxiv.org/abs/1709.10256) | 4 |

---

*Built with [harness-engineering](https://github.com/nickmccarty/ollama-pi-harness) · /lit-review skill*