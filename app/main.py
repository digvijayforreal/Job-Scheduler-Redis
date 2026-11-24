"""FastAPI application and HTTP routes.

Endpoints:
  POST   /tasks          - add a task to the queue
  GET    /tasks/{id}     - check a task's status
  GET    /tasks          - list all tasks
  DELETE /tasks/{id}     - cancel a pending task
  GET    /queue/status   - queue + scheduler snapshot
  GET    /health         - health check

The UI is served as static files at '/' and the worker(s)/scheduler are
started on startup and stopped on shutdown via the lifespan handler.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .models import QueueStatus, Task, TaskCreate, TaskDetail, TaskResponse
from .queue_manager import queue_manager

from . import config


STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background workers on startup, stop them on shutdown.

    If Redis is enabled and reachable, attach it so tasks persist across
    restarts; otherwise log a note and run in-memory.
    """
    if config.REDIS_ENABLED:
        try:
            from .persistence import RedisStore

            queue_manager.attach_store(RedisStore(config.REDIS_URL, config.REDIS_TASK_TTL))
            print("Redis persistence enabled")
        except Exception as exc:
            print(f"Redis unavailable ({exc}); using in-memory storage")

    queue_manager.start()
    yield
    await queue_manager.stop()


app = FastAPI(title="Background Task Queue & Job Scheduler", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send visitors to the UI."""
    return RedirectResponse(url="/ui/")


@app.get("/health")
async def health() -> dict:
    """Simple liveness check."""
    return {"status": "ok"}


@app.get("/queue/status", response_model=QueueStatus)
async def queue_status() -> QueueStatus:
    """Report queue size, scheduled count, and status breakdown."""
    return QueueStatus(**queue_manager.status())


@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(payload: TaskCreate) -> TaskResponse:
    """Add a task to the queue. Returns immediately with PENDING status."""
    task = Task(
        task_type=payload.task_type,
        duration=payload.duration,
        priority=payload.priority,
        scheduled_at=payload.scheduled_at,
        should_fail=payload.should_fail,
        max_retries=payload.max_retries,
        schedule_policy=payload.schedule_policy,
    )
    queue_manager.submit(task)
    return TaskResponse(
        task_id=task.task_id,
        status=task.status,
        message="Task added to queue",
    )


@app.get("/tasks", response_model=list[TaskDetail])
async def list_tasks() -> list[TaskDetail]:
    """List all tasks, newest first."""
    return [TaskDetail.from_task(t) for t in queue_manager.list_all()]


@app.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str) -> TaskDetail:
    """Fetch a single task by id."""
    task = queue_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskDetail.from_task(task)


@app.delete("/tasks/{task_id}", response_model=TaskResponse)
async def cancel_task(task_id: str) -> TaskResponse:
    """Cancel a pending task.

    Only pending tasks can be cancelled. Running/completed/failed tasks
    return 409 Conflict; unknown ids return 404.
    """
    try:
        task = queue_manager.cancel(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return TaskResponse(
        task_id=task.task_id,
        status=task.status,
        message="Task cancelled",
    )


# Serve the single-page UI (index.html, styles.css, app.js) at /ui.
# Mounted last so it never shadows the API routes above.
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
