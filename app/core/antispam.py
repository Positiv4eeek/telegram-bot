import time, asyncio
from collections import defaultdict, deque
from typing import Deque

REQS_PER_WINDOW = 3     # сколько запросов
WINDOW_SEC = 20         # за сколько секунд
COOLDOWN_SEC = 5        # мин. интервал между запросами
MAX_QUEUE = 2           # сколько задач держим в очереди на юзера

_last_seen: dict[int, float] = {}
_window_hits: dict[int, Deque[float]] = defaultdict(deque)
_user_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

_inflight: dict[tuple[int, str], asyncio.Task] = {}

_user_queues: dict[int, Deque[asyncio.Future]] = defaultdict(deque)

class RateLimitError(Exception): ...
class QueueOverflowError(Exception): ...

def check_rate(user_id: int):
    now = time.time()
    last = _last_seen.get(user_id, 0.0)
    if now - last < COOLDOWN_SEC:
        raise RateLimitError(f"Слишком часто, подожди {COOLDOWN_SEC - int(now - last)} сек.")
    hits = _window_hits[user_id]
    while hits and now - hits[0] > WINDOW_SEC:
        hits.popleft()
    if len(hits) >= REQS_PER_WINDOW:
        ttl = int(WINDOW_SEC - (now - hits[0]))
        raise RateLimitError(f"Лимит: {REQS_PER_WINDOW} запроса за {WINDOW_SEC} сек. Подожди ~{ttl} сек.")
    hits.append(now)
    _last_seen[user_id] = now

def get_user_lock(user_id: int) -> asyncio.Lock:
    return _user_locks[user_id]

def get_inflight_task(user_id: int, url: str) -> asyncio.Task | None:
    return _inflight.get((user_id, url))

def set_inflight_task(user_id: int, url: str, task: asyncio.Task):
    _inflight[(user_id, url)] = task
    task.add_done_callback(lambda t: _inflight.pop((user_id, url), None))

async def enqueue_or_fail(user_id: int):
    q = _user_queues[user_id]
    if len(q) >= MAX_QUEUE:
        raise QueueOverflowError("Слишком много задач в очереди, попробуй позже.")
    fut = asyncio.get_running_loop().create_future()
    q.append(fut)
    if q[0] is fut:
        fut.set_result(True)
    else:
        await fut

def dequeue(user_id: int):
    q = _user_queues[user_id]
    if q:
        q.popleft()
        if q:
            q[0].set_result(True)
