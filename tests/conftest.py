"""
Shared fixtures for harness-refactor post-refactor tests.
"""

import sys
from pathlib import Path

import pytest

# Repo root on path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def tmp_data_dir(tmp_path, monkeypatch):
    """Point all harness.schema JSONL paths to an isolated temp dir."""
    import harness.config as config
    import harness.schema as schema

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(schema, "PROJECTS_PATH",  str(tmp_path / "projects.jsonl"))
    monkeypatch.setattr(schema, "SESSIONS_PATH",  str(tmp_path / "sessions.jsonl"))
    monkeypatch.setattr(schema, "ARTIFACTS_PATH", str(tmp_path / "artifacts.jsonl"))
    monkeypatch.setattr(schema, "MESSAGES_PATH",  str(tmp_path / "messages.jsonl"))
    monkeypatch.setattr(schema, "PLANS_PATH",     str(tmp_path / "plans.jsonl"))
    monkeypatch.setattr(schema, "DOTFILE",        str(tmp_path / ".harness-project"))
    return tmp_path


@pytest.fixture()
def api_client():
    """FastAPI TestClient with isolated state."""
    from fastapi.testclient import TestClient

    from harness.api.main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def mock_inference(monkeypatch):
    """
    Stub harness.inference chat() and embed() — no live LLM calls.
    Returns recorder: {"chat_calls": [...], "embed_calls": [...]}.
    """
    import harness.inference as inference

    recorder = {"chat_calls": [], "embed_calls": []}

    class _FakeMessage:
        role = "assistant"
        content = '{"score": 8.5, "passed": false, "issues": [], "feedback": "ok"}'
        thinking = ""
        def __getitem__(self, k): return getattr(self, k)
        def get(self, k, d=None): return getattr(self, k, d)

    class _FakeResponse:
        prompt_eval_count = 10
        eval_count = 5
        total_duration = 1_000_000_000
        prompt_eval_duration = 500_000_000
        eval_duration = 500_000_000
        load_duration = 0
        message = _FakeMessage()
        def __getitem__(self, k): return getattr(self, k)

    def _fake_chat(model, messages, **kwargs):
        recorder["chat_calls"].append({"model": model, "messages": messages, **kwargs})
        return _FakeResponse()

    def _fake_embed(texts):
        recorder["embed_calls"].append(texts)
        return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr(inference, "chat", _fake_chat)
    monkeypatch.setattr(inference, "embed", _fake_embed)
    return recorder
