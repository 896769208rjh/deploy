import asyncio
from collections import defaultdict


class RunHub:
    def __init__(self) -> None:
        self.buffers: dict[str, list[dict]] = defaultdict(list)
        self.subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self.lock = asyncio.Lock()

    async def publish(self, run_id: str, event: dict) -> None:
        async with self.lock:
            bucket = self.buffers[run_id]
            bucket.append(event)
            if len(bucket) > 5000:
                del bucket[: len(bucket) - 5000]
            queues = list(self.subscribers.get(run_id, []))
        for queue in queues:
            queue.put_nowait(event)

    async def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self.lock:
            self.subscribers[run_id].append(queue)
            backlog = list(self.buffers.get(run_id, []))
        for event in backlog:
            await queue.put(event)
        return queue


hub = RunHub()
