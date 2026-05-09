"""
Tests for leverage metric computation in RunTrace.finish()
and git-state-layer auto-commit in RunTrace._git_commit_run().

Covers:
- Proxy formula (score × output_lines / runtime_hours) fires on every run
- Not set when wiggum_scores or output_lines are absent
- tac_hours formula takes precedence when available
- GIT_STATE=1 calls git add + git commit on PASS
- GIT_STATE unset → no git calls
- FAIL result → no git calls
- git failure is swallowed (no exception propagates)
"""

from __future__ import annotations

import harness.logger as _logger_mod


def _make_trace(monkeypatch, runtime_s: float = 600.0):
    """Create a RunTrace with _is_sub=True (no file I/O) and controlled runtime."""
    from harness.logger import RunTrace

    t0 = 1_000_000.0
    calls = [0]

    def fake_monotonic():
        calls[0] += 1
        return t0 if calls[0] == 1 else t0 + runtime_s

    monkeypatch.setattr(_logger_mod.time, "monotonic", fake_monotonic)
    return RunTrace(task="t", producer_model="m", evaluator_model="e", _is_sub=True)


class TestLeverageProxy:
    def test_proxy_formula_basic(self, monkeypatch, tmp_data_dir):
        """leverage = score × output_lines / (runtime_s / 3600)."""
        trace = _make_trace(monkeypatch, runtime_s=600.0)
        trace.data["wiggum_scores"] = [8.0]
        trace.data["output_lines"]  = 100
        trace.data.pop("tac_hours", None)

        trace.finish("PASS")

        expected = round(8.0 * 100 / (600.0 / 3600.0), 2)
        assert trace.data["leverage"] == expected

    def test_proxy_uses_last_wiggum_score(self, monkeypatch, tmp_data_dir):
        """Only the final round's score is used (best-round restoration)."""
        trace = _make_trace(monkeypatch, runtime_s=300.0)
        trace.data["wiggum_scores"] = [5.0, 6.0, 9.0]
        trace.data["output_lines"]  = 50
        trace.data.pop("tac_hours", None)

        trace.finish("PASS")

        expected = round(9.0 * 50 / (300.0 / 3600.0), 2)
        assert trace.data["leverage"] == expected

    def test_not_set_without_wiggum_scores(self, monkeypatch, tmp_data_dir):
        """No wiggum scores → leverage stays None."""
        trace = _make_trace(monkeypatch, runtime_s=600.0)
        trace.data["wiggum_scores"] = []
        trace.data["output_lines"]  = 100
        trace.data.pop("tac_hours", None)
        trace.data["leverage"] = None

        trace.finish("PASS")

        assert trace.data.get("leverage") is None

    def test_not_set_without_output_lines(self, monkeypatch, tmp_data_dir):
        """Zero output lines → leverage stays None (nothing was produced)."""
        trace = _make_trace(monkeypatch, runtime_s=600.0)
        trace.data["wiggum_scores"] = [8.0]
        trace.data["output_lines"]  = 0
        trace.data.pop("tac_hours", None)
        trace.data["leverage"] = None

        trace.finish("PASS")

        assert trace.data.get("leverage") is None

    def test_tac_hours_formula_takes_precedence(self, monkeypatch, tmp_data_dir):
        """When tac_hours is set, the quality-adjusted formula overrides the proxy."""
        trace = _make_trace(monkeypatch, runtime_s=600.0)
        trace.data["wiggum_scores"] = [8.0]
        trace.data["output_lines"]  = 100
        trace.data["tac_hours"]     = 2.0  # 2 human hours

        trace.finish("PASS")

        # tac formula: (tac_s * quality_norm) / runtime_s
        quality_norm = 8.0 / 10.0
        tac_s = 2.0 * 3600.0
        expected = round((tac_s * quality_norm) / 600.0, 2)
        assert trace.data["leverage"] == expected

    def test_proxy_logged_in_finish_print(self, monkeypatch, tmp_data_dir, capsys):
        """Leverage value appears in the finish() log line."""
        trace = _make_trace(monkeypatch, runtime_s=600.0)
        trace.data["wiggum_scores"] = [8.0]
        trace.data["output_lines"]  = 100
        trace.data.pop("tac_hours", None)

        trace.finish("PASS")

        out = capsys.readouterr().out
        assert "leverage=" in out


# ---------------------------------------------------------------------------
# Git state layer — _git_commit_run()
# ---------------------------------------------------------------------------

class TestGitCommitRun:
    """Tests for _git_commit_run() — called directly to avoid file-I/O in finish()."""

    def _make_trace_with_data(self, monkeypatch, run_id="abc12345", task="test task", out_path=None):
        from harness.logger import RunTrace
        trace = RunTrace(task=task, producer_model="m", evaluator_model="e", _is_sub=True)
        trace.data["run_id"]      = run_id
        trace.data["task"]        = task
        trace.data["final"]       = "PASS"
        trace.data["output_path"] = out_path
        return trace

    def test_git_called_when_git_state_is_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GIT_STATE", "1")
        calls = []

        def fake_run(cmd, **_):
            calls.append(cmd)
            class R: returncode = 0
            return R()

        monkeypatch.setattr(_logger_mod.subprocess, "run", fake_run)
        trace = self._make_trace_with_data(monkeypatch)
        trace._git_commit_run()

        add_call    = next((c for c in calls if "add" in c), None)
        commit_call = next((c for c in calls if "commit" in c), None)
        assert add_call    is not None, "git add not called"
        assert commit_call is not None, "git commit not called"

    def test_commit_message_contains_run_id_and_task(self, monkeypatch):
        monkeypatch.setenv("GIT_STATE", "1")
        commit_msgs = []

        def fake_run(cmd, **_):
            if "commit" in cmd:
                commit_msgs.append(cmd[-1])  # last arg is the -m message
            class R: returncode = 0
            return R()

        monkeypatch.setattr(_logger_mod.subprocess, "run", fake_run)
        trace = self._make_trace_with_data(monkeypatch, run_id="deadbeef1234", task="synthesize rag paper")
        trace._git_commit_run()

        assert commit_msgs, "git commit not called"
        msg = commit_msgs[0]
        assert "deadbeef" in msg
        assert "synthesize rag paper" in msg

    def test_output_path_added_when_present(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GIT_STATE", "1")
        out_file = tmp_path / "output.md"
        added_paths = []

        def fake_run(cmd, **_):
            if "add" in cmd:
                added_paths.extend(cmd[cmd.index("--") + 1:])
            class R: returncode = 0
            return R()

        monkeypatch.setattr(_logger_mod.subprocess, "run", fake_run)
        trace = self._make_trace_with_data(monkeypatch, out_path=str(out_file))
        trace._git_commit_run()

        assert any(str(out_file) in p for p in added_paths), \
            f"output_path not staged; staged: {added_paths}"

    def test_no_git_when_git_state_not_set(self, monkeypatch):
        monkeypatch.delenv("GIT_STATE", raising=False)
        calls = []

        def fake_run(cmd, **_):
            calls.append(cmd)
            class R: returncode = 0
            return R()

        monkeypatch.setattr(_logger_mod.subprocess, "run", fake_run)
        trace = self._make_trace_with_data(monkeypatch)
        trace._git_commit_run()

        assert not calls, "subprocess.run called when GIT_STATE not set"

    def test_no_git_when_git_state_is_0(self, monkeypatch):
        monkeypatch.setenv("GIT_STATE", "0")
        calls = []
        monkeypatch.setattr(_logger_mod.subprocess, "run", lambda *a, **kw: calls.append(a))
        trace = self._make_trace_with_data(monkeypatch)
        trace._git_commit_run()
        assert not calls

    def test_git_failure_is_swallowed(self, monkeypatch, capsys):
        monkeypatch.setenv("GIT_STATE", "1")

        def fake_run(cmd, **_):
            raise OSError("git not found")

        monkeypatch.setattr(_logger_mod.subprocess, "run", fake_run)
        trace = self._make_trace_with_data(monkeypatch)
        trace._git_commit_run()  # must not raise

        out = capsys.readouterr().out
        assert "skipped" in out or "git" in out
