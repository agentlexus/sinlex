"""Тесты hybrid_analysis и API job (этап HS-2)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from hybrid_analysis import (
    HybridJobError,
    finalize_hybrid_job,
    job_to_public,
    refresh_job_status,
    run_start_background,
    start_hybrid_analysis,
)
from hybrid_analysis import (
    find_latest_hybrid_job,
    purge_hybrid_jobs,
    hybrid_finalize_result_from_job,
    hybrid_jobs_dir,
    hybrid_session_restore_plan,
    load_job,
    save_job,
)


class TestHybridJobStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = "Test_Project"
        self.user_folder = "test_user"
        self.patcher = patch(
            "hybrid_analysis._project_dir",
            return_value=os.path.join(self.tmp.name, self.user_folder, "Test_Project"),
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    def test_start_creates_pending_job(self) -> None:
        out = start_hybrid_analysis(
            b"%PDF-1.4 fake",
            {"project_name": self.project, "step_analysis_version": "v1"},
            self.project,
            self.user_folder,
        )
        self.assertEqual(out["status"], "pending_balance")
        self.assertTrue(out["task_id"])
        job = load_job(self.project, self.user_folder, out["task_id"])
        self.assertEqual(job["status"], "pending_balance")
        self.assertTrue(job.get("deadline_at"))

    def test_cancel_previous_pending(self) -> None:
        out1 = start_hybrid_analysis(b"%PDF-a", {"project_name": self.project}, self.project, self.user_folder)
        out2 = start_hybrid_analysis(b"%PDF-b", {"project_name": self.project}, self.project, self.user_folder)
        job1 = load_job(self.project, self.user_folder, out1["task_id"])
        self.assertEqual(job1["status"], "cancelled")
        job2 = load_job(self.project, self.user_folder, out2["task_id"])
        self.assertEqual(job2["status"], "pending_balance")

    def test_timeout_without_suffler(self) -> None:
        out = start_hybrid_analysis(b"%PDF", {"project_name": self.project}, self.project, self.user_folder)
        job = load_job(self.project, self.user_folder, out["task_id"])
        job["deadline_at"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        save_job(job)
        with patch("hybrid_analysis.get_hybrid_channel") as mock_bot:
            mock_bot.return_value.check_response.return_value = None
            updated = refresh_job_status(self.project, self.user_folder, out["task_id"])
        self.assertEqual(updated["status"], "timeout")
        self.assertIsNone(updated.get("suffler_text"))

    def test_pending_to_ready_mock_channel(self) -> None:
        out = start_hybrid_analysis(b"%PDF", {"project_name": self.project}, self.project, self.user_folder)
        tid = out["task_id"]
        job = load_job(self.project, self.user_folder, tid)
        job["status"] = "pending"
        job["user_email"] = "user@test.com"
        job["flow_tokens_charged"] = 1
        save_job(job)
        mock_bot = MagicMock()
        mock_bot.check_response.return_value = "Ra 1.6\nH7"
        mock_bot.parse_response.return_value = {
            "roughness": ["Ra 1.6"],
            "tolerances": ["H7"],
            "notes": "Ra 1.6\nH7",
        }
        with patch("hybrid_analysis.get_hybrid_channel", return_value=mock_bot):
            updated = refresh_job_status(self.project, self.user_folder, tid)
        self.assertEqual(updated["status"], "ready")
        self.assertIn("Ra 1.6", updated["suffler_text"])

    def test_find_latest_hybrid_job_and_restore_plan(self) -> None:
        out = start_hybrid_analysis(
            b"%PDF",
            {"project_name": self.project},
            self.project,
            self.user_folder,
        )
        tid = out["task_id"]
        job = load_job(self.project, self.user_folder, tid)
        job["pdf_hash"] = "abc123"
        job["status"] = "ready"
        job["finalize_result"] = {
            "status": "ok",
            "analysis": "⚫ Sinlex AI 1.2\n\nГотово.",
        }
        save_job(job)
        found = find_latest_hybrid_job(
            self.project, self.user_folder, pdf_hash="abc123"
        )
        self.assertIsNotNone(found)
        self.assertEqual(found["task_id"], tid)
        fin = hybrid_finalize_result_from_job(found)
        self.assertEqual(fin.get("status"), "ok")
        plan = hybrid_session_restore_plan(found)
        self.assertEqual(plan["ui_status"], "done")
        self.assertIn("Готово", plan["result"]["analysis"])

    def test_purge_hybrid_jobs_removes_restore(self) -> None:
        out = start_hybrid_analysis(
            b"%PDF",
            {"project_name": self.project},
            self.project,
            self.user_folder,
        )
        job = load_job(self.project, self.user_folder, out["task_id"])
        job["pdf_hash"] = "purge_me"
        job["finalize_result"] = {"status": "ok", "analysis": "old"}
        save_job(job)
        n = purge_hybrid_jobs(self.project, self.user_folder, pdf_hash="purge_me")
        self.assertGreaterEqual(n, 1)
        self.assertIsNone(
            find_latest_hybrid_job(self.project, self.user_folder, pdf_hash="purge_me")
        )

    def test_job_to_public_hides_internals(self) -> None:
        pub = job_to_public(
            {
                "task_id": "t1",
                "status": "pending",
                "error_message": "hybrid_channel network fail",
            }
        )
        self.assertNotIn("network fail", json.dumps(pub, ensure_ascii=False))


class TestRunStartBackground(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = "Bg_Project"
        self.user_folder = ""
        self.patcher = patch(
            "hybrid_analysis._project_dir",
            return_value=os.path.join(self.tmp.name, "Bg_Project"),
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    @patch("hybrid_analysis.extract_text_from_pdf")
    @patch("hybrid_analysis.get_hybrid_channel")
    def test_background_fills_auto_and_channel(
        self,
        mock_get_bot,
        mock_extract,
    ) -> None:
        mock_extract.return_value = {"full_text": "ocr", "fields": {}}
        mock_bot = MagicMock()
        mock_bot.send_balance_inquiry.return_value = "tid-1"
        mock_get_bot.return_value = mock_bot

        out = start_hybrid_analysis(
            b"%PDF-bg",
            {"project_name": self.project},
            self.project,
            self.user_folder,
        )
        run_start_background(
            out["task_id"],
            self.project,
            self.user_folder,
            b"%PDF-bg",
            {"project_name": self.project},
        )
        job = load_job(self.project, self.user_folder, out["task_id"])
        self.assertEqual(job["auto_extraction"]["full_text"], "ocr")
        self.assertEqual(job["status"], "pending_balance")
        mock_bot.send_balance_inquiry.assert_called_once()


class TestFinalize(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = "Fin_Project"
        self.pdir = os.path.join(self.tmp.name, "Fin_Project")
        os.makedirs(self.pdir, exist_ok=True)
        self.pdf_path = os.path.join(self.pdir, "Fin_Project.pdf")
        with open(self.pdf_path, "wb") as f:
            f.write(b"%PDF-finalize")
        self.patcher = patch("hybrid_analysis._project_dir", return_value=self.pdir)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    def test_finalize_requires_ready(self) -> None:
        out = start_hybrid_analysis(b"%PDF", {"project_name": self.project}, self.project, "")
        job = load_job(self.project, "", out["task_id"])
        job["status"] = "pending"
        save_job(job)
        mock_bot = MagicMock()
        mock_bot.check_response.return_value = None
        with patch("hybrid_analysis.get_hybrid_channel", return_value=mock_bot):
            with self.assertRaises(HybridJobError) as ctx:
                finalize_hybrid_job(self.project, "", out["task_id"])
        self.assertEqual(ctx.exception.code, "pending")

    @patch("expert_analyzer.deep_analysis")
    def test_finalize_calls_deep_analysis(self, mock_deep) -> None:
        from expert_analyzer import LABEL_SINLEX_V12, MARKER_SINLEX_V12

        mock_deep.return_value = {
            "status": "ok",
            "analysis": f"{MARKER_SINLEX_V12} {LABEL_SINLEX_V12}\n\nгибридный текст",
            "api_used": "perplexity",
            "llm_stack_version": "hybrid_sonar_rp_v1",
            "hybrid_suffler_applied": True,
        }
        out = start_hybrid_analysis(b"%PDF", {"project_name": self.project}, self.project, "")
        job = load_job(self.project, "", out["task_id"])
        job["status"] = "ready"
        job["suffler_text"] = "Ra 0.8"
        job["suffler_parsed"] = {"roughness": [], "tolerances": [], "notes": ""}
        job["pdf_path"] = self.pdf_path
        save_job(job)
        result = finalize_hybrid_job(self.project, "", out["task_id"])
        self.assertEqual(result["status"], "ok")
        mock_deep.assert_called_once()
        _args, kwargs = mock_deep.call_args
        self.assertEqual(kwargs.get("suffler_text"), "Ra 0.8")
        self.assertEqual(kwargs.get("hybrid_task_id"), out["task_id"])
        self.assertEqual(result["api_used"], "perplexity")
        self.assertIn(MARKER_SINLEX_V12, result["analysis"])
        self.assertIn("гибридный текст", result["analysis"])

    @patch("hybrid_analysis.get_hybrid_channel")
    def test_refresh_balance_before_drawing(self, mock_get_bot) -> None:
        """До отправки чертежа опрашивается только ответ на служебное письмо."""
        out = start_hybrid_analysis(b"%PDF", {"project_name": self.project}, self.project, "")
        mock_bot = MagicMock()
        mock_bot.check_balance_response.return_value = None
        mock_get_bot.return_value = mock_bot
        updated = refresh_job_status(self.project, "", out["task_id"])
        self.assertEqual(updated["status"], "pending_balance")
        mock_bot.check_balance_response.assert_called_once_with(out["task_id"])
        mock_bot.check_response.assert_not_called()


if __name__ == "__main__":
    unittest.main()
