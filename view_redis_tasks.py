"""View all tasks currently stored in Redis.

Run with:  python view_redis_tasks.py
Reads REDIS_URL from your .env / environment and prints every saved task.
"""

from app import config
from app.persistence import RedisStore


def main() -> None:
    store = RedisStore(config.REDIS_URL)
    tasks = store.load_all()

    print(f"Total tasks in Redis: {len(tasks)}")
    print("-" * 70)
    # Sort newest first.
    for t in sorted(tasks, key=lambda x: x.created_at, reverse=True):
        exec_time = f"{t.execution_time:.1f}s" if t.execution_time else "-"
        print(
            f"{t.task_id}  "
            f"{t.task_type:<18} "
            f"{t.status.value:<10} "
            f"prio={t.priority.value:<7} "
            f"exec={exec_time}"
        )


if __name__ == "__main__":
    main()
