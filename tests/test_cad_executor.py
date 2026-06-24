"""Tests for CAD executor (TZ-cad-nonblocking-api CAD-4)."""

import asyncio
import time
import unittest

from api.services.cad_executor import run_cad


class TestCadExecutor(unittest.TestCase):
    def test_event_loop_stays_responsive_during_cad_job(self):
        async def scenario() -> None:
            cad_started = asyncio.Event()

            def slow_cad() -> str:
                cad_started.set()
                time.sleep(1.5)
                return "done"

            cad_task = asyncio.create_task(run_cad(slow_cad))
            await cad_started.wait()

            t0 = time.monotonic()
            ping = await asyncio.wait_for(asyncio.sleep(0), timeout=0.5)
            self.assertIsNone(ping)
            self.assertLess(time.monotonic() - t0, 0.3)

            self.assertEqual(await cad_task, "done")

        asyncio.run(scenario())

    def test_run_cad_timeout(self):
        async def scenario() -> None:
            def slow() -> None:
                time.sleep(2)

            with self.assertRaises(asyncio.TimeoutError):
                await run_cad(slow, timeout=0.05)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
