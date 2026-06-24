"""Tests for CAD router timeouts (TZ-cad-nonblocking-api CAD-5)."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from fastapi import HTTPException

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TestCadRouter(unittest.TestCase):
    @patch("api.routers.cad.get_user_folder", return_value="test_user")
    @patch("api.routers.cad.run_cad", new_callable=AsyncMock)
    def test_analyze_step_timeout_returns_504(self, mock_run_cad, _mock_folder):
        mock_run_cad.side_effect = asyncio.TimeoutError()
        file = MagicMock()
        file.read = AsyncMock(return_value=b"ISO-10303-21;")

        async def run():
            from api.routers.cad import analyze_step_endpoint

            with self.assertRaises(HTTPException) as ctx:
                await analyze_step_endpoint(file=file, x_user_email="u@test.com", casting=False)
            self.assertEqual(ctx.exception.status_code, 504)
            self.assertIn("Превышено время", ctx.exception.detail)

        asyncio.run(run())

    @patch("api.routers.cad.get_user_folder", return_value="test_user")
    @patch("api.routers.cad.run_cad", new_callable=AsyncMock)
    def test_step_to_glb_timeout_returns_504(self, mock_run_cad, _mock_folder):
        mock_run_cad.side_effect = asyncio.TimeoutError()
        file = MagicMock()
        file.read = AsyncMock(return_value=b"ISO-10303-21;")

        async def run():
            from api.routers.cad import step_to_glb

            with self.assertRaises(HTTPException) as ctx:
                await step_to_glb(file=file, x_user_email="u@test.com")
            self.assertEqual(ctx.exception.status_code, 504)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
