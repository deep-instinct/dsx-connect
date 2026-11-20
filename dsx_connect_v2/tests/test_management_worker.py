import asyncio

from dsx_connect_v2.workers import management_worker as worker
from dsx_connect_v2.jobs.daily_aggregates import ManagementSettings


def test_aggregation_failure_does_not_stop_discovery_or_heartbeat(monkeypatch):
    counters = dict(discovery=0,aggregate=0,errors=0,heartbeats=0)
    class Store:
        def settings(self): return {'settings':ManagementSettings().model_dump()}
        def backfill_page(self): pass
        def backfill_complete(self): return True
        def process_one(self):
            counters['aggregate'] += 1
            if counters['aggregate']==1: raise RuntimeError('transient aggregate failure')
            return False
        def record_error(self): counters['errors'] += 1
        def heartbeat(self, _): counters['heartbeats'] += 1
    async def discover(*args,stop):
        while not stop.is_set():
            counters['discovery'] += 1
            await asyncio.sleep(.005)
    monkeypatch.setattr(worker.discovery_worker,'serve',discover)
    monkeypatch.setattr(worker,'POLL_SECONDS',.01)
    async def scenario():
        stop=asyncio.Event()
        task=asyncio.create_task(worker.serve(None,None,Store(),stop))
        try:
            async with asyncio.timeout(2):
                while counters['aggregate']<3 or counters['heartbeats']<2:
                    await asyncio.sleep(.01)
        finally:
            stop.set()
            await task
    asyncio.run(scenario())
    assert counters['errors']==1 and counters['discovery']>1
