"""
Verify inference.py model map, response adapter shapes, and routing state.
No live LLM calls.
"""

import pytest
from harness.inference import (
    _resolve_model, _MODEL_MAP, _OllamaResponse, _OllamaMessage,
    OllamaLike, _BACKEND, _ENDPOINTS, list_endpoints, embed, get_embedding_function,
)


class TestModelMap:

    def test_resolve_known_model(self):
        # qwen3.6:35b-a3b is an Ollama tag that maps to the pi-qwen3.6 served name
        assert _resolve_model("qwen3.6:35b-a3b") == "pi-qwen3.6"

    def test_resolve_unknown_passthrough(self):
        assert _resolve_model("totally-unknown-model") == "totally-unknown-model"

    def test_all_entries_are_strings(self):
        for tag, served in _MODEL_MAP.items():
            assert isinstance(tag, str) and isinstance(served, str)


class TestOllamaMessageAdapter:

    def test_parses_think_tags(self):
        class _FakeOAI:
            role = "assistant"
            content = "<think>reasoning here</think>actual answer"
            reasoning_content = None

        msg = _OllamaMessage(_FakeOAI())
        assert msg.thinking == "reasoning here"
        assert msg.content == "actual answer"

    def test_uses_reasoning_content_field(self):
        class _FakeOAI:
            role = "assistant"
            content = "actual answer"
            reasoning_content = "server-side reasoning"

        msg = _OllamaMessage(_FakeOAI())
        assert msg.thinking == "server-side reasoning"
        assert msg.content == "actual answer"

    def test_from_raw_factory(self):
        msg = _OllamaMessage.from_raw("assistant", "hello", "thinking...")
        assert msg.content == "hello"
        assert msg.thinking == "thinking..."
        assert msg.role == "assistant"


class TestOllamaResponseAdapter:

    def test_dict_and_attribute_access(self):
        msg = _OllamaMessage.from_raw("assistant", "hello", "")
        resp = _OllamaResponse(msg, prompt_tokens=10, completion_tokens=5,
                               total_ns=1_000_000, prompt_ns=500_000, eval_ns=500_000)
        # Attribute access (new style)
        assert resp.message.content == "hello"
        assert resp.prompt_eval_count == 10
        assert resp.eval_count == 5
        # Dict access (legacy style — logger.py compatibility)
        assert resp["message"]["content"] == "hello"

    def test_total_tokens(self):
        msg = _OllamaMessage.from_raw("assistant", "hi", "")
        resp = _OllamaResponse(msg, prompt_tokens=10, completion_tokens=5,
                               total_ns=0, prompt_ns=0, eval_ns=0)
        assert resp.prompt_eval_count + resp.eval_count == 15


class TestOllamaLike:

    def test_instantiation(self):
        shim = OllamaLike(keep_alive=-1)
        assert shim._keep_alive == -1

    def test_chat_is_callable(self):
        assert callable(OllamaLike().chat)


class TestRoutingState:

    def test_backend_is_valid(self):
        assert _BACKEND in ("ollama", "vllm", "llamacpp")

    def test_endpoints_is_dict(self):
        assert isinstance(_ENDPOINTS, dict)

    def test_list_endpoints_returns_dict(self):
        assert isinstance(list_endpoints(), dict)

    def test_embed_callable(self):
        assert callable(embed)

    def test_get_embedding_function_callable(self):
        assert callable(get_embedding_function)
