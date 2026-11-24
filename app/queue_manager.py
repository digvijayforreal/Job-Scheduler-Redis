"""The queue manager: storage + queue + background worker.

This is the heart of the system. It holds:
  * `_tasks`  - an in-memory dict mapping task_id -> Task (our "database").
  * `_queue`  - an asyncio.Queue the worker pulls from.
  * worker coroutines started on app startup and cancelled on shutdown.

Queueing: we use an asyncio.PriorityQueue so high-priority tasks run
before lower-priority ones that are still waiting. Within the same
priority level, tasks keep submission order (FIFO). Execution is
simulated with asyncio.sleep(duration).
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Dict, List, Optional, Tuple

from datetime import timezone

from .config import SCHEDULER_POLL_INTERVAL, WORKER_COUNT
from .models import SchedulePolicy, Task, TaskStatus, _now

# What we actually put on the queue: (priority_rank, sequence, task_id).
#   priority_rank - high=1, medium=2, low=3 (min-heap pops smallest first)
#   sequence      - monotonic counter; breaks ties so equal-priority tasks
#                   stay FIFO, and stops Python ever comparing task_ids.
#   task_id       - the id we look up in the _tasks dict.
QueueItem = Tuple[int, int, str]


class QueueManager:
    """Owns task storage, the queue, and the worker coroutines."""

    def __init__(self, worker_count: int = WORKER_COUNT) -> None:
        self._tasks: Dict[str, Task] = {}
        # The queue is created in start(), NOT here. An asyncio.Queue binds
        # to the event loop that first touches it. Creating it at import
        # time would bind it to whatever loop happens to run first, which
        # breaks when a new loop is used later (e.g. each pytest test gets a
        # fresh loop). Creating it in start() ties it to the worker's own
        # loop every time.
        self._queue: Optional[asyncio.PriorityQueue[QueueItem]] = None
        self._worker_count = worker_count
        self._workers: List[asyncio.Task] = []
        # Monotonic counter that gives every queued item a unique, ever-
        # increasing sequence number for FIFO tie-breaking.
        self._counter = itertools.count()
        # Tasks waiting for a future scheduled_at. The scheduler loop moves
        # them into the real queue once their time arrives. Keyed by id so
        # we can drop cancelled ones cheaply.
        self._scheduled: Dict[str, Task] = {}
        self._scheduler: Optional[asyncio.Task] = None
        # Live concurrency tracking: how many tasks are executing right now,
        # and the most we ever ran at once. The peak lets us prove we never
        # exceed the worker count.
        self._running_now = 0
        self._peak_running = 0
        self._store = None

    def _get_queue(self) -> "asyncio.PriorityQueue[QueueItem]":
        """Return the queue, creating it on first use if needed."""
        if self._queue is None:
            self._queue = asyncio.PriorityQueue()
        return self._queue
    
    def attach_store(self, store):
        self._store = store
    
    def _save(self, task):
        if self._store is not None:
            try:
                self._store.save(task)
            except Exception:
                pass

    def reset(self) -> None:
        """Wipe all stored tasks and counters. Only valid while stopped.

        Used by tests to get a clean slate between cases, since the app
        uses one shared manager instance for its whole lifetime.
        """
        if self._workers:
            raise RuntimeError("Cannot reset while running")
        self._tasks.clear()
        self._scheduled.clear()
        self._counter = itertools.count()
        self._running_now = 0
        self._peak_running = 0

    def set_worker_count(self, count: int) -> None:
        """Change how many workers will run. Only valid while stopped.

        Used mainly by tests that need deterministic ordering (count=1).
        Raising it mid-run is not allowed because workers are created in
        start(); change it before the app/lifespan starts.
        """
        if self._workers:
            raise RuntimeError("Cannot change worker count while running")
        if count < 1:
            raise ValueError("Worker count must be at least 1")
        self._worker_count = count

    # --- public API used by the routes ---------------------------------

    def submit(self, task: Task) -> Task:
        """Store a task, then either enqueue it now or hold it for later.

        If `scheduled_at` is set to a future time, the task is parked in the
        scheduled holding area and the scheduler loop releases it into the
        run queue when its time comes. Otherwise it goes straight to the
        queue.
        """
        # Normalise a naive datetime to UTC so comparisons never crash.
        if task.scheduled_at is not None and task.scheduled_at.tzinfo is None:
            task.scheduled_at = task.scheduled_at.replace(tzinfo=timezone.utc)

        self._tasks[task.task_id] = task

        if task.scheduled_at is not None and task.scheduled_at > _now():
            # Hold it back; the scheduler loop will release it when due.
            self._scheduled[task.task_id] = task
            self._save(task)
        else:
            self._release(task)
        return task

    def _has_free_slot(self) -> bool:
        """True if a task could start running immediately - i.e. there's an
        idle worker with nothing already queued ahead of it."""
        queued = self._queue.qsize() if self._queue is not None else 0
        return (self._worker_count - self._running_now - queued) > 0

    def _release(self, task: Task) -> None:
        """Send a due task to the queue, or fail it per its schedule policy.

        With the default 'queue' policy the task waits in the queue. With
        'fail', if no worker is free right now the task is marked failed
        instead of waiting.
        """
        if task.schedule_policy == SchedulePolicy.FAIL and not self._has_free_slot():
            task.status = TaskStatus.FAILED
            task.error = "Could not start at scheduled time (all workers busy)"
            task.finished_at = _now()
        else:
            self._enqueue(task)
        self._save(task)

    def _enqueue(self, task: Task) -> None:
        """Put a task's id onto the priority queue, ready to run.

        We queue a (priority, sequence, id) tuple. The PriorityQueue sorts
        by priority first, then sequence (submission order) for ties. We
        store the id (not the object) so the _tasks dict stays the single
        source of truth for task state.
        """
        item: QueueItem = (task.priority.rank, next(self._counter), task.task_id)
        self._get_queue().put_nowait(item)

    def get(self, task_id: str) -> Optional[Task]:
        """Look up a single task, or None if the id is unknown."""
        return self._tasks.get(task_id)

    def list_all(self) -> List[Task]:
        """Return every task, newest-created first."""
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def cancel(self, task_id: str) -> Task:
        """Cancel a task that is still pending.

        Returns the updated task on success. Raises:
          * KeyError   - no task with this id (route maps to 404).
          * ValueError - task exists but is not pending, so it can't be
                         cancelled (route maps to 409 Conflict).

        Note: we don't try to pull the id out of the asyncio.Queue (there
        is no clean API for that). Instead we flip the status to CANCELLED
        here, and the worker skips any cancelled task when it pops it. This
        is the standard "tombstone" approach for a queue you can't reach
        into.
        """
        from .models import _now

        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status != TaskStatus.PENDING:
            raise ValueError(
                f"Task is '{task.status.value}' and can no longer be cancelled"
            )
        task.status = TaskStatus.CANCELLED
        task.finished_at = _now()
        # If it was waiting on a schedule, drop it from the holding area so
        # the scheduler never releases it.
        self._scheduled.pop(task_id, None)
        self._save(task)
        return task

    def status(self) -> dict:
        """Build a snapshot of queue/scheduler counts for the API."""
        counts = {s: 0 for s in TaskStatus}
        exec_times = []
        for task in self._tasks.values():
            counts[task.status] += 1
            # Average execution time over tasks that actually finished running.
            if task.status == TaskStatus.COMPLETED and task.execution_time is not None:
                exec_times.append(task.execution_time)
        queued = self._queue.qsize() if self._queue is not None else 0
        avg_exec = round(sum(exec_times) / len(exec_times), 3) if exec_times else None
        return {
            "worker_count": self._worker_count,
            "queued": queued,
            "scheduled": len(self._scheduled),
            "pending": counts[TaskStatus.PENDING],
            "running": counts[TaskStatus.RUNNING],
            "completed": counts[TaskStatus.COMPLETED],
            "failed": counts[TaskStatus.FAILED],
            "cancelled": counts[TaskStatus.CANCELLED],
            "total": len(self._tasks),
            "peak_running": self._peak_running,
            "avg_execution_time": avg_exec,
        }

    # --- worker lifecycle ----------------------------------------------

    def start(self) -> None:
        """Spawn the background worker coroutine(s).

        Creates a fresh queue bound to the current running loop, so a new
        app lifecycle (or a new test's event loop) always gets a working
        queue instead of one stuck on a dead loop.
        """
        self._queue = asyncio.PriorityQueue()
        # Reset concurrency tracking for this fresh lifecycle.
        self._running_now = 0
        self._peak_running = 0
        if self._store is not None:
            self._restore_from_store()
        for i in range(self._worker_count):
            worker = asyncio.create_task(self._worker_loop(worker_id=i))
            self._workers.append(worker)
        # Start the scheduler loop that releases due scheduled tasks.
        self._scheduler = asyncio.create_task(self._scheduler_loop())

    async def stop(self) -> None:
        """Cancel all workers and the scheduler cleanly on shutdown."""
        tasks = list(self._workers)
        if self._scheduler is not None:
            tasks.append(self._scheduler)
        for t in tasks:
            t.cancel()
        # Wait for them to actually finish unwinding.
        await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        self._scheduler = None
        self._queue = None

    def _restore_from_store(self):
        now = _now()
        for task in self._store.load_all():
            self._tasks[task.task_id] = task
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PENDING
            if task.status == TaskStatus.PENDING:
                if task.scheduled_at and task.scheduled_at > now:
                    self._scheduled[task.task_id] = task
                else:
                    self._enqueue(task)

    async def _scheduler_loop(self) -> None:
        """Periodically release scheduled tasks whose time has arrived.

        Runs until cancelled. Every poll it checks the holding area and
        enqueues any task that is now due and still pending. A task may
        start slightly after its scheduled time (up to one poll interval,
        or longer if all workers are busy) - that's acceptable per the
        assignment.
        """
        while True:
            await asyncio.sleep(SCHEDULER_POLL_INTERVAL)
            now = _now()
            due = [
                task
                for task in self._scheduled.values()
                if task.scheduled_at is not None and task.scheduled_at <= now
            ]
            for task in due:
                # Remove from holding first, then release if still pending.
                self._scheduled.pop(task.task_id, None)
                if task.status == TaskStatus.PENDING:
                    self._release(task)

    # --- the worker itself ---------------------------------------------

    async def _worker_loop(self, worker_id: int) -> None:
        """Pull task ids off the queue forever and execute them.

        Runs until cancelled on shutdown. Each iteration blocks on
        `queue.get()` until a task is available, so an idle worker uses
        no CPU.
        """
        # Capture the queue created in start() so we always use the same
        # instance for the life of this worker.
        queue = self._get_queue()
        while True:
            # Unpack the tuple; we only need the task_id to find the task.
            _priority, _seq, task_id = await queue.get()
            try:
                task = self._tasks.get(task_id)
                # Skip tasks that were cancelled while waiting in the queue.
                # Their status is already CANCELLED; we just don't run them.
                if task is not None and task.status == TaskStatus.PENDING:
                    await self._execute(task)
            finally:
                # Always mark the queue item done, even on error, so the
                # queue's internal counter stays correct.
                queue.task_done()

    async def _execute(self, task: Task) -> None:
        """Run a single task, flipping its status and recording the result.

        Execution is simulated with asyncio.sleep(duration). Any exception
        is captured and turns the task FAILED instead of crashing the
        worker loop.
        """
        from .models import _now  # local import to avoid clutter at top

        task.status = TaskStatus.RUNNING
        task.started_at = _now()
        self._save(task)
        # Bump the live counter and record a new peak if this is the most
        # concurrent we've ever been.
        self._running_now += 1
        self._peak_running = max(self._peak_running, self._running_now)
        try:
            await asyncio.sleep(task.duration)
            # Simulated failure path: a real task would raise here naturally
            # (bad input, network error, etc). We trigger it on demand.
            if task.should_fail:
                raise RuntimeError("Task failed (should_fail=True)")
            task.status = TaskStatus.COMPLETED
            task.result = "Task completed successfully"
        except asyncio.CancelledError:
            # The worker was cancelled mid-execution (e.g. app shutdown).
            # CancelledError is a BaseException, so it is NOT caught by the
            # generic handler below. Mark the task as failed/interrupted so
            # it never lingers as RUNNING, then re-raise so the cancellation
            # actually propagates and the worker stops.
            task.status = TaskStatus.FAILED
            task.error = "Interrupted (worker stopped)"
            raise
        except Exception as exc:  # noqa: BLE001 - we want to catch everything
            task.error = str(exc)
            if task.retries < task.max_retries:
                # Retries left: bump the counter, put the task back to
                # PENDING and re-queue it for another attempt.
                task.retries += 1
                task.status = TaskStatus.PENDING
                self._enqueue(task)
            else:
                # Out of retries: give up and mark it failed for good.
                task.status = TaskStatus.FAILED
        finally:
            task.finished_at = _now()
            self._running_now -= 1
            self._save(task)


# A single shared instance the whole app uses.
queue_manager = QueueManager()
