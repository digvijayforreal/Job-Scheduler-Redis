"""Optional Redis persistance - stores tasks so they survive a restart."""

import json 

from .models import Task

import redis

KEY_PREFIX = "_task:"

class RedisStore:
    def __init__(self, url, ttl=0):
        if not url:
            raise ValueError("REDIS_URL is not set; add it to your .env file")
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._client.ping()  # raises if no server is reachable
        # ttl = seconds before a saved task auto-expires. 0 = never expire.
        self._ttl = ttl

    def save(self, task):
        data = json.dumps(task.to_dict())
        if self._ttl > 0:
            # 'ex' sets a TTL (in seconds); Redis deletes the key when it runs out.
            self._client.set(KEY_PREFIX + task.task_id, data, ex=self._ttl)
        else:
            self._client.set(KEY_PREFIX + task.task_id, data)

    def load_all(self):
        tasks = []
        for key in self._client.scan_iter(match=KEY_PREFIX + "*"):  
            raw = self._client.get(key)
            if raw:
                tasks.append(Task.from_dict(json.loads(raw)))
        return tasks
    
    def clear(self) :
        for key in self._client.scan_iter(match = KEY_PREFIX + "*"):
            self._client.delete(key)
