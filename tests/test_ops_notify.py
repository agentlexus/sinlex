"""Tests for ops Max notifications."""

import unittest
from unittest.mock import MagicMock, patch

from ops_notify import notify


class TestOpsNotify(unittest.TestCase):
    def setUp(self) -> None:
        notify._SECRETS = None

    @patch.dict("os.environ", {"ENABLE_OPS_NOTIFY": "0"}, clear=False)
    def test_disabled_skips_send(self) -> None:
        with patch("ops_notify.notify.requests.post") as mock_post:
            notify.notify_user_registered("a@b.c")
            mock_post.assert_not_called()

    @patch.dict(
        "os.environ",
        {
            "ENABLE_OPS_NOTIFY": "1",
            "MAX_SUFFLER_TOKEN": "tok",
            "MAX_SUFFLER_CHAT_ID": "9001",
        },
        clear=False,
    )
    def test_user_registered_message(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("ops_notify.notify.requests.post", return_value=mock_resp) as mock_post:
            notify._send_message("Зарегистрирован новый пользователь u@x.ru")
            mock_post.assert_called_once()
            _args, kwargs = mock_post.call_args
            self.assertTrue(_args[0].endswith("/messages"))
            self.assertEqual(kwargs["headers"]["Authorization"], "tok")
            self.assertEqual(kwargs["params"]["chat_id"], "9001")
            self.assertEqual(kwargs["json"]["text"], "Зарегистрирован новый пользователь u@x.ru")

    @patch.dict(
        "os.environ",
        {
            "ENABLE_OPS_NOTIFY": "1",
            "MAX_SUFFLER_TOKEN": "tok",
            "MAX_SUFFLER_CHAT_ID": "9001",
        },
        clear=False,
    )
    def test_flow_activated_fires_background(self) -> None:
        with patch("ops_notify.notify.threading.Thread") as mock_thread:
            notify.notify_flow_activated("flow@x.ru")
            mock_thread.assert_called_once()
            target = mock_thread.call_args.kwargs["target"]
            args = mock_thread.call_args.kwargs["args"]
            self.assertEqual(target, notify._send_message)
            self.assertEqual(args, ("Активация потока пользователем flow@x.ru",))
