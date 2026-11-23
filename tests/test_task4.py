"""Task 4 - scheduling and queue status."""

import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


def test_scheduled_task_waits_then_runs():
    """A task scheduled ~2s in the future stays pending, then runs."""
    with TestClient(app) as client:
        run_at = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
        tid = client.post(
            "/tasks",
            json={"task_type": "future", "duration": 0, "scheduled_at": run_at},
        ).json()["task_id"]

        assert client.get(f"/tasks/{tid}").json()["status"] == "pending"
        assert client.get("/queue/status").json()["scheduled"] >= 1

        time.sleep(1)  # before its time
        assert client.get(f"/tasks/{tid}").json()["status"] == "pending"

        time.sleep(2.5)  # after its time + a poll
        assert client.get(f"/tasks/{tid}").json()["status"] == "completed"


def test_past_scheduled_time_runs_immediately():
    """A scheduled_at in the past is treated as run-now."""
    with TestClient(app) as client:
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        tid = client.post(
            "/tasks",
            json={"task_type": "past", "duration": 0, "scheduled_at": past},
        ).json()["task_id"]
        time.sleep(1)
        assert client.get(f"/tasks/{tid}").json()["status"] == "completed"


def test_cancel_scheduled_task():
    """A scheduled task can be cancelled before its time and never runs."""
    with TestClient(app) as client:
        run_at = (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()
        tid = client.post(
            "/tasks",
            json={"task_type": "cancelme", "duration": 0, "scheduled_at": run_at},
        ).json()["task_id"]

        assert client.delete(f"/tasks/{tid}").status_code == 200
        time.sleep(4)  # past its scheduled time
        assert client.get(f"/tasks/{tid}").json()["status"] == "cancelled"


def test_queue_status_shape():
    """The status endpoint reports all expected fields."""
    with TestClient(app) as client:
        s = client.get("/queue/status").json()
        for key in [
            "worker_count", "queued", "scheduled", "pending", "running",
            "completed", "failed", "cancelled", "total", "peak_running",
        ]:
            assert key in s
