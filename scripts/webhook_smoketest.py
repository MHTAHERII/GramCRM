import asyncio
import sys
from pathlib import Path
# ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
from app.routers import webhook as w

# clear state
try:
    while not w.webhook_queue.empty():
        w.webhook_queue.get_nowait()
except Exception:
    pass
w._processed_event_cache.clear()

async def run_test():
    e = {"sender_id":"u1","text":"hello","mid":"m1"}
    ok1 = await w.enqueue_event(e)
    ok2 = await w.enqueue_event(e)
    print('enqueued_first', ok1)
    print('enqueued_second_should_be_false', ok2)
    print('queue_size', w.get_queue_size())

if __name__ == '__main__':
    asyncio.run(run_test())
