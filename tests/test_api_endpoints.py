"""
Verify all FastAPI endpoints return correct status codes and response shapes.
Uses fastapi.testclient.TestClient — no subprocess spawned, no LLM calls.
"""

from fastapi.testclient import TestClient

from harness.api.main import app

client = TestClient(app)


class TestRunsEndpoints:

    def test_runs_returns_active_and_recent(self):
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data and "recent" in data
        assert isinstance(data["active"], list)
        assert isinstance(data["recent"], list)

    def test_all_runs_returns_list(self):
        resp = client.get("/api/runs/all")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_data_returns_kpi_structure(self):
        resp = client.get("/api/data")
        assert resp.status_code == 200
        data = resp.json()
        assert "kpi" in data
        kpi = data["kpi"]
        assert "total_runs" in kpi
        assert "pass_rate" in kpi
        assert "mean_score" in kpi
        assert "mean_duration_s" in kpi


class TestHistoryEndpoints:

    def test_sessions_returns_list(self):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_plans_returns_list(self):
        resp = client.get("/api/plans")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_artifacts_returns_list(self):
        resp = client.get("/api/artifacts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_curation_returns_list(self):
        resp = client.get("/api/curation")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestTasksEndpoint:

    def test_submit_requires_task(self):
        resp = client.post("/api/tasks", json={})
        assert resp.status_code == 422  # FastAPI validation error

    def test_submit_empty_task_rejected(self):
        resp = client.post("/api/tasks", json={"task": ""})
        # Either 422 (pydantic min_length) or 400 (explicit validation)
        assert resp.status_code in (400, 422)

    def test_submit_valid_task_returns_item_id(self):
        resp = client.post("/api/tasks", json={"task": "test task"})
        assert resp.status_code == 202
        data = resp.json()
        assert "item_id" in data
        assert "status" in data
        assert data["status"] == "pending"


class TestQueueEndpoints:

    def test_queue_state_returns_list(self):
        resp = client.get("/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "pending" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["pending"], int)


class TestMcpLogEndpoint:

    def test_mcp_log_returns_list(self):
        resp = client.get("/api/mcp/log")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMcpToolsEndpoint:

    def test_mcp_tools_returns_three_tools(self):
        resp = client.get("/api/mcp/tools")
        assert resp.status_code == 200
        tools = resp.json()
        assert isinstance(tools, list)
        assert len(tools) == 3
        names = {t["name"] for t in tools}
        assert names == {"run_task", "run_orchestrated", "get_run"}
        for t in tools:
            assert "description" in t
            assert "parameters" in t
            assert isinstance(t["parameters"], list)

    def test_mcp_tools_have_required_param_flag(self):
        resp = client.get("/api/mcp/tools")
        tools = resp.json()
        for t in tools:
            for p in t["parameters"]:
                assert "name" in p
                assert "type" in p
                assert "required" in p


class TestWebSocketRoute:

    def test_ws_runs_endpoint_exists(self):
        # Verify the WebSocket route is registered without opening a real connection
        routes = [r.path for r in app.routes]
        assert any("/ws" in r for r in routes), f"No /ws route found in {routes}"
