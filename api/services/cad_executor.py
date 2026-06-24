"""Thread-pool executor for CPU-bound STEP/CAD work (non-blocking event loop)."""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Callable, TypeVar

from page_modules.upload_limits import STEP_ANALYZE_TIMEOUT_SEC, STEP_GLB_TIMEOUT_SEC

_CAD_MAX_WORKERS = max(1, int(os.environ.get("SINLEX_CAD_MAX_WORKERS", "1")))
_CAD_POOL = ThreadPoolExecutor(max_workers=_CAD_MAX_WORKERS, thread_name_prefix="sinlex-cad")
_CAD_SEM = asyncio.Semaphore(1)

T = TypeVar("T")

CAD_TIMEOUT_ANALYZE = STEP_ANALYZE_TIMEOUT_SEC
CAD_TIMEOUT_GLB = STEP_GLB_TIMEOUT_SEC


async def run_cad(
    fn: Callable[..., T],
    *args,
    timeout: float | None = None,
    **kwargs,
) -> T:
    """Run blocking CAD/OCC code in a worker thread; at most one job at a time."""
    async with _CAD_SEM:
        loop = asyncio.get_running_loop()
        if kwargs:
            call: Callable[[], T] = partial(fn, *args, **kwargs)
            fut = loop.run_in_executor(_CAD_POOL, call)
        else:
            fut = loop.run_in_executor(_CAD_POOL, fn, *args)
        if timeout is not None:
            return await asyncio.wait_for(fut, timeout=timeout)
        return await fut
