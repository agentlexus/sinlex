"""Тесты пополнения токенов «Поток» (TZ-flow-tokens-payment, этап 1)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import payment as pay


class TestFlowTokensPayment(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._user_dir = os.path.join(self._tmpdir.name, "user_payments")
        os.makedirs(self._user_dir, exist_ok=True)
        self._payments_file = os.path.join(self._tmpdir.name, "payments.json")
        with open(self._payments_file, "w", encoding="utf-8") as f:
            json.dump({"payments": {}}, f)
        self._accounts = {
            "user@test.com": {"folder": "test_co", "company_name": "Test"},
        }
        self._patches = [
            mock.patch.object(pay, "USER_PAYMENTS_DIR", self._user_dir),
            mock.patch.object(pay, "PAYMENTS_FILE", self._payments_file),
            mock.patch.object(pay, "load_accounts", return_value=self._accounts),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_balance_zero_for_new_user(self):
        self.assertEqual(pay.get_flow_token_balance("user@test.com"), 0)

    def test_credit_increases_balance(self):
        r = pay.credit_flow_tokens("user@test.com", 1000, "pay-001")
        self.assertEqual(r["credited"], 1000)
        self.assertEqual(r["balance"], 1000)
        self.assertEqual(pay.get_flow_token_balance("user@test.com"), 1000)

    def test_credit_idempotent_by_payment_id(self):
        pay.credit_flow_tokens("user@test.com", 1000, "pay-dup")
        r2 = pay.credit_flow_tokens("user@test.com", 1000, "pay-dup")
        self.assertTrue(r2.get("already_credited"))
        self.assertEqual(r2["balance"], 1000)
        self.assertEqual(pay.get_flow_token_balance("user@test.com"), 1000)
        path = pay._user_payment_file("user@test.com")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        deposits = [t for t in data.get("transactions", []) if t.get("type") == "deposit"]
        self.assertEqual(len(deposits), 1)

    def test_register_payment_flow_purpose(self):
        rec = pay.register_payment(
            "p-flow-1",
            "user@test.com",
            amount=1500.0,
            purpose=pay.PURPOSE_FLOW_TOKENS,
            amount_tokens=1500,
        )
        self.assertEqual(rec["purpose"], pay.PURPOSE_FLOW_TOKENS)
        self.assertEqual(rec["amount_tokens"], 1500)

    def test_flow_rub_to_tokens(self):
        self.assertEqual(pay.flow_rub_to_tokens(1000), 100)
        self.assertEqual(pay.flow_rub_to_tokens(1500), 150)
        self.assertEqual(pay.flow_rub_to_tokens(9), 0)
        self.assertEqual(pay.flow_tokens_rub_equiv(10), 100)

    def test_flow_topup_min_amount(self):
        with self.assertRaises(ValueError):
            pay.create_flow_topup_payment("user@test.com", 500, "http://localhost/")

    def test_is_activation_result_flow(self):
        self.assertTrue(
            pay.is_activation_result({"purpose": pay.PURPOSE_FLOW_TOKENS, "balance": 10})
        )


if __name__ == "__main__":
    unittest.main()


class TestFlowDebitAndPending(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._user_dir = os.path.join(self._tmpdir.name, "user_payments")
        self._pending_dir = os.path.join(self._tmpdir.name, "flow_pending")
        os.makedirs(self._user_dir)
        os.makedirs(self._pending_dir)
        self._payments_file = os.path.join(self._tmpdir.name, "payments.json")
        with open(self._payments_file, "w", encoding="utf-8") as f:
            json.dump({"payments": {}}, f)
        self._accounts = {"user@test.com": {"folder": "test_co"}}
        self._patches = [
            mock.patch.object(pay, "USER_PAYMENTS_DIR", self._user_dir),
            mock.patch.object(pay, "FLOW_PENDING_DIR", self._pending_dir),
            mock.patch.object(pay, "PAYMENTS_FILE", self._payments_file),
            mock.patch.object(pay, "load_accounts", return_value=self._accounts),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_debit_and_idempotent(self):
        pay.credit_flow_tokens("user@test.com", 100, "dep-1", source="test")
        d1 = pay.debit_flow_tokens("user@test.com", 30, task_id="task-a")
        self.assertTrue(d1.get("ok"))
        self.assertEqual(d1["balance"], 70)
        d2 = pay.debit_flow_tokens("user@test.com", 30, task_id="task-a")
        self.assertTrue(d2.get("already_debited"))

    def test_pending_enqueue_and_release_fifo(self):
        pay.credit_flow_tokens("user@test.com", 50, "dep-2", source="test")
        payload = {"status": "ok", "analysis": "text"}
        pay.enqueue_flow_pending(
            "user@test.com",
            task_id="t1",
            project_name="P1",
            project_slug="P1",
            tokens_required=40,
            result_payload=payload,
        )
        pay.enqueue_flow_pending(
            "user@test.com",
            task_id="t2",
            project_name="P2",
            project_slug="P2",
            tokens_required=40,
            result_payload=payload,
        )
        released = pay.release_flow_pending_queue("user@test.com")
        self.assertEqual(len(released), 1)
        self.assertEqual(released[0]["task_id"], "t1")
        self.assertEqual(pay.get_flow_token_balance("user@test.com"), 10)
        pending = pay._load_flow_pending("user@test.com")
        self.assertEqual(len(pending["queue"]), 1)
        self.assertEqual(pending["queue"][0]["task_id"], "t2")
