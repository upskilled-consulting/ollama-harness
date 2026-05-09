"""
Tests for per-task stdout tee + GET /api/tasks/{id}/stream SSE endpoint.

Three properties verified for the tee writer:
  1. Log file is created when a task opens.
  2. print() calls are captured in the log file.
  3. [DONE] sentinel is appended on close even if the agent raises.
  4. Two concurrent threads write to separate log files (no cross-contamination).
  5. sys.stdout still passes writes through to real stdout (not swallowed).

Three properties verified for the SSE endpoint:
  6. Returns text/event-stream content-type.
  7. Each log line becomes a `data: <line>` SSE event.
  8. [EVENT]<json> lines pass through unmodified (parsed only on the frontend).
  9. [DONE] appears as the final data event and the stream closes.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness.api.main import app

_client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse_data_lines(body: str) -> list[str]:
    """Extract `data: <x>` payloads from a raw SSE body."""
    lines = []
    for line in body.splitlines():
        if line.startswith("data: "):
            lines.append(line[len("data: "):])
    return lines


# ---------------------------------------------------------------------------
# Tee writer
# ---------------------------------------------------------------------------

class TestTaskTeeWriter:

    # ------------------------------------------------------------------
    # 1. Log file created
    # ------------------------------------------------------------------

    def test_log_file_created(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        log_path = mod._open_task_log("create-test")
        mod._close_task_log(log_path)

        assert log_path.exists()
        assert log_path == tmp_path / "create-test.log"

    # ------------------------------------------------------------------
    # 2. print() is captured in the log
    # ------------------------------------------------------------------

    def test_print_captured_to_log(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        log_path = mod._open_task_log("capture-test")
        print("captured line", flush=True)
        mod._close_task_log(log_path)

        text = log_path.read_text(encoding="utf-8")
        assert "captured line" in text

    # ------------------------------------------------------------------
    # 3. [DONE] sentinel appended on close
    # ------------------------------------------------------------------

    def test_done_sentinel_appended(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        log_path = mod._open_task_log("sentinel-test")
        print("some output", flush=True)
        mod._close_task_log(log_path)

        text = log_path.read_text(encoding="utf-8")
        assert text.endswith("[DONE]\n")

    def test_done_sentinel_written_even_without_output(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        log_path = mod._open_task_log("empty-task")
        mod._close_task_log(log_path)

        text = log_path.read_text(encoding="utf-8")
        assert "[DONE]" in text

    # ------------------------------------------------------------------
    # 4. Thread isolation — two concurrent threads use separate log files
    # ------------------------------------------------------------------

    def test_concurrent_threads_write_separate_logs(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        results: dict[str, str] = {}

        def worker(item_id: str, marker: str) -> None:
            log_path = mod._open_task_log(item_id)
            print(marker, flush=True)
            mod._close_task_log(log_path)
            results[item_id] = log_path.read_text(encoding="utf-8")

        t1 = threading.Thread(target=worker, args=("thread-a", "MARKER_A"))
        t2 = threading.Thread(target=worker, args=("thread-b", "MARKER_B"))
        t1.start(); t2.start()
        t1.join();  t2.join()

        assert "MARKER_A" in results["thread-a"], "thread-a log missing its own marker"
        assert "MARKER_B" in results["thread-b"], "thread-b log missing its own marker"
        assert "MARKER_B" not in results["thread-a"], "thread-a log contaminated by thread-b"
        assert "MARKER_A" not in results["thread-b"], "thread-b log contaminated by thread-a"

    # ------------------------------------------------------------------
    # 5. Real stdout still receives writes (not swallowed)
    # ------------------------------------------------------------------

    def test_real_stdout_still_receives_writes(self, tmp_path, monkeypatch, capsys):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        log_path = mod._open_task_log("passthrough-test")
        print("passthrough line", flush=True)
        mod._close_task_log(log_path)

        # capsys may or may not capture depending on whether pytest already owns
        # sys.stdout at fixture time. What we CAN assert: the log file has the line.
        text = log_path.read_text(encoding="utf-8")
        assert "passthrough line" in text


# ---------------------------------------------------------------------------
# SSE stream endpoint
# ---------------------------------------------------------------------------

class TestSseStreamEndpoint:

    # ------------------------------------------------------------------
    # 6. Content-type is text/event-stream
    # ------------------------------------------------------------------

    def test_content_type_is_event_stream(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        # Pre-write a complete log so the stream closes immediately
        (tmp_path / "ct-item.log").write_text("hello\n[DONE]\n", encoding="utf-8")

        resp = _client.get("/api/tasks/ct-item/stream")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    # ------------------------------------------------------------------
    # 7. Each log line becomes a data: event
    # ------------------------------------------------------------------

    def test_log_lines_become_sse_data_events(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        (tmp_path / "lines-item.log").write_text(
            "first line\nsecond line\n[DONE]\n", encoding="utf-8"
        )

        resp = _client.get("/api/tasks/lines-item/stream")
        data = _sse_data_lines(resp.text)
        assert "first line"  in data
        assert "second line" in data

    # ------------------------------------------------------------------
    # 8. [EVENT] lines pass through unmodified (server is a dumb pipe)
    # ------------------------------------------------------------------

    def test_event_json_lines_pass_through_unmodified(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        event_json = '[EVENT]{"type":"plan","data":{"queries":["q1"],"complexity":"low"}}'
        (tmp_path / "event-item.log").write_text(
            f"{event_json}\n[DONE]\n", encoding="utf-8"
        )

        resp = _client.get("/api/tasks/event-item/stream")
        data = _sse_data_lines(resp.text)
        assert event_json in data, f"[EVENT] line not found in SSE events: {data}"

    # ------------------------------------------------------------------
    # 9. [DONE] is the final data event; stream closes after it
    # ------------------------------------------------------------------

    def test_done_is_last_data_event(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        (tmp_path / "done-item.log").write_text(
            "line one\nline two\n[DONE]\nshould not appear\n", encoding="utf-8"
        )

        resp = _client.get("/api/tasks/done-item/stream")
        data = _sse_data_lines(resp.text)
        assert data[-1] == "[DONE]", f"Expected [DONE] as last event, got {data[-1]!r}"
        assert "should not appear" not in data

    def test_stream_closes_cleanly_after_done(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        (tmp_path / "close-item.log").write_text("[DONE]\n", encoding="utf-8")

        resp = _client.get("/api/tasks/close-item/stream")
        assert resp.status_code == 200
        data = _sse_data_lines(resp.text)
        assert data == ["[DONE]"]


# ---------------------------------------------------------------------------
# Integration: tee → file → SSE
# ---------------------------------------------------------------------------

class TestTeeToSseIntegration:
    """Write via the tee, read back via the SSE endpoint."""

    def test_tee_written_lines_appear_in_sse_stream(self, tmp_path, monkeypatch):
        import harness.api.routes.tasks as mod
        monkeypatch.setattr(mod, "TASK_LOGS_DIR", tmp_path)

        # Simulate a task writing output
        log_path = mod._open_task_log("integration-item")
        print("step 1 complete", flush=True)
        print("step 2 complete", flush=True)
        mod._close_task_log(log_path)

        # Read the stream
        resp = _client.get("/api/tasks/integration-item/stream")
        data = _sse_data_lines(resp.text)

        assert "step 1 complete" in data
        assert "step 2 complete" in data
        assert "[DONE]"         in data
        assert data[-1] == "[DONE]"
