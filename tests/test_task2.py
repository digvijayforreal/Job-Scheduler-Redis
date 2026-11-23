"""Task 2 - status tracking and cancellation."""

import time

from fastapi.testclient import TestClient

from app.main import app


def test_status_progresses_to_completed():
    """A task moves pending -> (running) -> completed with timestamps."""
    with TestClient(app) as client:
        tid = client.post("/tasks", json={"task_type": "demo", "duration": 1}).json()["task_id"]
        assert client.get(f"/tasks/{tid}").json()["status"] in {"pending", "running"}
        time.sleep(2)
        d = client.get(f"/tasks/{tid}").json()
        assert d["status"] == "completed"
        assert d["execution_time"] is not None
        assert d["started_at"] is not None
        assert d["finished_at"] is not None


def test_cancel_pending_task(single_worker):
    """A queued-but-not-yet-run task can be cancelled.

    Needs a single worker so the second task genuinely stays pending
    behind the blocker (with multiple workers it would start immediately).
    """
    with TestClient(app) as client:
        client.post("/tasks", json={"task_type": "blocker", "duration": 5})
        tid = client.post("/tasks", json={"task_type": "victim", "duration": 1}).json()["task_id"]

        r = client.delete(f"/tasks/{tid}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        assert client.get(f"/tasks/{tid}").json()["status"] == "cancelled"


def test_cannot_cancel_finished_task():
    """Cancelling a completed task returns 409 Conflict."""
    with TestClient(app) as client:
        tid = client.post("/tasks", json={"task_type": "quick", "duration": 0}).json()["task_id"]
        time.sleep(1)
        assert client.get(f"/tasks/{tid}").json()["status"] == "completed"
        assert client.delete(f"/tasks/{tid}").status_code == 409


def test_cancel_unknown_task_returns_404():
    with TestClient(app) as client:
        assert client.delete("/tasks/task_nonexistent").status_code == 404
