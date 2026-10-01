"""Event-loop block detector (ported idea from Geny loop_watchdog): logs a stack when the loop stalls > 2s."""
from __future__ import annotations

import asyncio
import faulthandler
import signal
import sys
import threading
import time

from blackmoa.core.logging import get_logger

log = get_logger("blackmoa.watchdog")
_last_tick = time.monotonic()
_max_lag = 0.0


def loop_lag() -> float:
    return max(0.0, time.monotonic() - _last_tick - 1.0)


def install_loop_watchdog(threshold_s: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    with __import__("contextlib").suppress(Exception):
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)

    async def _tick():
        global _last_tick
        while True:
            _last_tick = time.monotonic()
            await asyncio.sleep(1.0)

    def _watch():
        global _max_lag
        stalled = False
        while True:
            time.sleep(1.0)
            lag = time.monotonic() - _last_tick
            if lag > threshold_s and not stalled:
                stalled = True
                log.warning("event loop stalled", lag_s=round(lag, 1))
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            elif lag <= threshold_s:
                stalled = False
            _max_lag = max(_max_lag, lag)

    loop.create_task(_tick(), name="watchdog-tick")
    threading.Thread(target=_watch, name="loop-watchdog", daemon=True).start()
