"""Optional Redis persistance - stores tasks so they survive a restart."""

import json 

from .models import Task

import redis

KEY_PREFIX = "_task:"

class RedisStore:
    def __init__(self,url):
        self._client = redis.Redis.from_url(url, decode_responses = True)
        self._client.ping() #raises if no server is reachable

    def save(self, task):
        self._client.set(KEY_PREFIX + task.task_id, json.dumps(task.to_dict())) 

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
