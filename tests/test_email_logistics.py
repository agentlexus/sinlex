"""Тесты email_logistics (HE-0…HE-2)."""

from __future__ import annotations

import json
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

from email.message import Message

from email_logistics.channel import EmailLogisticsChannel
from email_logistics.config import load_channel_config, resolve_active_channel
from email_logistics.imap_receive import (
    _is_balance_only_reply,
    _match_task_id,
    normalize_msg_id,
    strip_quoted_reply,
)
from email_logistics.smtp_send import send_drawing_email
from hybrid_channel.errors import HybridChannelError
from hybrid_channel.markers import build_outbound_body, extract_task_id_from_text


class TestMarkers(unittest.TestCase):
    def test_outbound_body_includes_user_folder(self) -> None:
        body = build_outbound_body("Проект А", "task-uuid-1", user_folder="client_x")
        self.assertIn("task_id:task-uuid-1", body)
        self.assertIn("user_folder:client_x", body)
        self.assertIn("project:Проект А", body)

    def test_extract_task_id(self) -> None:
        tid = extract_task_id_from_text("task_id:550e8400-e29b-41d4-a716-446655440000\nRa 1.6")
        self.assertEqual(tid, "550e8400-e29b-41d4-a716-446655440000")


class TestImapHelpers(unittest.TestCase):
    def test_normalize_msg_id(self) -> None:
        self.assertEqual(
            normalize_msg_id("<abc@sinlex.local>"),
            "abc@sinlex.local",
        )

    def test_strip_quoted_reply(self) -> None:
        text = "Ответ технолога\nRa 1.6\n> цитата\n> ещё"
        self.assertEqual(strip_quoted_reply(text), "Ответ технолога\nRa 1.6")

    def test_match_by_in_reply_to(self) -> None:
        pending = {
            "tid-1": {"message_id": "<out-1@sinlex.local>"},
            "tid-2": {"message_id": "<out-2@sinlex.local>"},
        }
        msg = EmailMessage()
        msg["In-Reply-To"] = "<out-2@sinlex.local>"
        body = "Распознанный текст чертежа"
        self.assertEqual(_match_task_id(pending, msg, body), "tid-2")

    def test_match_by_task_id_in_body(self) -> None:
        tid = "550e8400-e29b-41d4-a716-446655440000"
        pending = {tid: {"message_id": "<x@y>"}}
        msg = Message()
        body = f"task_id:{tid}\nШероховатость Ra 0.8"
        self.assertEqual(_match_task_id(pending, msg, body), tid)

    def test_balance_only_reply_detection(self) -> None:
        self.assertTrue(_is_balance_only_reply("500\n\nSinlex писал:"))
        self.assertFalse(_is_balance_only_reply("Крышка 2 мм\n12 отверстий"))


class TestChannelConfig(unittest.TestCase):
    def test_load_default_json_template(self) -> None:
        path = Path("/opt/sinlex/config/hybrid_channel.json")
        if not path.is_file():
            self.skipTest("hybrid_channel.json missing")
        data = load_channel_config()
        self.assertEqual(data.get("version"), 1)
        self.assertIn(data.get("active_channel"), ("email_logistics", "max_suffler"))


class TestEmailChannel(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "state.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @patch("email_logistics.channel.require_email_settings")
    @patch("email_logistics.channel.send_drawing_email")
    def test_send_registers_pending_then_message_id(
        self, mock_send, _req
    ) -> None:
        mock_send.return_value = ("<mid-test@sinlex.local>", "subject")
        ch = EmailLogisticsChannel(state_path=self.state_path)
        out = ch.send_drawing(
            b"%PDF-1.4",
            "Проект",
            "task-early",
            user_folder="user_a",
        )
        self.assertEqual(out, "task-early")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIn("task-early", state["pending"])
        self.assertEqual(
            state["pending"]["task-early"]["message_id"],
            "<mid-test@sinlex.local>",
        )
        mock_send.assert_called_once()

    @patch("email_logistics.channel.require_email_settings")
    @patch("email_logistics.channel.poll_inbox")
    def test_check_response_polls_when_pending(self, mock_poll, _req) -> None:
        self.state_path.write_text(
            json.dumps(
                {
                    "pending": {
                        "tid-1": {
                            "message_id": "<m@x>",
                            "sent_at": "2026-01-01T00:00:00+00:00",
                        }
                    },
                    "responses": {},
                }
            ),
            encoding="utf-8",
        )

        def fill_response(cfg, state):
            state["responses"]["tid-1"] = "Текст ответа"

        mock_poll.side_effect = fill_response
        ch = EmailLogisticsChannel(state_path=self.state_path)
        self.assertEqual(ch.check_response("tid-1"), "Текст ответа")

    @patch("email_logistics.channel.require_email_settings")
    def test_check_response_no_poll_without_pending(self, _req) -> None:
        ch = EmailLogisticsChannel(state_path=self.state_path)
        self.assertIsNone(ch.check_response("unknown"))


class TestSmtpSend(unittest.TestCase):
    @patch("email_logistics.smtp_send._smtp_connect")
    def test_smtp_send_builds_message(self, connect_mock) -> None:
        server = MagicMock()
        connect_mock.return_value = server
        server.__enter__ = MagicMock(return_value=server)
        server.__exit__ = MagicMock(return_value=False)
        cfg = {
            "to": "tech@example.com",
            "from": "sinlex@example.com",
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "u",
            "smtp_password": "p",
            "smtp_tls": True,
        }
        mid, subj = send_drawing_email(
            cfg,
            pdf_bytes=b"%PDF",
            project_name="Деталь",
            task_id="uuid-1",
            user_folder="folder1",
        )
        self.assertIn("@", mid)
        self.assertIn("Деталь", subj)
        server.send_message.assert_called_once()


class TestGetHybridChannel(unittest.TestCase):
    @patch("email_logistics.resolve_active_channel", return_value="max_suffler")
    def test_factory_max(self, _active) -> None:
        from email_logistics import get_hybrid_channel
        from max_suffler import MaxSufflerBot

        ch = get_hybrid_channel(token="test-token", chat_id=12345)
        self.assertIsInstance(ch, MaxSufflerBot)

    @patch("email_logistics.resolve_active_channel", return_value="email_logistics")
    @patch("email_logistics.channel.require_email_settings")
    def test_factory_email(self, _req, _active) -> None:
        from email_logistics import get_hybrid_channel

        with tempfile.TemporaryDirectory() as td:
            ch = get_hybrid_channel(state_path=Path(td) / "s.json")
        self.assertIsInstance(ch, EmailLogisticsChannel)

    @patch("email_logistics.config.load_channel_config")
    def test_invalid_active_channel(self, mock_load) -> None:
        mock_load.return_value = {
            "version": 1,
            "active_channel": "telegram",
            "channels": {},
        }
        from email_logistics.config import resolve_active_channel

        with self.assertRaises(HybridChannelError):
            resolve_active_channel(force_reload=True)
