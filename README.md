# Background Task Queue & Job Scheduler

A background task queue and job scheduler built with **FastAPI** and Python's
**asyncio**. Users submit tasks through an API; instead of running them inside
the request, the system queues them and background workers execute them — one
by one or concurrently — with support for priorities, scheduling, retries, and
optional Redis persistence.

The queue, priority ordering, scheduler, and worker pool are all implemented
**from scratch** using standard-library primitives — no Celery, RQ, or
APScheduler.

![Dashboard preview](docs/dashboard.svg)

---

## Features

| # | Feature | Status |
|---|---------|--------|
| 1 | Basic queue with background worker | ✅ |
| 2 | Status tracking (pending / running / completed / failed / cancelled) + cancel | ✅ |
| 3 | Priority queue (high / medium / low) | ✅ |
| 4 | Scheduling tasks for future execution | ✅ |
| 5 | Multiple workers / concurrency (configurable) | ✅ |
| 6 | Automated test suite (22 tests) | ✅ |
| Bonus 1 | Auto-retry failed tasks (up to N times) | ✅ |
| Bonus 2 | Redis persistence (survive restarts) | ✅ |
| Bonus 3 | Queue statistics (completed / failed / avg execution time) | ✅ |

Plus a live web dashboard with real-time updates.

---

## Quick start

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- **Dashboard:** http://127.0.0.1:8000/
- **API docs (Swagger):** http://127.0.0.1:8000/docs

Run the tests:

```bash
pytest
```

---

## Project structure

```
job-scheduler/
├── app/
│   ├── config.py          # worker count, poll interval, Redis settings
│   ├── models.py          # Task record, enums, API schemas, (de)serialization
│   ├── queue_manager.py   # priority queue + worker pool + scheduler + store
│   ├── persistence.py     # optional Redis store (save / load tasks)
│   ├── main.py            # FastAPI app, routes, static UI mount
│   └── static/            # index.html, styles.css, app.js (dashboard)
├── tests/                 # pytest suite (one file per task + bonuses)
├── docs/dashboard.svg     # UI preview
├── .env                   # Redis settings (git-ignored)
├── pytest.ini
└── requirements.txt
```

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tasks` | Add a task to the queue |
| GET | `/tasks/{task_id}` | Check a task's status |
| GET | `/tasks` | List all tasks |
| DELETE | `/tasks/{task_id}` | Cancel a pending task |
| GET | `/queue/status` | Queue + scheduler snapshot and statistics |
| GET | `/health` | Health check |

### Submit a task

```json
POST /tasks
{
  "task_type": "data_processing",
  "duration": 5,
  "priority": "high",
  "scheduled_at": null,
  "should_fail": false,
  "max_retries": 3
}
```

Response:

```json
{
  "task_id": "task_a1b2c3d4",
  "status": "pending",
  "message": "Task added to queue"
}
```

- `priority` — `high`, `medium`, or `low` (default `medium`).
- `scheduled_at` — optional ISO-8601 time (e.g. `2026-11-13T15:30:00Z`); null or a past time runs as soon as possible.
- `should_fail` — if true, the task fails on purpose (to demo the failure/retry path).
- `max_retries` — how many times to retry on failure before giving up.

### Check a task

```json
GET /tasks/task_a1b2c3d4
{
  "task_id": "task_a1b2c3d4",
  "status": "completed",
  "priority": "high",
  "execution_time": 5.0,
  "result": "Task completed successfully"
}
```

---

## How it works

- **Queue** — an `asyncio.PriorityQueue` holds `(priority_rank, sequence, task_id)`
  tuples. Priority sorts first (high=1, medium=2, low=3); a monotonic sequence
  counter breaks ties so equal-priority tasks run in submission order (FIFO).
- **Storage** — a dict `task_id -> Task` is the single source of truth; the
  queue only carries ids.
- **Workers** — `WORKER_COUNT` worker coroutines share the queue. At most
  `WORKER_COUNT` tasks run at once; when a worker finishes, it grabs the next.
- **Scheduler** — a background loop polls every `SCHEDULER_POLL_INTERVAL`
  seconds and moves due scheduled tasks into the run queue.
- **Cancellation** — a pending task is marked `cancelled` (tombstone pattern);
  workers skip it when popped. Only pending tasks can be cancelled (409 otherwise).
- **Retry** — on failure, a task with retries left goes back to `pending` and is
  re-queued; once retries are exhausted it is marked `failed`.
- **Statistics** — `/queue/status` reports counts per status, peak concurrency,
  and average execution time over completed tasks.

---

## Configuration

Edit `app/config.py`:

- `WORKER_COUNT` — number of concurrent workers (default 3). Set to 1 for strict one-at-a-time ordering.
- `SCHEDULER_POLL_INTERVAL` — how often the scheduler checks for due tasks.

---

## Redis persistence (optional — bonus #2)

By default tasks are kept in memory and lost on restart. Enable Redis to make
them **survive restarts**. Redis is used only as a datastore — the queue,
scheduler, and workers remain hand-written code.

Settings live in a `.env` file at the project root:

```
REDIS_ENABLED=true
REDIS_URL=redis://default:PASSWORD@host:port
```

Then start the app normally — you'll see `Redis persistence enabled` at startup.
If Redis is disabled or unreachable, the app logs a note and runs in-memory
(nothing breaks).

**On startup it restores from Redis:** finished tasks reload as history, pending
tasks are re-queued, and tasks caught mid-run are reset to pending and run again.

**Getting a Redis server:** use a free cloud instance (e.g. Redis Cloud), or run
one locally with Docker: `docker run -p 6379:6379 redis`.

---

## Tests

```bash
pytest
```

22 tests cover submission, status transitions, cancellation, priority ordering,
scheduling, concurrency limits, retries, and statistics. Ordering tests pin the
worker count to 1; concurrency tests use 3, via fixtures in `tests/conftest.py`.
The suite always runs in-memory, so it never needs a Redis server.

---

## Design notes

- **asyncio over threads** — a single event loop makes "N concurrent workers"
  trivial (N coroutines) and avoids locks.
- **The dict is the truth, the queue is a to-do list of ids** — some ids may be
  stale (cancelled); workers simply skip them.
- **Simulated work** — `asyncio.sleep(duration)` stands in for real work;
  `should_fail` triggers the failure path on demand.
