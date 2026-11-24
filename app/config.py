"""Application configuration.

Central place for tunable settings so we don't scatter magic numbers
across the codebase. For Task 1 we only need a single worker, but we
keep this configurable so later tasks (multiple workers) are an easy
one-line change.
"""
import os

# Load the .env file at the project root so REDIS_URL / REDIS_ENABLED can
# live in a file instead of being typed each run. Safe if python-dotenv
# isn't installed - we just skip it.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Number of background workers that pull tasks off the queue.
# With N workers, up to N tasks run concurrently and never more. Set to 1
# for strict one-at-a-time ordering; raise it for real concurrency.
WORKER_COUNT = 2

# How often (in seconds) the scheduler wakes up to check whether any
# scheduled tasks are now due to be moved into the run queue. A small
# value makes scheduled tasks start closer to their requested time.
SCHEDULER_POLL_INTERVAL = 0.5

REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() in  ("1","true","yes")

# Redis connection string. It comes only from .env or the environment and
# never lives in code. See .env.example for the format.
REDIS_URL = os.getenv("REDIS_URL", "")

# Seconds before a saved task auto-expires (TTL) in Redis.
# This default (1 hour) is used unless you override REDIS_TASK_TTL in .env.
# Set to 0 to keep tasks forever (no expiry).
REDIS_TASK_TTL = int(os.getenv("REDIS_TASK_TTL", "3600"))
