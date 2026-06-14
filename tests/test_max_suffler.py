"""Юнит-тесты max_suffler (этап HS-1 TZ-hybrid-deep-analysis)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from max_suffler import (
    MaxSufflerBot,
    MaxSufflerError,
    _assert_ui_safe,
    get_max_suffler_bot,
)


class TestUiMessages(unittest.TestCase):
    def test_default_messages_have_no_forbidden_words(self):
        for code in ("config", "network", "api", "hybrid_channel"):
            err = MaxSufflerError(code, "internal")
            _assert_ui_safe(err.ui_message)

    def test_internal_code_hybrid_channel(self):
        err = MaxSufflerError("network", "internal")
        self.assertEqual(err.internal_code, "hybrid_channel")


class TestConfig(unittest.TestCase):
    def test_missing_token_on_factory(self):
        with patch.dict(os.environ, {"MAX_SUFFLER_TOKEN": ""}, clear=False):
            with patch("max_suffler._SECRETS", {}):
                with self.assertRaises(MaxSufflerError) as ctx:
                    get_max_suffler_bot(token="")
        self.assertEqual(ctx.exception.code, "config")
        _assert_ui_safe(ctx.exception.ui_message)

    @patch.dict(os.environ, {"ENABLE_HYBRID_SUFFLER": "0"}, clear=False)
    def test_missing_token_ok_when_disabled(self):
        bot = MaxSufflerBot(token="test-token", chat_id=42)
        self.assertEqual(bot.token, "test-token")


class TestSendAndCheckMockHttp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp.name, "state.json")
        self.session = MagicMock()
        self.bot = MaxSufflerBot(
            token="tok-test",
            chat_id=9001,
            api_base="https://api.test",
            state_path=self.state_path,
            session=self.session,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _mock_upload_flow(self) -> None:
        upload_meta = MagicMock()
        upload_meta.status_code = 200
        upload_meta.json.return_value = {"url": "https://cdn.test/upload"}

        upload_file = MagicMock()
        upload_file.status_code = 200
        upload_file.json.return_value = {"token": "file-tok-1"}

        send_msg = MagicMock()
        send_msg.status_code = 200
        send_msg.json.return_value = {
            "message": {"body": {"mid": "mid-out-1"}},
        }

        self.session.request.side_effect = [upload_meta, send_msg]

        with patch("max_suffler.requests.post", return_value=upload_file):
            tid = self.bot.send_drawing(b"%PDF-1.4", "Проект А", "task-uuid-1")
        self.assertEqual(tid, "task-uuid-1")
        with open(self.state_path, encoding="utf-8") as f:
            state = json.load(f)
        self.assertIn("task-uuid-1", state["pending"])
        self.assertEqual(state["pending"]["task-uuid-1"]["message_id"], "mid-out-1")

    def test_send_drawing_returns_task_id(self) -> None:
        self._mock_upload_flow()

    def test_check_response_none_until_reply(self) -> None:
        self._mock_upload_flow()
        empty_updates = MagicMock()
        empty_updates.status_code = 200
        empty_updates.json.return_value = {"marker": 1, "updates": []}
        self.session.request.side_effect = None
        self.session.request.return_value = empty_updates
        self.assertIsNone(self.bot.check_response("task-uuid-1"))

    def test_check_response_text_on_reply(self) -> None:
        self._mock_upload_flow()
        updates_resp = MagicMock()
        updates_resp.status_code = 200
        updates_resp.json.return_value = {
            "marker": 10,
            "updates": [
                {
                    "update_type": "message_created",
                    "message": {
                        "recipient": {"chat_id": 9001},
                        "link": {"message": {"mid": "mid-out-1"}},
                        "body": {"text": "Ra 0.8\nH7\nШпоночный паз"},
                    },
                }
            ],
        }
        self.session.request.side_effect = None
        self.session.request.return_value = updates_resp
        text = self.bot.check_response("task-uuid-1")
        self.assertIn("Ra 0.8", text or "")
        self.assertEqual(self.bot.check_response("task-uuid-1"), text)

    def test_check_response_plain_text_newest_pending(self) -> None:
        """Ответ без reply (как в MAX dialog) — к последнему pending в чате."""
        state = {
            "marker": None,
            "pending": {
                "old-task": {
                    "message_id": "mid-old",
                    "chat_id": 9001,
                    "sent_at": "2026-05-22T10:00:00+00:00",
                },
                "new-task": {
                    "message_id": "mid-new",
                    "chat_id": 9001,
                    "sent_at": "2026-05-22T19:00:00+00:00",
                },
            },
            "responses": {},
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        updates_resp = MagicMock()
        updates_resp.status_code = 200
        updates_resp.json.return_value = {
            "marker": 11,
            "updates": [
                {
                    "update_type": "message_created",
                    "message": {
                        "recipient": {"chat_id": 9001},
                        "body": {"text": "Маховик. Ra 1.6"},
                        "sender": {"user_id": 1, "is_bot": False},
                    },
                }
            ],
        }
        self.session.request.return_value = updates_resp
        text = self.bot.check_response("new-task")
        self.assertEqual(text, "Маховик. Ra 1.6")
        with open(self.state_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIn("new-task", saved.get("responses", {}))
        self.assertNotIn("new-task", saved.get("pending", {}))

    def test_check_response_cached_without_http(self) -> None:
        state = {
            "marker": None,
            "pending": {},
            "responses": {"cached-id": "готовый текст"},
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        self.assertEqual(self.bot.check_response("cached-id"), "готовый текст")
        self.session.request.assert_not_called()

    def test_check_response_no_poll_without_pending(self) -> None:
        """LP-4: опрос /updates только после регистрации task в pending."""
        self.assertIsNone(self.bot.check_response("unknown-task"))
        self.session.request.assert_not_called()

    def test_send_registers_pending_before_upload(self) -> None:
        """LP-4: pending в state до загрузки PDF (гонка с refresh_job_status)."""
        pending_before_upload: list[bool] = []

        def capture_pending(*_args, **_kwargs):
            with open(self.state_path, encoding="utf-8") as f:
                st = json.load(f)
            pending_before_upload.append("task-early" in (st.get("pending") or {}))
            return "file-tok-1"

        upload_meta = MagicMock()
        upload_meta.status_code = 200
        upload_meta.json.return_value = {"url": "https://cdn.test/upload"}
        upload_file = MagicMock()
        upload_file.status_code = 200
        upload_file.json.return_value = {"token": "file-tok-1"}
        send_msg = MagicMock()
        send_msg.status_code = 200
        send_msg.json.return_value = {"message": {"body": {"mid": "mid-out-1"}}}
        self.session.request.side_effect = [upload_meta, send_msg]

        with patch("max_suffler.requests.post", return_value=upload_file):
            with patch.object(self.bot, "_upload_pdf_token", side_effect=capture_pending):
                self.bot.send_drawing(b"%PDF", "Проект", "task-early")
        self.assertTrue(pending_before_upload)
        self.assertTrue(pending_before_upload[0])


class TestParseResponse(unittest.TestCase):
    def test_parse_ra_and_h(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bot = MaxSufflerBot(
                token="x",
                chat_id=1,
                state_path=os.path.join(td, "s.json"),
            )
            parsed = bot.parse_response("Ra 0,8\nОтверстие H7 ±0.02")
        self.assertTrue(any("0.8" in r for r in parsed["roughness"]))
        self.assertTrue(any("H7" in t for t in parsed["tolerances"]))


class TestGetMaxSufflerBot(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "ENABLE_HYBRID_SUFFLER": "1",
            "MAX_SUFFLER_TOKEN": "tok",
            "MAX_SUFFLER_CHAT_ID": "42",
        },
        clear=False,
    )
    def test_factory_ok(self) -> None:
        bot = get_max_suffler_bot()
        self.assertEqual(bot.token, "tok")
        self.assertEqual(bot.chat_id, 42)

    @patch.dict(
        os.environ,
        {"ENABLE_HYBRID_SUFFLER": "1", "MAX_SUFFLER_TOKEN": "tok"},
        clear=False,
    )
    def test_factory_requires_chat_when_enabled(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "MAX_SUFFLER_CHAT_ID"}
        with patch.dict(os.environ, env, clear=True):
            with patch("max_suffler._SECRETS", {}):
                with self.assertRaises(MaxSufflerError):
                    get_max_suffler_bot()


if __name__ == "__main__":
    unittest.main()
