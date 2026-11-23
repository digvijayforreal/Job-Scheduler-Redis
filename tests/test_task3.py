"""Task 3 - priority queue ordering."""

import time

from fastapi.testclient import TestClient

from app.main import app


def test_priority_execution_order(single_worker):
    """With the one worker busy, waiting tasks run high -> medium -> low,
    and FIFO within the same priority.

    Assignment example: A(low) B(high) C(medium) D(high) runs B -> D -> C -> A.
    """
    with TestClient(app) as client:
        # Occupy the single worker so A/B/C/D all queue up while it's busy.
        client.post("/tasks", json={"task_type": "blocker", "duration": 2})

        submissions = [("A", "low"), ("B", "high"), ("C", "medium"), ("D", "high")]
        ids = {}
        for name, prio in submissions:
            # 1s each so their start times are clearly separated and
            # sortable (duration 0 would tie within one clock tick).
            r = client.post(
                "/tasks",
                json={"task_type": name, "duration": 1, "priority": prio},
            )
            ids[name] = r.json()["task_id"]

        time.sleep(7)  # blocker (2s) + four tasks (1s each)

        details = []
        for name, tid in ids.items():
            d = client.get(f"/tasks/{tid}").json()
            assert d["status"] == "completed", f"{name} is {d['status']}"
            details.append((d["task_type"], d["started_at"]))

        order = [name for name, _ in sorted(details, key=lambda x: x[1])]
        assert order == ["B", "D", "C", "A"], f"got {order}"


def test_default_priority_is_medium():
    """Omitting priority defaults to medium."""
    with TestClient(app) as client:
        tid = client.post("/tasks", json={"task_type": "x", "duration": 0}).json()["task_id"]
        time.sleep(0.5)
        assert client.get(f"/tasks/{tid}").json()["priority"] == "medium"
