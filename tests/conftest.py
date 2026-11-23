"""Shared pytest fixtures for the whole suite.

The app uses a single global QueueManager, so without care, tasks from one
test would leak into the next. These fixtures:
  * reset_state  - (autouse) clears all tasks/counters before every test.
  * single_worker / three_workers - pin the worker count for deterministic
    ordering vs. concurrency tests, then restore the configured default.

All worker-count changes happen BEFORE the TestClient starts the workers
(start() reads the count in the lifespan handler).
"""

import pytest

from app import config
from app.queue_manager import queue_manager

# Tests always run in-memory: never touch a real Redis server, so the suite
# stays fast, deterministic, and can't pollute real data.
config.REDIS_ENABLED = False


@pytest.fixture(autouse=True)
def reset_state():
    """Give every test a clean manager (no leftover tasks/counters)."""
    queue_manager.reset()
    queue_manager.set_worker_count(config.WORKER_COUNT)
    yield
    queue_manager.reset()


@pytest.fixture
def single_worker():
    """Pin to exactly one worker, then restore the default."""
    queue_manager.set_worker_count(1)
    yield 1
    queue_manager.set_worker_count(config.WORKER_COUNT)


@pytest.fixture
def three_workers():
    """Pin to exactly three workers, then restore the default."""
    queue_manager.set_worker_count(3)
    yield 3
    queue_manager.set_worker_count(config.WORKER_COUNT)
