#!/usr/bin/env python3
"""Smoke: ops Max notifications (config + unit tests + live send)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops_notify import notify  # noqa: E402

TAG = "smoke-test@sinlex.tech"


def check_config() -> dict:
    notify._SECRETS = None
    return {
        "enabled": notify._enabled(),
        "token_set": bool(notify._env("MAX_SUFFLER_TOKEN")),
        "chat_set": bool(notify._chat_id()),
    }


def run_unit_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_ops_notify", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()}


def live_send(text: str) -> dict:
    notify._SECRETS = None
    if not notify._enabled():
        return {"ok": False, "skipped": True, "error": "ENABLE_OPS_NOTIFY is off"}
    if not notify._env("MAX_SUFFLER_TOKEN") or not notify._chat_id():
        return {"ok": False, "error": "missing MAX_SUFFLER_TOKEN or MAX_SUFFLER_CHAT_ID"}
    try:
        notify._send_message(text)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    report = {
        "smoke": "ops_notify_max",
        "config": check_config(),
        "unit_tests": run_unit_tests(),
        "live": [],
    }
    cases = [
        ("registration", f"Зарегистрирован новый пользователь {TAG}"),
        ("flow", f"Активация потока пользователем {TAG}"),
    ]
    for name, text in cases:
        report["live"].append({"case": name, "text": text, **live_send(text)})

    cfg_ok = report["config"]["enabled"] and report["config"]["token_set"] and report["config"]["chat_set"]
    live_ok = all(x.get("ok") for x in report["live"])
    tests_ok = report["unit_tests"]["ok"]
    report["passed"] = cfg_ok and tests_ok and live_ok
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
