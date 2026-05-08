# Reading Scripts — TTS Dataset

Each passage is one recording. Read naturally, at your normal pace. Pauses are fine.

---

## 1. The harness as product

The core insight behind this project is that the model is a commodity and the harness is the product. Anyone can pull a model from Hugging Face or Ollama. What you can't pull is the evaluation loop, the memory system, the structured trace format, or the fine-tuning pipeline that closes the feedback cycle. Those take time to build and they compound. Every run that goes through Wiggum generates a preference signal. Every preference signal improves the next checkpoint. The model gets better because the scaffolding around it gets better, not the other way around.

---

## 2. On evaluator separation

One of the non-negotiable principles here is that the evaluator and the producer have to be different models. If you let the same model grade its own output, you get circular self-reinforcement. The model learns to produce whatever pattern its own grader rewards, which is usually confident-sounding text with good surface structure and very little actual content. Separation forces the grader to be adversarial in a healthy way. It catches completeness failures, factual drift, and shallow synthesis that a same-model evaluator would wave through.

---

## 3. Leverage as a metric

There's a metric I've been thinking about called leverage. The rough definition is: how much value did this run deliver, relative to the human time it consumed? A run that produces a thorough literature review in four minutes has extremely high leverage. A run that spends twenty minutes re-fetching the same three sources under different query phrasings has near-zero leverage even if the final Wiggum score looks acceptable. The distinction matters for fine-tuning. If you only optimize for quality scores, you reward verbosity and oversearch. If you add leverage as a signal, you start rewarding efficiency, and the model learns to stop when it has enough.

---

## 4. The self-improvement loop

The long-term goal is a loop that closes without human intervention. The proposer generates a variation on the synthesis instructions or the search configuration. The executor runs a batch of eval tasks against that variation. The critic scores the results using typed event telemetry from the run trace, not just a scalar. If the variation wins, it gets promoted. If it loses, it gets discarded and the proposer tries something else. Humans set the goal and approve promotions. Everything between is autonomous. That's the design. We're not all the way there yet, but the scaffolding exists. The main gap is closing the manual handoffs.

---

## 5. On sliding window attention

One thing I ran into recently is that the model I'm running locally uses sliding window attention, which means the key-value cache doesn't persist across requests the way you'd expect. Every time a new request comes in, the server has to reprocess the full context from scratch. That's a fundamental architectural constraint, not a configuration issue. The workaround is either to switch to a model that doesn't use sliding window attention, or to move to vLLM which handles the cache differently. For now it just means latency is higher than it would be on a standard attention model, and there's no prefix caching benefit across calls.

---

## 6. On parallel annotation

The annotation step in the literature review pipeline used to be the bottleneck. Sixty papers, fifteen seconds each, sequential. You'd wait fifteen minutes before synthesis even started. The fix was straightforward: the papers are completely independent, so you can fan them out across a thread pool. Each thread handles one paper, calls the model, writes its result into an indexed slot. A lock protects the shared token counter. When all the futures resolve, you stitch the results back together in the original order. Wall time dropped by about half at two parallel workers. The limiting factor now is how many parallel slots the inference server can handle without degrading per-request latency.

---

## 7. Wiggum dimensions

The evaluator grades on six dimensions: relevance, completeness, depth, groundedness, specificity, and structure. Each dimension gets a weight, and the weighted sum is the round score. Groundedness is the one that catches hallucinations. It asks whether the claims in the output are traceable back to the sources that were actually retrieved. Specificity catches outputs that are technically accurate but too vague to be useful. Structure catches formatting issues, missing sections, and logical gaps. The model gets multiple rounds to improve. If the score goes up, it keeps going. If it plateaus or cycles, it stops and returns the best round. That cycling detection was important. Without it, the model would sometimes oscillate between two versions without ever converging.

---

## 8. Building memory into the loop

The semantic memory system stores high-quality past outputs indexed by embedding. When a new task comes in, it retrieves the closest matches by cosine similarity, weighted by their historical Wiggum scores. So the memory isn't just a lookup. It's a quality-filtered cache. A run that scored poorly gets low weight even if its embedding is close to the query. The effect is that over time, the system stops rediscovering things it already knows and starts building on prior work. That's the compounding dynamic I mentioned earlier. The first run on a topic does the heavy lifting. Every subsequent run on a related topic starts from a higher floor.

---

## 9. On voice cloning and data

The irony of building a voice cloning pipeline is that the hardest part is the data. The model architecture is well-understood, the training loop is well-documented, the tooling exists. What you actually need is clean, timestamped, transcribed recordings of the target voice, across enough phonetic variety that the model can learn the full character of the voice and not just a few common patterns. Short recordings are fine as long as there are enough of them. A two-minute audio note with twenty well-segmented utterances is more useful than a single ten-minute monologue with long pauses and background noise. The transcription quality matters too. A single word error in the text label will teach the model the wrong mapping.

---

## 10. On local inference

Running everything locally changes the economics in ways that aren't obvious until you've done it for a while. There's no per-token cost, so you stop rationing context and start using it. You stop worrying about whether a particular prompt pattern will hit a content filter. Latency is predictable because it's just your hardware. The tradeoff is that model quality is bounded by what fits in your VRAM, and you're responsible for your own uptime. But for a research loop where you're running hundreds of experiments and iterating on prompts constantly, the local setup is just strictly better. The economics only favor the API when you need models larger than what you can run, or when you need to scale horizontally in ways that aren't practical on a single machine.
