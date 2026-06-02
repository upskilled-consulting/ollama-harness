"""
harness/logger.py — structured run tracing for the agent pipeline.

Appends one JSON record per run to runs.jsonl.
Writes a Chrome Trace Event JSON to traces/ for each run — load in ui.perfetto.dev.
Import and use RunTrace in agent.py and wiggum.py.
"""

import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from harness.config import LIVE_RUN_FILE, RUNS_FILE, TRACES_DIR
from harness.schema import (
    ARTIFACTS_PATH,
    MESSAGES_PATH,
    PLANS_PATH,
    Artifact,
    Message,
    OrchestratorPlan,
    _append_jsonl,
    make_id,
)

LOG_PATH  = str(RUNS_FILE)
TRACE_DIR = str(TRACES_DIR)


def _extract_usage(response) -> dict:
    """
    Pull token counts, timing, and thinking content from an ollama ChatResponse.
    Returns zeros/empty for any missing fields (safe to call on any response).
    """
    msg = getattr(response, "message", None)
    thinking = (getattr(msg, "thinking", None) or "") if msg is not None else ""
    return {
        "input_tokens":   getattr(response, "prompt_eval_count", 0) or 0,
        "output_tokens":  getattr(response, "eval_count", 0) or 0,
        "total_ms":       round((getattr(response, "total_duration", 0) or 0) / 1e6, 1),
        "eval_ms":        round((getattr(response, "eval_duration",  0) or 0) / 1e6, 1),
        "prompt_ms":      round((getattr(response, "prompt_eval_duration", 0) or 0) / 1e6, 1),
        "thinking":       thinking,
        "thinking_chars": len(thinking),
    }


class RunTrace:
    def __init__(
        self,
        task: str,
        producer_model: str,
        evaluator_model: str,
        session_id: str = "",
        project_id: str = "",
        _is_sub: bool = False,
    ):
        self._run_start  = time.monotonic()
        self._t0_us      = time.monotonic_ns() // 1000
        self._pid        = os.getpid()
        self._events: list[Any] = []
        self._task       = task

        self.run_id      = os.environ.get("HARNESS_RUN_ID") or make_id()
        self.session_id  = session_id or os.environ.get("HARNESS_SESSION_ID", "")
        self.project_id  = project_id or os.environ.get("HARNESS_PROJECT_ID", "")
        self.parent_run_id   = os.environ.get("HARNESS_PARENT_RUN_ID", "")
        self.experiment_id   = os.environ.get("HARNESS_EXPERIMENT_ID", "")
        self.treatment_level = os.environ.get("HARNESS_TREATMENT_LEVEL", "")
        self.task_id         = os.environ.get("HARNESS_TASK_ID", "")
        self._msg_seq        = 0
        self._is_sub         = _is_sub
        self._current_stage  = "startup"
        self._stages_seen: list[str] = []

        self.data: dict[str, Any] = {
            "run_id":           self.run_id,
            "session_id":       self.session_id,
            "project_id":       self.project_id,
            "parent_run_id":    self.parent_run_id,
            "experiment_id":    self.experiment_id,
            "treatment_level":  self.treatment_level,
            "task_id":          self.task_id,
            "timestamp":        datetime.now(UTC).isoformat(),
            "task":             task,
            "producer_model":   producer_model,
            "evaluator_model":  evaluator_model,

            "run_duration_s":   None,

            "input_tokens":     0,
            "output_tokens":    0,
            "total_tokens":     0,

            "total_eval_ms":        None,
            "total_prompt_ms":      None,
            "generation_tok_s":     None,
            "total_thinking_chars": 0,

            "tokens_by_stage":  {},

            "tool_calls":           [],
            "vision_images":        [],
            "total_search_chars":   0,
            "quality_floor_hit":    False,

            "files_read":           [],
            "code_executions":      0,
            "injection_stripped":   0,
            "memory_hits":          0,
            "memory_context_titles": [],
            "plan":                 None,

            "orchestrated":         False,
            "subtask_count":        0,
            "orchestration_style":  None,
            "allow_parallelism":    None,
            "subtask_results":      [],
            "tool_failures":        [],
            "validation_passed":    None,
            "policy_confidence":    None,

            "synth_forced":         False,
            "output_path":          None,
            "output_lines":         None,
            "output_bytes":         None,
            "count_check_retry":    False,

            "synth_cot":            [],
            "planner_cot":          [],
            "trajectory":           [],   # ordered steps: {seq, stage, thinking, tool, query, result_chars}

            "wiggum_rounds":        0,
            "wiggum_scores":        [],
            "wiggum_dims":          [],
            "wiggum_eval_log":      [],

            "tac_hours":            None,
            "leverage":             None,

            "screenshots":          [],

            "final":                None,
        }

    # ------------------------------------------------------------------
    # Chrome Trace Event instrumentation
    # ------------------------------------------------------------------

    def _record(self, name: str, start_us: int, dur_us: int, tid: int, args: dict = None):
        """Append one complete (X) Chrome Trace event."""
        event = {
            "name": name,
            "ph":   "X",
            "ts":   start_us - self._t0_us,
            "dur":  max(dur_us, 1),
            "pid":  self._pid,
            "tid":  tid,
        }
        if args:
            event["args"] = args
        self._events.append(event)

    def name_thread(self, name: str):
        """Emit a thread_name metadata event for the calling thread."""
        self._events.append({
            "name": "thread_name",
            "ph":   "M",
            "pid":  self._pid,
            "tid":  threading.get_ident(),
            "args": {"name": name},
        })

    @contextmanager
    def span(self, name: str, **args):
        """
        Context manager — records a Chrome Trace 'X' event for the enclosed block.

        Usage:
            with trace.span("synthesize", model="pi-qwen-32b"):
                content = synthesize(...)
        """
        tid      = threading.get_ident()
        start_us = time.monotonic_ns() // 1000
        try:
            yield
        finally:
            dur_us = (time.monotonic_ns() // 1000) - start_us
            self._record(name, start_us, dur_us, tid, args or None)

    def _fire_webhook(self):
        """POST a compact run summary to CLAUDE_WEBHOOK_URL if set (non-blocking, best-effort)."""
        url = os.environ.get("CLAUDE_WEBHOOK_URL", "").strip()
        if not url:
            return
        import threading
        import urllib.error
        import urllib.request
        payload = json.dumps({
            "run_id":       self.run_id,
            "task":         self._task[:200],
            "final":        self.data.get("final"),
            "task_type":    self.data.get("task_type"),
            "elapsed_s":    self.data.get("run_duration_s"),
            "input_tokens":  self.data.get("input_tokens", 0),
            "output_tokens": self.data.get("output_tokens", 0),
            "output_path":  self.data.get("output_path"),
            "wiggum_scores": self.data.get("wiggum_scores", []),
        }).encode()
        def _post():
            try:
                req = urllib.request.Request(
                    url, data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=10)
                print(f"  [webhook] fired -> {url}")
            except urllib.error.URLError as e:
                print(f"  [webhook] failed (non-fatal): {e}")
        threading.Thread(target=_post, daemon=True).start()

    def _write_trace(self):
        """Write Chrome Trace JSON to traces/<run_id>_<slug>.json."""
        if not self._events:
            return
        os.makedirs(TRACE_DIR, exist_ok=True)
        slug = re.sub(r"[^\w]+", "_", self._task[:50]).strip("_")
        path = os.path.join(TRACE_DIR, f"{self.run_id}_{slug}.json")
        payload = {
            "traceEvents":     self._events,
            "displayTimeUnit": "ms",
            "otherData":       {"task": self._task},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        print(f"  [trace] {path}")

    # ------------------------------------------------------------------
    # Token / timing tracking
    # ------------------------------------------------------------------

    def log_usage(self, response, stage: str = "other"):
        """
        Accumulate token counts, latency, and thinking chars from one ollama.chat response.
        Also emits a Chrome Trace event using Ollama's own reported total_duration.

        stage: "search_query" | "synth" | "synth_count" | "tool_loop" |
               "wiggum_eval" | "wiggum_revise" | "planner" | "memory" | "compress_knowledge" | "other"
        """
        u = _extract_usage(response)
        self.data["input_tokens"]  += u["input_tokens"]
        self.data["output_tokens"] += u["output_tokens"]

        s = self.data["tokens_by_stage"].setdefault(
            stage, {"input": 0, "output": 0, "thinking_chars": 0, "calls": 0,
                    "total_ms": 0, "eval_ms": 0, "prompt_ms": 0}
        )
        s["input"]          += u["input_tokens"]
        s["output"]         += u["output_tokens"]
        s["thinking_chars"] += u["thinking_chars"]
        s["calls"]          += 1
        s["total_ms"]       += u["total_ms"]
        s["eval_ms"]        += u["eval_ms"]
        s["prompt_ms"]      += u["prompt_ms"]

        if u["total_ms"] > 0:
            now_us   = time.monotonic_ns() // 1000
            start_us = now_us - int(u["total_ms"] * 1000)
            self._record(
                f"llm:{stage}",
                start_us,
                int(u["total_ms"] * 1000),
                threading.get_ident(),
                {"in_tok": u["input_tokens"], "out_tok": u["output_tokens"],
                 "prompt_ms": u["prompt_ms"], "eval_ms": u["eval_ms"]},
            )

    # ------------------------------------------------------------------
    # Existing log methods
    # ------------------------------------------------------------------

    def log_tool_call(self, name: str, query: str, result_chars: int,
                      urls: list[dict] | None = None,
                      result_preview: str | None = None,
                      error: str | None = None):
        entry: dict = {"name": name, "query": query, "result_chars": result_chars}
        if urls:
            entry["urls"] = urls[:12]
        if result_preview:
            entry["result_preview"] = result_preview[:1200]
        if error:
            entry["error"] = error
        self.data["tool_calls"].append(entry)

    def log_synth_forced(self):
        self.data["synth_forced"] = True

    def log_plan(self, plan_dict: dict):
        self.data["plan"] = plan_dict

    def log_memory_hits(self, count: int, titles: list[str] | None = None):
        self.data["memory_hits"] = count
        if titles:
            self.data["memory_context_titles"] = titles

    def log_injection_stripped(self, count: int):
        self.data["injection_stripped"] += count

    def log_files_read(self, paths: list[str]):
        self.data["files_read"] = paths

    def log_vision(self, image_paths: list[str]):
        self.data["vision_images"] = image_paths

    def log_step(self, stage: str, thinking: str = "", tool: str = "",
                 query: str = "", result_chars: int = 0) -> None:
        """Append one trajectory step for RL dataset export.
        Each step captures the model's reasoning (thinking) paired with the action it took."""
        if not thinking and not tool:
            return
        self.data["trajectory"].append({
            "seq":          len(self.data["trajectory"]),
            "stage":        stage,
            "thinking":     thinking,
            "tool":         tool,
            "query":        query,
            "result_chars": result_chars,
        })

    def set_stage(self, stage: str) -> None:
        """Mark entry into a pipeline stage and write a live snapshot for the dashboard."""
        self._current_stage = stage
        if stage not in self._stages_seen:
            self._stages_seen.append(stage)
        if not self._is_sub:
            self._write_live()

    def _write_live(self) -> None:
        snapshot = {
            "run_id":        self.run_id,
            "task":          self._task,
            "started_at":    self.data["timestamp"],
            "current_stage": self._current_stage,
            "stages_seen":   list(self._stages_seen),
            "elapsed_s":     round(time.monotonic() - self._run_start, 1),
        }
        tmp = str(LIVE_RUN_FILE) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f)
            os.replace(tmp, str(LIVE_RUN_FILE))
        except OSError:
            pass

    def log_synth_cot(self, thinking: str):
        """Append one synthesis thinking block. Called once per synthesize() invocation."""
        if thinking:
            self.data["synth_cot"].append(thinking)
            self.log_step("synth", thinking=thinking)

    def log_planner_cot(self, response) -> None:
        """Extract and store thinking text from a planner model response."""
        thinking = getattr(getattr(response, "message", None), "thinking", None) or ""
        if thinking:
            self.data["planner_cot"].append(thinking)
            self.log_step("plan", thinking=thinking)

    def log_count_retry(self):
        self.data["count_check_retry"] = True

    def log_search_quality(self, total_chars: int):
        self.data["total_search_chars"] = total_chars
        self.data["quality_floor_hit"] = total_chars < 1800

    def log_artifact(self, path: str, artifact_type: str = "output", lines: int = None, content_hash: str = None):
        """Register a produced file in artifacts.jsonl."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        try:
            size = os.path.getsize(abs_path)
        except OSError:
            size = 0
        a = Artifact(
            run_id=self.run_id,
            session_id=self.session_id,
            project_id=self.project_id,
            type=artifact_type,
            path=abs_path,
            bytes=size,
            lines=lines,
            content_hash=content_hash,
        )
        _append_jsonl(ARTIFACTS_PATH, {"event": "artifact_create", **a.to_dict()})

    def log_message(self, role: str, content: str = None, cot: str = None, tool_calls: list = None, tool_name: str = None, stage: str = None):
        """Record one LLM message turn in messages.jsonl."""
        m = Message(
            run_id=self.run_id,
            session_id=self.session_id,
            project_id=self.project_id,
            seq=self._msg_seq,
            role=role,
            stage=stage or None,
            content=content,
            cot=cot or None,
            tool_calls=tool_calls,
            tool_name=tool_name,
            chars=len(content) if content else None,
        )
        self._msg_seq += 1
        _append_jsonl(MESSAGES_PATH, m.to_dict())

    def log_llm_turn(self, stage: str, input_text: str, output_text: str, thinking: str = "") -> None:
        """Log one complete LLM prompt+response pair to messages.jsonl, tagged by stage."""
        self.log_message(role="user",      content=input_text,  stage=stage)
        self.log_message(role="assistant", content=output_text, cot=thinking or None, stage=stage)

    def log_context_block(self, stage: str, content: str) -> None:
        """Log a non-LLM context injection (system prompt, memory, research, etc.) to messages.jsonl.
        Records an estimated token count (chars // 4) in tokens_by_stage so the treemap can show it."""
        if not content or not content.strip():
            return
        self.log_message(role="context", content=content, stage=stage)
        chars = len(content)
        s = self.data["tokens_by_stage"].setdefault(
            stage, {"input": 0, "output": 0, "calls": 0, "total_ms": 0,
                    "eval_ms": 0, "prompt_ms": 0, "thinking_chars": 0, "context": True}
        )
        s["input"]   += max(1, chars // 4)
        s["context"]  = True

    def log_policy(self, orchestration_style: str, allow_parallelism: bool) -> None:
        """Record the orchestration policy chosen for this run."""
        self.data["orchestration_style"] = orchestration_style
        self.data["allow_parallelism"] = allow_parallelism

    def log_plan_record(self, plan_dict: dict, plan_type: str = "agent") -> str:
        """Write an OrchestratorPlan record to plans.jsonl. Returns plan_id."""
        raw_subtasks = plan_dict.get("subtasks", [])
        subtasks = [
            s if isinstance(s, dict) else {"desc": s}
            for s in raw_subtasks
        ]
        p = OrchestratorPlan(
            run_id=self.run_id,
            session_id=self.session_id,
            project_id=self.project_id,
            parent_run_id=self.parent_run_id,
            task=self._task,
            plan_type=plan_type,
            task_type=plan_dict.get("task_type", ""),
            complexity=plan_dict.get("complexity", ""),
            subtasks=subtasks,
            known_facts=plan_dict.get("known_facts", []),
            knowledge_gaps=plan_dict.get("knowledge_gaps", []),
            search_queries=plan_dict.get("search_queries", []),
        )
        _append_jsonl(PLANS_PATH, p.to_dict())
        return p.plan_id

    def log_write(self, path: str, content: str):
        abs_path = os.path.abspath(os.path.expanduser(path))
        byte_count = len(content.encode("utf-8"))
        line_count = content.count("\n") + 1
        self.data["output_path"]    = abs_path
        self.data["output_lines"]   = line_count
        self.data["output_bytes"]   = byte_count
        self.data["final_content"]  = content[:16_000]
        self.log_artifact(path, artifact_type="output", lines=line_count)

    def log_wiggum(self, wiggum_trace: dict):
        rounds = wiggum_trace.get("rounds", [])
        self.data["wiggum_rounds"] = len(rounds)
        self.data["wiggum_scores"] = [r["score"] for r in rounds]
        self.data["wiggum_dims"]   = [r.get("dims", {}) for r in rounds]
        self.data["task_type"]     = wiggum_trace.get("task_type")
        self.data["final"]         = wiggum_trace.get("final")
        self.data["wiggum_eval_log"] = [
            {
                "round":    r["round"],
                "score":    r["score"],
                "dims":     r.get("dims", {}),
                "issues":   r.get("issues", []),
                "feedback": r.get("feedback", ""),
                **({"content": r["content"]} if r.get("content") else {}),
                **({"thinking": r["thinking"]} if r.get("thinking") else {}),
            }
            for r in rounds
        ]

        if wiggum_trace.get("tac_hours") is not None:
            self.data["tac_hours"] = wiggum_trace["tac_hours"]

        for stage, vals in wiggum_trace.get("tokens_by_stage", {}).items():
            s = self.data["tokens_by_stage"].setdefault(
                stage, {"input": 0, "output": 0, "calls": 0,
                        "total_ms": 0, "eval_ms": 0, "prompt_ms": 0, "thinking_chars": 0}
            )
            s["input"]          += vals.get("input", 0)
            s["output"]         += vals.get("output", 0)
            s["calls"]          += vals.get("calls", 0)
            s["total_ms"]       += vals.get("total_ms", 0)
            s["eval_ms"]        += vals.get("eval_ms", 0)
            s["prompt_ms"]      += vals.get("prompt_ms", 0)
            s["thinking_chars"] += vals.get("thinking_chars", 0)
        self.data["input_tokens"]  += wiggum_trace.get("input_tokens", 0)
        self.data["output_tokens"] += wiggum_trace.get("output_tokens", 0)

    def _git_commit_run(self) -> None:
        """Stage runs.jsonl + output file and commit. Opt-in via GIT_STATE=1. Silent/best-effort."""
        if os.environ.get("GIT_STATE", "").strip() != "1":
            return
        run_id  = self.data.get("run_id", "")[:8]
        task    = (self.data.get("task") or "")[:60]
        out_path = self.data.get("output_path")
        try:
            repo_root = str(RUNS_FILE.parent.parent)
            paths = [str(RUNS_FILE)]
            if out_path:
                paths.append(str(out_path))
            subprocess.run(
                ["git", "add", "--"] + paths,
                cwd=repo_root, check=True,
                capture_output=True, timeout=15,
            )
            subprocess.run(
                ["git", "commit", "-m", f"run: {run_id} {task}"],
                cwd=repo_root, check=True,
                capture_output=True, timeout=15,
            )
            print(f"  [git] committed run {run_id}")
        except Exception as e:
            print(f"  [git] commit skipped: {e}")

    def finish(self, final: str = None):
        if final:
            self.data["final"] = final
        self.data["run_duration_s"] = round(time.monotonic() - self._run_start, 1)

        tac_hours    = self.data.get("tac_hours")
        scores       = self.data.get("wiggum_scores") or []
        runtime_s    = self.data["run_duration_s"]
        output_lines = self.data.get("output_lines", 0)
        if tac_hours and scores:
            quality_norm  = scores[-1] / 10.0
            tac_s         = tac_hours * 3600.0
            energy_cost   = float(os.environ.get("HARNESS_ENERGY_COST_PER_RUN", 0.0))
            infer_cost    = float(os.environ.get("HARNESS_INFERENCE_COST_PER_RUN", 0.0))
            hourly_rate   = float(os.environ.get("HARNESS_HOURLY_RATE", 75.0))
            cost_s        = ((energy_cost + infer_cost) / hourly_rate) * 3600.0
            self.data["leverage"] = round((tac_s * quality_norm) / max(runtime_s + cost_s, 1.0), 2)
        elif scores and output_lines and runtime_s > 0:
            # Proxy: score × lines / (runtime_hours) — derivable from every run
            self.data["leverage"] = round(scores[-1] * output_lines / max(runtime_s / 3600.0, 1e-6), 2)

        # Derived timing + throughput metrics
        stages = self.data["tokens_by_stage"].values()
        total_eval_ms   = sum(s.get("eval_ms",   0) for s in stages)
        total_prompt_ms = sum(s.get("prompt_ms", 0) for s in stages)
        total_thinking_chars = sum(s.get("thinking_chars", 0) for s in stages)

        self.data["total_tokens"]          = self.data["input_tokens"] + self.data["output_tokens"]
        self.data["total_eval_ms"]         = round(total_eval_ms, 1)
        self.data["total_prompt_ms"]       = round(total_prompt_ms, 1)
        self.data["total_thinking_chars"]  = total_thinking_chars

        if total_eval_ms > 0:
            self.data["generation_tok_s"] = round(
                self.data["output_tokens"] / (total_eval_ms / 1000), 1
            )
            # Per-stage tok/s
            for s in self.data["tokens_by_stage"].values():
                e = s.get("eval_ms", 0)
                if e > 0 and s.get("output", 0) > 0:
                    s["tok_s"] = round(s["output"] / (e / 1000), 1)

        tok_in   = self.data["input_tokens"]
        tok_out  = self.data["output_tokens"]
        tok_s    = self.data.get("generation_tok_s")
        dur      = self.data["run_duration_s"]
        leverage = self.data.get("leverage")
        lev_str  = f"  leverage={leverage:.1f}x" if leverage is not None else ""
        tac_str  = f"  tac={tac_hours}h" if tac_hours else ""
        tps_str  = f"  {tok_s:.0f} tok/s" if tok_s else ""
        print(f"  [log] {dur}s  in={tok_in} out={tok_out} tok{tps_str}{tac_str}{lev_str}")
        if not self._is_sub:
            try:
                LIVE_RUN_FILE.unlink(missing_ok=True)
            except OSError:
                pass
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(self.data) + "\n")
            print(f"  [log] -> {LOG_PATH}")
            self._write_trace()
            self._fire_webhook()
            if self.data.get("final") == "PASS":
                self._git_commit_run()
