"""
Tests for leverage metric computation in RunTrace.finish().

Covers:
- Proxy formula (score × output_lines / runtime_hours) fires on every run
- Not set when wiggum_scores or output_lines are absent
- tac_hours formula takes precedence when available
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
