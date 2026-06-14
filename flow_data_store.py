"""Персистентное хранение данных «Поток» в flow_data.md рядом с чертежом."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flow_drawing_io import flow_data_md_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_data(drawing_file: str, drawing_hash: str = "") -> Dict[str, Any]:
    return {
        "drawing_file": drawing_file,
        "drawing_hash": drawing_hash,
        "updated_at": _utc_now(),
        "channel_responses": [],
        "chat": [],
        "report": None,
        "job": {},
    }


def load_flow_data(drawing_path: str) -> Optional[Dict[str, Any]]:
    path = flow_data_md_path(drawing_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None
    meta_match = re.search(
        r"```json\s*flow-meta\s*\n(.*?)\n```",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    if not meta_match:
        return None
    try:
        return json.loads(meta_match.group(1))
    except json.JSONDecodeError:
        return None


def save_flow_data(drawing_path: str, data: Dict[str, Any]) -> str:
    path = flow_data_md_path(drawing_path)
    data = dict(data)
    data["updated_at"] = _utc_now()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    report = data.get("report") or {}
    analysis = report.get("analysis") or report.get("finalize") or {}
    norm = report.get("norm_calc") or {}

    lines = [
        f"# Поток — {data.get('drawing_file', os.path.basename(drawing_path))}",
        "",
        f"_Обновлено: {data['updated_at']}_",
        "",
    ]

    ch = data.get("channel_responses") or []
    if ch:
        lines.append("## Ответы канала")
        lines.append("")
        for i, item in enumerate(ch, 1):
            lines.append(f"### Ответ {i}")
            if item.get("task_id"):
                lines.append(f"- task_id: `{item['task_id']}`")
            if item.get("at"):
                lines.append(f"- время: {item['at']}")
            lines.append("")
            lines.append(item.get("text") or "_(пусто)_")
            lines.append("")

    chat = data.get("chat") or []
    if chat:
        lines.append("## Диалог")
        lines.append("")
        for i, turn in enumerate(chat, 1):
            lines.append(f"### Вопрос {i}")
            lines.append("")
            lines.append(turn.get("question") or "")
            lines.append("")
            lines.append(f"### Ответ {i}")
            lines.append("")
            lines.append(turn.get("answer") or "_(ожидание)_")
            lines.append("")

    if analysis:
        lines.append("## Итоговый отчёт")
        lines.append("")
        if isinstance(analysis, dict):
            lines.append(analysis.get("report_markdown") or analysis.get("summary") or "")
        else:
            lines.append(str(analysis))
        lines.append("")

    if norm:
        lines.append("## Нормочасы")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(norm, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    lines.append("```json flow-meta")
    lines.append(json.dumps(data, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def init_flow_data(drawing_path: str, drawing_file: str, drawing_hash: str) -> Dict[str, Any]:
    data = _default_data(drawing_file, drawing_hash)
    save_flow_data(drawing_path, data)
    return data


def append_channel_response(
    drawing_path: str,
    text: str,
    *,
    task_id: str = "",
) -> Dict[str, Any]:
    data = load_flow_data(drawing_path) or _default_data(
        os.path.basename(drawing_path), ""
    )
    data.setdefault("channel_responses", []).append(
        {"at": _utc_now(), "task_id": task_id, "text": text}
    )
    save_flow_data(drawing_path, data)
    return data


def append_chat_turn(
    drawing_path: str,
    question: str,
    answer: str = "",
    *,
    chat_id: str = "",
) -> Dict[str, Any]:
    data = load_flow_data(drawing_path) or _default_data(
        os.path.basename(drawing_path), ""
    )
    chat: List[Dict[str, Any]] = data.setdefault("chat", [])
    if chat and not chat[-1].get("answer") and chat[-1].get("question") == question:
        chat[-1]["answer"] = answer
        if chat_id:
            chat[-1]["chat_id"] = chat_id
    else:
        chat.append(
            {
                "chat_id": chat_id,
                "at": _utc_now(),
                "question": question,
                "answer": answer,
            }
        )
    save_flow_data(drawing_path, data)
    return data


def set_report(
    drawing_path: str,
    *,
    analysis: Any = None,
    norm_calc: Any = None,
    structured: Any = None,
    finalize: Any = None,
    job: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = load_flow_data(drawing_path) or _default_data(
        os.path.basename(drawing_path), ""
    )
    report = data.get("report")
    if not isinstance(report, dict):
        report = {}
        data["report"] = report
    if analysis is not None:
        report["analysis"] = analysis
    if norm_calc is not None:
        report["norm_calc"] = norm_calc
    if structured is not None:
        report["structured"] = structured
    if finalize is not None:
        report["finalize"] = finalize
    if job:
        data["job"] = {**data.get("job", {}), **job}
    save_flow_data(drawing_path, data)
    return data




def find_flow_data_by_hash(project_dir: str, drawing_hash: str) -> Optional[tuple[str, Dict[str, Any]]]:
    """Найти сохранённый анализ по хэшу файла (если чертёж переименовали)."""
    h = (drawing_hash or "").strip()
    if not h or not project_dir or not os.path.isdir(project_dir):
        return None
    for fname in os.listdir(project_dir):
        if not fname.endswith(".flow_data.md"):
            continue
        stem = fname[: -len(".flow_data.md")]
        drawing_path = ""
        for ext in (".pdf", ".png", ".jpg", ".jpeg"):
            candidate = os.path.join(project_dir, stem + ext)
            if os.path.isfile(candidate):
                drawing_path = candidate
                break
        if not drawing_path:
            continue
        data = load_flow_data(drawing_path)
        if not data:
            continue
        stored = (data.get("drawing_hash") or "").strip()
        job_h = ((data.get("job") or {}).get("pdf_hash") or "").strip()
        if stored == h or job_h == h:
            return drawing_path, data
    return None

def delete_flow_data(drawing_path: str) -> None:
    path = flow_data_md_path(drawing_path)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def result_from_flow_data(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Восстановление UI result из flow_data."""
    report = data.get("report") or {}
    analysis = report.get("analysis") or report.get("finalize")
    if not analysis and not (data.get("channel_responses")):
        return None
    norm = report.get("norm_calc") or {}
    if isinstance(analysis, dict):
        md = analysis.get("report_markdown") or analysis.get("summary") or ""
    else:
        md = str(analysis or "")
    return {
        "status": "ok",
        "analysis": analysis,
        "norm_calc": norm,
        "structured": report.get("structured"),
        "report_markdown": md,
        "from_saved": True,
        "flow_data": data,
    }
