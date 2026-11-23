"""Task 1 - basic queue: submission, health, and execution."""

import time

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_submit_returns_pending_immediately():
    """POST /tasks returns right away with a pending task (work is queued,
    not run inside the request)."""
    with TestClient(app) as client:
        r = client.post("/tasks", json={"task_type": "demo", "duration": 0})
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "pending"
        assert body["task_id"].startswith("task_")
        assert body["message"] == "Task added to queue"


def test_list_tasks():
    with TestClient(app) as client:
        for n in ["a", "b", "c"]:
            client.post("/tasks", json={"task_type": n, "duration": 0})
        tasks = client.get("/tasks").json()
        assert len(tasks) == 3


def test_get_unknown_task_returns_404():
    with TestClient(app) as client:
        assert client.get("/tasks/task_missing").status_code == 404


def test_tasks_execute_in_fifo_order(single_worker):
    """With one worker and equal priority, tasks run in submission order."""
    with TestClient(app) as client:
        ids = [
            client.post("/tasks", json={"task_type": n, "duration": 1}).json()["task_id"]
            for n in ["A", "B", "C"]
        ]
        time.sleep(4)  # single worker, 1s each
        starts = []
        for tid in ids:
            d = client.get(f"/tasks/{tid}").json()
            assert d["status"] == "completed"
            assert d["result"] == "Task completed successfully"
            starts.append((d["task_type"], d["started_at"]))
        order = [name for name, _ in sorted(starts, key=lambda x: x[1])]
        assert order == ["A", "B", "C"]
