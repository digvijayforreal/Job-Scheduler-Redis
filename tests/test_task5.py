"""Task 5 - multiple workers and concurrency."""

import time

from fastapi.testclient import TestClient

from app.main import app


def test_runs_up_to_n_concurrently(three_workers):
    """With 3 workers and 6 tasks, at most 3 run at once - never more."""
    n = three_workers
    with TestClient(app) as client:
        for i in range(6):
            client.post("/tasks", json={"task_type": f"job{i}", "duration": 2})

        # Sample the live 'running' count while they execute.
        max_running = 0
        for _ in range(20):
            max_running = max(max_running, client.get("/queue/status").json()["running"])
            time.sleep(0.2)

        status = client.get("/queue/status").json()
        assert max_running <= n              # never exceeded the worker count
        assert status["peak_running"] == n   # reached full concurrency


def test_worker_count_reported(three_workers):
    with TestClient(app) as client:
        assert client.get("/queue/status").json()["worker_count"] == 3


def test_all_tasks_complete_with_concurrency(three_workers):
    """Every submitted task finishes when run concurrently."""
    with TestClient(app) as client:
        ids = [
            client.post("/tasks", json={"task_type": "c", "duration": 1}).json()["task_id"]
            for _ in range(6)
        ]
        time.sleep(4)  # 6 tasks / 3 workers * 1s ~= 2s, plus margin
        for tid in ids:
            assert client.get(f"/tasks/{tid}").json()["status"] == "completed"
