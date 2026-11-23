"""Data models for tasks.

We separate three concerns here:
  1. TaskStatus  - the lifecycle states a task moves through.
  2. Task        - the internal record we store and mutate in memory.
  3. Pydantic schemas (TaskCreate / TaskResponse) - the shapes the API
     accepts and returns. Keeping API schemas separate from the internal
     record means we can change storage without breaking the API.

Task 1 scope: a task only needs a type and a duration. Priority and
scheduling fields are added in later tasks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Every state a task can be in during its lifecycle."""

    PENDING = "pending"      # created, waiting in the queue
    RUNNING = "running"      # a worker is currently executing it
    COMPLETED = "completed"  # finished successfully
    FAILED = "failed"        # raised an error during execution
    CANCELLED = "cancelled"  # cancelled by the user while still pending


class Priority(str, Enum):
    """Priority levels. The API uses the names ('high'/'medium'/'low')."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        """Numeric sort key: lower runs first (high=1, medium=2, low=3).

        A PriorityQueue is a min-heap, so the smallest value comes out
        first. We map 'high' to the smallest number so it runs first.
        """
        return {"high": 1, "medium": 2, "low": 3}[self.value]


def _now() -> datetime:
    """Timezone-aware 'now' in UTC. Used for all timestamps."""
    return datetime.now(timezone.utc)


def _new_id() -> str:
    """Generate a short unique task id like 'task_a1b2c3d4'."""
    return f"task_{uuid.uuid4().hex[:8]}"


@dataclass
class Task:
    """Internal in-memory record for a task.

    This is what the queue and workers operate on. It is mutable: the
    worker flips `status`, fills in `result`, and stamps timestamps as
    the task progresses.
    """

    task_type: str
    duration: int
    priority: Priority = Priority.MEDIUM
    task_id: str = field(default_factory=_new_id)
    status: TaskStatus = TaskStatus.PENDING

    # If True, the task deliberately raises when it runs, ending as FAILED.
    # Lets us demonstrate the failure path (our "work" is just a sleep that
    # never errors on its own).
    should_fail: bool = False

    # Auto-retry: how many times to re-run on failure before giving up, and
    # how many retries have been used so far.
    max_retries: int = 3
    retries: int = 0

    # When to run. None means "as soon as possible". A future time means the
    # scheduler holds it back until then.
    scheduled_at: Optional[datetime] = None

    # Bookkeeping timestamps.
    created_at: datetime = field(default_factory=_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Outcome of execution.
    result: Optional[str] = None
    error: Optional[str] = None

    @property
    def execution_time(self) -> Optional[float]:
        """Seconds spent actually running, or None if it hasn't run."""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict:
        """convert the task to plain JSON-friendly types for storage."""
        def iso (dt):
            return dt.isoformat() if dt else None
        
        return {
            "task_type": self.task_type,
            "duration": self.duration,
            "priority": self.priority.value,
            "task_id": self.task_id,
            "status": self.status.value,
            "should_fail": self.should_fail,
            "max_retries": self.max_retries,
            "retries": self.retries,
            "scheduled_at": iso(self.scheduled_at),
            "created_at": iso(self.created_at),
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
            "result": self.result,
            "error": self.error,
        }
    @classmethod
    def from_dict(cls, d:dict) -> "Task":
        """Rebuild a Task from the dict produced bt to_dict()."""
        def dt(v):
            return datetime.fromisoformat(v) if v else None

        return cls(
            task_type = d["task_type"],
            duration = d["duration"],
            priority = Priority(d["priority"]),
            task_id = d["task_id"],
            status = TaskStatus(d["status"]),
            should_fail = d.get("should_fail",False),
            max_retries  = d.get("max_retries",3),
            retries = d.get("retries",0),
            scheduled_at = dt(d.get("scheduled_at")), 
            created_at= dt(d.get("created_at")),
            started_at = dt(d.get("started_at")),
            finished_at = dt(d.get("finished_at")),
            result = d.get("result"),
            error = d.get("error"),
        )


# --- API schemas -----------------------------------------------------------


class TaskCreate(BaseModel):
    """Request body for POST /tasks."""

    task_type: str = Field(..., description="Label for the kind of work, e.g. 'data_processing'.")
    duration: int = Field(..., ge=0, description="How long the task takes, in seconds.")
    priority: Priority = Field(
        Priority.MEDIUM, description="high, medium, or low. Defaults to medium."
    )
    scheduled_at: Optional[datetime] = Field(
        None,
        description="ISO 8601 time to run the task, e.g. '2026-11-13T15:30:00Z'. "
        "Null or a past time means run as soon as possible.",
    )
    should_fail: bool = Field(
        False,
        description="If true, the task fails on purpose when it runs. Useful "
        "for demonstrating the FAILED status.",
    )
    max_retries: int = Field(
        3, ge=0, description="Times to automatically retry on failure before "
        "the task is marked failed for good.",
    )


class TaskResponse(BaseModel):
    """Shape returned when a task is created."""

    task_id: str
    status: TaskStatus
    message: str


class QueueStatus(BaseModel):
    """Snapshot of the queue/scheduler for GET /queue/status."""

    worker_count: int
    queued: int          # tasks sitting in the ready-to-run queue
    scheduled: int       # tasks waiting for a future scheduled_at
    pending: int
    running: int
    completed: int
    failed: int
    cancelled: int
    total: int
    peak_running: int = 0            # most tasks that ran at the same time
    avg_execution_time: Optional[float] = None  # mean seconds over completed tasks


class TaskDetail(BaseModel):
    """Full task view for GET /tasks/{id} and GET /tasks."""

    task_id: str
    task_type: str
    status: TaskStatus
    priority: Priority
    duration: int
    execution_time: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 0
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @classmethod
    def from_task(cls, task: Task) -> "TaskDetail":
        """Build the API view from an internal Task record."""
        return cls(
            task_id=task.task_id,
            task_type=task.task_type,
            status=task.status,
            priority=task.priority,
            duration=task.duration,
            execution_time=task.execution_time,
            result=task.result,
            error=task.error,
            retries=task.retries,
            max_retries=task.max_retries,
            created_at=task.created_at,
            scheduled_at=task.scheduled_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
        )
