"""Bonus features - auto-retry (#1) and queue statistics (#3)."""

import time

from fastapi.testclient import TestClient

from app.main import app


def test_failed_task_is_retried_then_fails():
    """A failing task retries up to max_retries, then ends FAILED."""
    with TestClient(app) as client:
        tid = client.post(
            "/tasks",
            json={"task_type": "boom", "duration": 0, "should_fail": True, "max_retries": 3},
        ).json()["task_id"]
        time.sleep(3)
        d = client.get(f"/tasks/{tid}").json()
        assert d["status"] == "failed"
        assert d["retries"] == 3
        assert d["max_retries"] == 3


def test_no_retries_when_disabled():
    """max_retries=0 means a failing task fails immediately, no retries."""
    with TestClient(app) as client:
        tid = client.post(
            "/tasks",
            json={"task_type": "boom", "duration": 0, "should_fail": True, "max_retries": 0},
        ).json()["task_id"]
        time.sleep(1)
        d = client.get(f"/tasks/{tid}").json()
        assert d["status"] == "failed"
        assert d["retries"] == 0


def test_successful_task_has_no_retries():
    with TestClient(app) as client:
        tid = client.post("/tasks", json={"task_type": "ok", "duration": 0}).json()["task_id"]
        time.sleep(1)
        d = client.get(f"/tasks/{tid}").json()
        assert d["status"] == "completed"
        assert d["retries"] == 0


def test_average_execution_time_stat():
    """avg_execution_time is the mean over completed tasks."""
    with TestClient(app) as client:
        client.post("/tasks", json={"task_type": "a", "duration": 1})
        client.post("/tasks", json={"task_type": "b", "duration": 3})
        time.sleep(5)
        s = client.get("/queue/status").json()
        assert s["completed"] == 2
        # mean of 1s and 3s is ~2s
        assert 1.8 <= s["avg_execution_time"] <= 2.3
