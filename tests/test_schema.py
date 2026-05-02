"""
Verify schema helpers: ID generation, JSONL I/O, dataclasses, project lifecycle.
"""

import re

from harness.schema import (
    Artifact,
    Message,
    OrchestratorPlan,
    Project,
    Session,
    _append_jsonl,
    _now_iso,
    _read_jsonl,
    create_project,
    end_session,
    list_projects,
    make_id,
    resolve_project_id,
    start_session,
)


class TestMakeId:

    def test_format(self):
        assert re.match(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$", make_id())

    def test_length(self):
        assert len(make_id()) == 29

    def test_lexicographic_order(self):
        import time
        a = make_id()
        time.sleep(1.05)
        b = make_id()
        assert a < b

    def test_uniqueness(self):
        assert len({make_id() for _ in range(100)}) == 100


class TestNowIso:

    def test_returns_iso_string(self):
        ts = _now_iso()
        assert "T" in ts


class TestJsonlIO:

    def test_append_and_read(self, tmp_path):
        path = str(tmp_path / "test.jsonl")
        _append_jsonl(path, {"key": "value1"})
        _append_jsonl(path, {"key": "value2"})
        records = _read_jsonl(path)
        assert len(records) == 2
        assert records[0]["key"] == "value1"
        assert records[1]["key"] == "value2"

    def test_read_missing_file(self, tmp_path):
        assert _read_jsonl(str(tmp_path / "nonexistent.jsonl")) == []

    def test_read_skips_bad_lines(self, tmp_path):
        path = str(tmp_path / "mixed.jsonl")
        with open(path, "w") as f:
            f.write('{"good": true}\nnot json\n{"also_good": true}\n')
        records = _read_jsonl(path)
        assert len(records) == 2


class TestDataclasses:

    def test_project_defaults(self):
        p = Project(name="test")
        assert p.status == "active"
        assert len(p.project_id) == 29
        assert p.tags == []

    def test_project_to_dict(self):
        d = Project(name="test").to_dict()
        assert d["name"] == "test"
        assert "project_id" in d

    def test_session_defaults(self):
        s = Session(project_id="proj-123")
        assert s.triggered_by == "cli"
        assert s.runs == 0

    def test_artifact_type(self):
        assert Artifact(type="kg").type == "kg"

    def test_message_to_dict(self):
        d = Message(run_id="r1", seq=0, role="user", content="hello").to_dict()
        assert d["role"] == "user"
        assert d["content"] == "hello"

    def test_orchestrator_plan_fields(self):
        d = OrchestratorPlan(task="test task", complexity="high").to_dict()
        assert d["complexity"] == "high"
        assert d["subtasks"] == []


class TestProjectLifecycle:

    def test_create_and_list(self, tmp_data_dir):
        create_project("test-project", "desc", ["tag1"])
        assert any(p["name"] == "test-project" for p in list_projects())

    def test_resolve_creates_default(self, tmp_data_dir):
        pid = resolve_project_id()
        assert len(pid) == 29

    def test_session_start_end(self, tmp_data_dir):
        pid = resolve_project_id()
        session = start_session(pid, triggered_by="test")
        assert session.project_id == pid
        end_session(session, runs=1)
        assert session.ended_at is not None
