"""
harness/inference.py — unified LLM backend shim.

Drop-in replacement for `import ollama` throughout the harness. Routes calls to
Ollama, vLLM, llama-server, or any OpenAI-compatible endpoint.

Environment variables
---------------------
INFERENCE_BACKEND   "ollama" (default) | "vllm"
VLLM_BASE_URL       vLLM server URL (default: http://localhost:8000/v1)
VLLM_API_KEY        auth key — vLLM ignores this by default ("none")
VLLM_MODEL_MAP      JSON dict overriding the built-in Ollama-tag → served-name map
                    e.g. '{"pi-qwen3.6": "pi-qwen3.6", "pi-qwen-32b": "pi-qwen-32b"}'

Per-model endpoint routing (takes priority over INFERENCE_BACKEND / VLLM_MODEL_MAP):
HARNESS_ENDPOINTS   JSON dict: {"tag": {"url": "...", "model_id": "...", "backend": "..."}}
                    backend: "vllm" (enables Qwen thinking-mode headers) |
                             "llamacpp" | "openai"  (generic OpenAI-compatible, no special headers)
                    Example — vLLM on 8000 + llama-server GGUF on 8001 simultaneously:
                    '{"qwen3-14b": {"url": "http://localhost:8000/v1", "model_id": "qwen3-14b", "backend": "vllm"},
                      "phi4-mini": {"url": "http://localhost:8001/v1", "model_id": "phi-4-mini-q8", "backend": "llamacpp"}}'

Migration
---------
Files using `import ollama` directly:
    - replace with `import harness.inference as ollama`  (chat attribute exists at module level)

Files using the _OllamaShim pattern (agent.py, wiggum.py, autoresearch.py):
    - replace with `from harness.inference import OllamaLike; ollama = OllamaLike(keep_alive=_KEEP_ALIVE)`

Files calling `_ollama_raw.chat(...)` directly (skills, email, lit_review, etc.):
    - replace with `from harness.inference import chat as _llm_chat; _llm_chat(model=..., messages=..., options=...)`

logger.py's _extract_usage() works unchanged — _OllamaResponse exposes the same
attribute names (prompt_eval_count, eval_count, total_duration, eval_duration,
prompt_eval_duration, message.thinking) via getattr.
"""

import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path as _Path
from typing import Any

# Load .env from the repo root before reading any os.environ.get() calls below.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_Path(__file__).parent.parent / ".env", override=False)
except Exception:
    pass

_BACKEND      = os.environ.get("INFERENCE_BACKEND", "ollama").lower()
_VLLM_BASE    = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
_VLLM_API_KEY = os.environ.get("VLLM_API_KEY", "none")

# ---------------------------------------------------------------------------
# Model name translation: Ollama tag → vLLM / HuggingFace model ID
# ---------------------------------------------------------------------------
_MODEL_MAP: dict[str, str] = {
    "pi-qwen3.6":                     "pi-qwen3.6",
    "qwen3.6:35b-a3b":                "pi-qwen3.6",
    "pi-qwen25-14b":                  "pi-qwen25-14b",
    "qwen3-14b":                      "qwen3-14b",
    "pi-qwen3-32b":                   "pi-qwen3-32b",
    "pi-qwen-32b":                    "Qwen/Qwen2.5-32B-Instruct",
    "pi-qwen":                        "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5:32b-instruct-q4_K_M":   "Qwen/Qwen2.5-32B-Instruct",
    "qwen2.5:7b-instruct":            "Qwen/Qwen2.5-7B-Instruct",
    "Qwen3-Coder:30b":                "Qwen/Qwen3-Coder-480B-A22B",
    "gemma4:latest":                  "google/gemma-4-9b-it",
    "gemma4:26b":                     "google/gemma-4-26b-it",
    "glm4:9b":                        "THUDM/glm-4-9b-chat",
    "llama3.2-vision":                "meta-llama/Llama-3.2-11B-Vision-Instruct",
    "llama3.2:3b":                    "meta-llama/Llama-3.2-3B-Instruct",
    "mistral-small3.1:24b":           "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    "phi4:14b":                       "microsoft/phi-4",
    "nomic-embed-text":               "nomic-ai/nomic-embed-text-v1.5",
}

_env_map = os.environ.get("VLLM_MODEL_MAP")
_VLLM_ROUTE: set | None = None
if _env_map:
    try:
        _env_parsed = json.loads(_env_map)
        _MODEL_MAP.update(_env_parsed)
        _VLLM_ROUTE = set(_env_parsed.keys())
    except Exception as _e:
        print(f"  [inference] VLLM_MODEL_MAP parse error: {_e}")

# ---------------------------------------------------------------------------
# Per-model endpoint registry — HARNESS_ENDPOINTS
# ---------------------------------------------------------------------------
_ENDPOINTS: dict[str, dict] = {}
_raw_ep = os.environ.get("HARNESS_ENDPOINTS", "")
if _raw_ep:
    try:
        _ENDPOINTS = json.loads(_raw_ep)
        print(f"  [inference] HARNESS_ENDPOINTS: {list(_ENDPOINTS)}")
    except Exception as _e:
        print(f"  [inference] HARNESS_ENDPOINTS parse error: {_e}")


def _resolve_model(name: str) -> str:
    """Return the vLLM model ID for an Ollama model tag, or the name unchanged."""
    return _MODEL_MAP.get(name, name)


def get_active_vllm_model(base_url: str | None = None) -> str | None:
    """Return the first model ID loaded at base_url (defaults to VLLM_BASE_URL), or None."""
    try:
        import json as _json
        import urllib.request
        root = (base_url or _VLLM_BASE).rstrip("/")
        if not root.endswith("/v1"):
            root += "/v1"
        with urllib.request.urlopen(root + "/models", timeout=3) as r:
            data = _json.loads(r.read())
        models = data.get("data", [])
        return models[0]["id"] if models else None
    except Exception:
        return None


def list_endpoints() -> dict[str, dict]:
    """Return the loaded HARNESS_ENDPOINTS registry (tag → {url, model_id, backend})."""
    return dict(_ENDPOINTS)


# ---------------------------------------------------------------------------
# Ollama-compatible response adapter for OpenAI/vLLM responses
# ---------------------------------------------------------------------------

class _OllamaMessage:
    """
    Adapter: makes an OpenAI ChatCompletionMessage look like an Ollama message.
    Supports both attribute access (response.message.content) and the dict-style
    access used throughout the harness (response["message"]["content"]).
    """
    def __init__(self, oai_message):
        self.role = getattr(oai_message, "role", "assistant") or "assistant"
        raw = getattr(oai_message, "content", "") or ""
        reasoning = getattr(oai_message, "reasoning_content", None) or ""
        if not reasoning:
            m = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
            if m:
                reasoning = m.group(1).strip()
                raw = raw[raw.rfind("</think>") + len("</think>"):].strip()
        self.thinking = reasoning
        self.content  = raw

    @classmethod
    def from_raw(cls, role: str, content: str, thinking: str = "") -> "_OllamaMessage":
        """Build directly from accumulated streaming parts — no parsing needed."""
        obj = cls.__new__(cls)
        obj.role    = role
        obj.content = content
        obj.thinking = thinking
        return obj

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


class _OllamaResponse:
    """
    Wraps vLLM streaming output to look like an Ollama ChatResponse.

    Timing fields come from real wall-clock measurements taken during streaming:
      prompt_eval_duration = time from request start to first content token (TTFT / prefill)
      eval_duration        = time from first token to stream end (generation)
      total_duration       = end-to-end wall time (prompt + eval + overhead)
    """
    def __init__(
        self,
        message:          "_OllamaMessage",
        prompt_tokens:    int,
        completion_tokens: int,
        total_ns:         int,
        prompt_ns:        int,
        eval_ns:          int,
    ):
        self.prompt_eval_count    = prompt_tokens
        self.eval_count           = completion_tokens
        self.total_duration       = total_ns
        self.prompt_eval_duration = prompt_ns
        self.eval_duration        = eval_ns
        self.load_duration        = 0
        self.message              = message

    def __getitem__(self, key):
        if key == "message":
            return self.message
        if key == "prompt_eval_count":
            return self.prompt_eval_count
        if key == "eval_count":
            return self.eval_count
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

def _chat_ollama(model: str, messages: list, **kwargs) -> Any:
    import ollama as _ollama
    options = kwargs.get("options") or {}
    if "think" in options:
        options = dict(options)
        kwargs["think"] = options.pop("think")
        kwargs["options"] = options
    return _ollama.chat(model=model, messages=messages, **kwargs)


def _stream_vllm_call(client, vllm_model: str, messages: list, oai_kwargs: dict):
    """
    Execute one streaming vLLM completion.

    Returns (message, prompt_tokens, completion_tokens, total_ns, prompt_ns, eval_ns).

    Streaming gives us real per-phase timing:
      prompt_ns = TTFT (prefill latency) — time from request dispatch to first content token
      eval_ns   = generation latency — time from first token to stream end
    """
    t0      = time.monotonic_ns()
    t_first = None

    content_parts   = []
    reasoning_parts = []
    prompt_tokens   = 0
    completion_tokens = 0

    stream = client.chat.completions.create(
        model=vllm_model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        **oai_kwargs,
    )

    for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta
            c = delta.content or ""
            r = getattr(delta, "reasoning_content", None) or ""
            if t_first is None and (c or r):
                t_first = time.monotonic_ns()
            if c:
                content_parts.append(c)
            if r:
                reasoning_parts.append(r)
        if getattr(chunk, "usage", None):
            prompt_tokens     = chunk.usage.prompt_tokens     or 0
            completion_tokens = chunk.usage.completion_tokens or 0

    t_end = time.monotonic_ns()
    if t_first is None:
        t_first = t_end

    raw_content = "".join(content_parts)
    reasoning   = "".join(reasoning_parts)

    if not reasoning:
        m = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
        if m:
            reasoning   = m.group(1).strip()
            raw_content = raw_content[raw_content.rfind("</think>") + len("</think>"):].strip()

    msg = _OllamaMessage.from_raw("assistant", raw_content, reasoning)
    return (
        msg,
        prompt_tokens,
        completion_tokens,
        t_end - t0,
        t_first - t0,
        t_end - t_first,
    )


def _chat_vllm(
    model: str,
    messages: list,
    base_url: str = _VLLM_BASE,
    backend: str = "vllm",
    model_id: str | None = None,
    **kwargs,
) -> _OllamaResponse:
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=_VLLM_API_KEY)

    kwargs.pop("keep_alive", None)
    options = kwargs.pop("options", {}) or {}

    oai_kwargs: dict = {}
    if "temperature" in options:
        oai_kwargs["temperature"] = options["temperature"]
    if "num_predict" in options:
        oai_kwargs["max_tokens"] = options["num_predict"]
    if "top_p" in options:
        oai_kwargs["top_p"] = options["top_p"]
    if "presence_penalty" in options:
        oai_kwargs["presence_penalty"] = options["presence_penalty"]
    if "top_k" in options:
        oai_kwargs.setdefault("extra_body", {})["top_k"] = options["top_k"]

    vllm_model = model_id if model_id else _resolve_model(model)
    if backend in ("vllm", "llamacpp") and any(k in vllm_model.lower() for k in ("qwen", "qwq")):
        chat_tmpl: dict = {}
        if "think" in options:
            chat_tmpl["enable_thinking"] = bool(options["think"])
        else:
            chat_tmpl["enable_thinking"] = False
        if "preserve_thinking" in options:
            chat_tmpl["preserve_thinking"] = bool(options["preserve_thinking"])
        eb = oai_kwargs.setdefault("extra_body", {})
        eb["chat_template_kwargs"] = chat_tmpl

    # Retry up to 2× on context-length or server-disconnect errors.
    # Server disconnects (RemoteProtocolError / APIConnectionError) are the vLLM OOM signal.
    # We truncate head (60%) + tail (20%) so both instruction preamble and recent context survive.
    # Never truncate system prompt — truncate the longest non-system message instead.
    _messages = list(messages)
    for attempt in range(3):
        try:
            msg, ptok, ctok, total_ns, prompt_ns, eval_ns = _stream_vllm_call(
                client, vllm_model, _messages, oai_kwargs,
            )
            return _OllamaResponse(msg, ptok, ctok, total_ns, prompt_ns, eval_ns)
        except Exception as exc:
            exc_str = str(exc)
            _is_ctx_err = (
                "maximum context length" in exc_str
                or "exceeds the available context size" in exc_str
                or "exceed_context_size" in exc_str
                or "context_length_exceeded" in exc_str
            )
            _is_disconnect = (
                "Server disconnected" in exc_str
                or "RemoteProtocolError" in exc_str
                or "Connection error" in exc_str
                or "ConnectError" in exc_str
            )
            if (_is_ctx_err or _is_disconnect) and attempt < 2:
                reason = "context too long" if _is_ctx_err else "server disconnect (OOM)"
                if _is_disconnect:
                    print(f"  [inference] waiting for vLLM to recover (up to 120s)…")
                    _t0 = time.monotonic()
                    _recovered = False
                    while time.monotonic() - _t0 < 120:
                        try:
                            import httpx as _httpx
                            _httpx.get(f"{base_url}/health", timeout=4)
                            _recovered = True
                            break
                        except Exception:
                            time.sleep(5)
                    if not _recovered:
                        print("  [inference] vLLM health check timed out — retrying anyway")
                candidates = [
                    (i, len(str(_messages[i].get("content", "") or "")))
                    for i, m in enumerate(_messages)
                    if _messages[i].get("role") != "system"
                ]
                if not candidates:
                    candidates = [(i, len(str(_messages[i].get("content", "") or "")))
                                  for i in range(len(_messages))]
                    print("  [inference] WARNING: only system messages remain — "
                          "truncating system prompt to fit context window")

                longest_idx = max(candidates, key=lambda x: x[1])[0]
                content  = str(_messages[longest_idx].get("content", "") or "")
                keep_head = int(len(content) * 0.60)
                keep_tail = int(len(content) * 0.20)
                truncated = content[:keep_head] + "\n…[truncated]…\n" + content[-keep_tail:]
                _messages[longest_idx] = {**_messages[longest_idx], "content": truncated}
                if "max_tokens" in oai_kwargs:
                    oai_kwargs = dict(oai_kwargs)
                    oai_kwargs["max_tokens"] = max(256, oai_kwargs["max_tokens"] // 2)
                role = _messages[longest_idx].get("role", "?")
                print(f"  [inference] {reason} — truncated {role} msg[{longest_idx}] "
                      f"({len(content)}→{len(truncated)} chars), "
                      f"max_tokens={oai_kwargs.get('max_tokens', '?')}, retry {attempt+1}/2")
            else:
                raise
    raise RuntimeError("_chat_vllm: all retries exhausted without returning")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Optional display hooks — set by op.py via harness_console when running interactively.
_on_inf_start: Callable | None = None   # (label: str) -> None
_on_inf_end:   Callable | None = None   # () -> None
_on_cot:       Callable | None = None   # (thinking: str) -> None


def chat(model: str, messages: list, **kwargs) -> Any:
    """
    Drop-in replacement for ollama.chat().

    Routing priority (highest first):
      1. HARNESS_ENDPOINTS — per-model {url, model_id, backend}
      2. INFERENCE_BACKEND=vllm + VLLM_MODEL_MAP — hybrid vLLM/Ollama routing
      3. INFERENCE_BACKEND=ollama (default) — all calls to local Ollama daemon
    """
    if _on_inf_start:
        _on_inf_start(f"generating  ·  {model}")
    try:
        if model in _ENDPOINTS:
            ep = _ENDPOINTS[model]
            result = _chat_vllm(
                model=model,
                messages=messages,
                base_url=ep["url"],
                backend=ep.get("backend", "openai"),
                model_id=ep.get("model_id"),
                **kwargs,
            )
        elif _BACKEND == "vllm" and (_VLLM_ROUTE is None or model in _VLLM_ROUTE):
            result = _chat_vllm(model=model, messages=messages, **kwargs)
        else:
            result = _chat_ollama(model=model, messages=messages, **kwargs)
    finally:
        if _on_inf_end:
            _on_inf_end()

    thinking = getattr(getattr(result, "message", None), "thinking", None) or ""
    if thinking and _on_cot:
        _on_cot(thinking)
    return result


class OllamaLike:
    """
    Drop-in for the _OllamaShim pattern used in agent.py, wiggum.py, autoresearch.py.

    Before:
        def _ollama_chat(*args, **kwargs):
            kwargs.setdefault("keep_alive", _KEEP_ALIVE)
            return _ollama_raw.chat(*args, **kwargs)
        ollama = type("_OllamaShim", (), {"chat": staticmethod(_ollama_chat)})()

    After:
        from harness.inference import OllamaLike
        ollama = OllamaLike(keep_alive=_KEEP_ALIVE)

    keep_alive is injected for Ollama calls and silently dropped for vLLM.
    """
    def __init__(self, keep_alive=None):
        self._keep_alive = keep_alive

    def chat(self, model: str | None = None, messages: list | None = None, **kwargs) -> Any:
        if self._keep_alive is not None and _BACKEND == "ollama":
            kwargs.setdefault("keep_alive", self._keep_alive)
        return chat(model=model or "", messages=messages or [], **kwargs)


# Module-level shim so `import harness.inference as ollama` works as a drop-in.
_module_shim = OllamaLike()


# ---------------------------------------------------------------------------
# Embedding API
# ---------------------------------------------------------------------------

_LOCAL_EMBED_MODEL = "all-MiniLM-L6-v2"   # ~22MB, fast, 384 dims


def _embed_vllm(texts: list[str]) -> list[list[float]]:
    """Embed via vLLM /v1/embeddings using the first served model."""
    from openai import OpenAI
    client = OpenAI(base_url=_VLLM_BASE, api_key=_VLLM_API_KEY)
    embed_model = next(iter(_MODEL_MAP.values())) if _MODEL_MAP else "default"
    resp = client.embeddings.create(model=embed_model, input=texts)
    return [d.embedding for d in resp.data]


_LOCAL_EMBED_INSTANCE = None  # module-level cache — avoids reloading weights each call


def _embed_local(texts: list[str]) -> list[list[float]]:
    """Embed via sentence-transformers (all-MiniLM-L6-v2, local, no API)."""
    global _LOCAL_EMBED_INSTANCE
    if _LOCAL_EMBED_INSTANCE is None:
        from sentence_transformers import SentenceTransformer
        _LOCAL_EMBED_INSTANCE = SentenceTransformer(_LOCAL_EMBED_MODEL)
    return _LOCAL_EMBED_INSTANCE.encode(texts, show_progress_bar=False).tolist()


def embed(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using the current backend.

    vLLM backend: uses /v1/embeddings with the served model.
    Ollama backend: uses sentence-transformers directly.
    Falls back to sentence-transformers on any vLLM error.

    Returns list of float vectors, one per input text.
    """
    if _BACKEND == "vllm":
        try:
            return _embed_vllm(texts)
        except Exception as e:
            print(f"  [inference:embed] vLLM embed failed ({e}) — falling back to local")
    return _embed_local(texts)


def get_embedding_function(device: str = "cpu"):
    """
    Return a ChromaDB-compatible EmbeddingFunction.

    Always returns SentenceTransformerEmbeddingFunction (384-dim, local).
    Both backends use the same local model so ChromaDB collections stay
    compatible across backend switches.
    """
    from chromadb.utils import embedding_functions
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=_LOCAL_EMBED_MODEL,
        device=device,
    )


def get_embed_collection_suffix() -> str:
    """
    Collection name suffix for backend isolation.

    Returns "" always: both backends use the same local sentence-transformers
    model (384-dim), so no collection isolation is needed.
    """
    return ""
