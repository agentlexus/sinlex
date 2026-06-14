"""
Нормировка по 2D-чертежу (режим «Поток» на отдельной странице).

Цепочка:
1. Канал «Поток» — сведения по чертежу (текст + OCR).
2. Структурирование ответа + параметры заготовки/станка/партии.
3. Экспресс-расчёт по методичке технолога (расширяемые коэффициенты).
4. LLM-отчёт технолога (отдельный промпт, без опоры на STEP/3D).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

LOG = logging.getLogger("flow_norm_hours")

FLOW_NORM_PROJECT = "__flow_norm__"

# Коэффициент на вспомогательное время (упрощённая методичка, §4)
EQUIPMENT_K_VSP: Dict[str, float] = {
    "universal_lathe": 1.55,
    "universal_mill": 1.55,
    "cnc_lathe": 1.25,
    "cnc_mill": 1.25,
    "complex": 1.9,
}

EQUIPMENT_LABELS: Dict[str, str] = {
    "universal_lathe": "Универсальный токарный",
    "universal_mill": "Универсальный фрезерный",
    "cnc_lathe": "Токарный с ЧПУ",
    "cnc_mill": "Фрезерный с ЧПУ",
    "complex": "Сложная корпусная (много отверстий)",
}

_RE_DIM_MM = re.compile(
    r"(?:Ø|D|диам\.?|диаметр)\s*[:=]?\s*(\d+[.,]?\d*)",
    re.IGNORECASE,
)
_RE_LEN_MM = re.compile(
    r"(?:длина|L)\s*[:=]?\s*(\d+[.,]?\d*)",
    re.IGNORECASE,
)


def merge_structured(
    suffler_text: str,
    suffler_parsed: Optional[dict],
    auto_extraction: Optional[dict],
) -> Dict[str, Any]:
    """Сводка сведений по чертежу для расчёта."""
    parsed = suffler_parsed if isinstance(suffler_parsed, dict) else {}
    notes = (parsed.get("notes") or suffler_text or "").strip()
    fields = {}
    if isinstance(auto_extraction, dict):
        fields = dict(auto_extraction.get("fields") or {})
    return {
        "notes": notes,
        "roughness": list(parsed.get("roughness") or []),
        "tolerances": list(parsed.get("tolerances") or []),
        "ocr_fields": fields,
        "material": (fields.get("material") or fields.get("Материал") or "").strip(),
    }


def _infer_dimensions_mm(notes: str, ocr_fields: dict) -> tuple[float, float]:
    """Грубая оценка D и L из текста (мм)."""
    text = notes + "\n" + json.dumps(ocr_fields, ensure_ascii=False)
    d_vals = [float(m.group(1).replace(",", ".")) for m in _RE_DIM_MM.finditer(text)]
    l_vals = [float(m.group(1).replace(",", ".")) for m in _RE_LEN_MM.finditer(text)]
    if not l_vals:
        nums = [float(x) for x in re.findall(r"\b(\d{2,4})\b", text) if 20 <= float(x) <= 2000]
        if len(nums) >= 2:
            l_vals = [max(nums)]
        elif nums:
            l_vals = [nums[0] * 1.5]
    diameter = max(d_vals) if d_vals else 40.0
    length = max(l_vals) if l_vals else diameter * 2.0
    return diameter, length


def _finishing_factor(roughness: list) -> float:
    """Доп. время на чистовые проходы по Ra."""
    extra = 1.0
    for r in roughness:
        m = re.search(r"(\d+[.,]?\d*)", str(r))
        if not m:
            continue
        ra = float(m.group(1).replace(",", "."))
        if ra <= 0.8:
            extra = max(extra, 1.45)
        elif ra <= 1.6:
            extra = max(extra, 1.25)
        elif ra <= 3.2:
            extra = max(extra, 1.1)
    return extra


def _holes_factor(notes: str, tolerances: list) -> float:
    n_h = len(re.findall(r"\bH[6-9]\b", notes, re.I)) + len(tolerances)
    n_deep = len(re.findall(r"глубин|сквозн|расточ", notes, re.I))
    extra = 1.0 + min(0.5, n_h * 0.04) + min(0.3, n_deep * 0.08)
    return extra


def compute_norm_hours(
    structured: Dict[str, Any],
    norm_inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Экспресс-нормировка по методичке (2D, без 3D).
    Возвращает разбивку минут — базу для отчёта LLM.
    """
    equipment = (norm_inputs.get("equipment_type") or "cnc_lathe").strip()
    k_vsp = EQUIPMENT_K_VSP.get(equipment, 1.4)
    batch = max(1, int(norm_inputs.get("batch_size") or 1))

    d_in = norm_inputs.get("blank_diameter_mm")
    l_in = norm_inputs.get("blank_length_mm")
    notes = structured.get("notes") or ""
    ocr = structured.get("ocr_fields") or {}
    if d_in and l_in:
        diameter = float(d_in)
        length = float(l_in)
    else:
        diameter, length = _infer_dimensions_mm(notes, ocr)

    # Упрощённое машинное время токарного прохода: T_o ≈ L / (n*f), n≈800/D, f≈0.2
    n = max(80.0, 1000.0 * 120.0 / (3.14159 * max(diameter, 5.0)))
    f = 0.18 if "cnc" in equipment else 0.15
    passes = max(1, int(norm_inputs.get("rough_passes") or 2))
    t_o = (length + 4.0) * passes / (n * f)

    t_o *= _finishing_factor(structured.get("roughness") or [])
    t_o *= _holes_factor(notes, structured.get("tolerances") or [])

    t_piece = t_o * k_vsp
    t_org = 0.5
    t_pl = 0.3
    if equipment == "complex":
        t_org = 1.2
        t_pl = 0.8

    # Тпз: универсальные 20–40 мин, ЧПУ 60–120 (§6)
    t_pz = 30.0 if "universal" in equipment else 90.0
    t_setup_per_piece = t_pz / batch

    t_shrink = (
        norm_inputs.get("part_length_mm"),
        norm_inputs.get("part_diameter_mm"),
    )
    if t_shrink[0] and t_shrink[1]:
        # корректировка если заданы размеры детали
        pd, pl = float(t_shrink[1]), float(t_shrink[0])
        scale = min(2.0, max(0.5, (pl + pd) / max(length + diameter, 1.0)))
        t_piece *= scale

    t_total = t_piece + t_org + t_pl + t_setup_per_piece

    return {
        "equipment_type": equipment,
        "equipment_label": EQUIPMENT_LABELS.get(equipment, equipment),
        "k_vsp": k_vsp,
        "batch_size": batch,
        "assumed_diameter_mm": round(diameter, 1),
        "assumed_length_mm": round(length, 1),
        "machine_time_min": round(t_o, 2),
        "piece_time_min": round(t_piece, 2),
        "org_min": t_org,
        "pl_min": t_pl,
        "setup_per_piece_min": round(t_setup_per_piece, 2),
        "total_piece_min": round(t_total, 2),
        "total_batch_min": round(t_total * batch, 2),
        "formula_note": "Tшт ≈ Tо×Kвсп + Торг + Тпл + Тпз/n; Tо — оценка по L, D, Ra, отверстиям (2D).",
    }


_STYLE_RULES = """
СТИЛЬ И ОГРАНИЧЕНИЯ (обязательно):
- Ты — эксперт-технолог. Даёшь готовое заключение по чертежу от первого лица («определено», «обнаружено», «рекомендуется»).
- Не ссылайся на внешние источники, описания, указания, пересказ чужих слов.
- Запрещённые формулировки (и близкие): «как было указано», «по имеющимся данным», «в исходных данных»,
  «требуется уточнение», «некорректно/неоднозначно», «по данным распознавания», «согласно описанию»,
  «кем-то указано», «в описании сказано», «суфлёр», «OCR», «email», «ИИ», «нейросеть».
- Не используй «возможно», «вероятно», «необходимо уточнить» в оговорочном смысле.
- Если параметр не удалось установить — пиши «Данные не распознаны» или «Рекомендуется проверить: …»,
  без намёка, что кто-то что-то не указал.
- Размеры, допуски, Ra, отверстия — как факты, которые ты сам установил по чертежу.
"""


def build_technologist_norm_prompt(
    structured: Dict[str, Any],
    norm_inputs: Dict[str, Any],
    calc: Dict[str, Any],
) -> str:
    material = (norm_inputs.get("material") or structured.get("material") or "").strip()
    blank = norm_inputs.get("blank_description") or ""
    notes = (structured.get("notes") or "").strip() or "—"
    roughness = structured.get("roughness") or []
    tolerances = structured.get("tolerances") or []
    ocr_fields = structured.get("ocr_fields") or {}

    return f"""Ты — эксперт-технолог. Выполни **основной** анализ детали **только по 2D-чертежу** (3D-модели нет).
Ты не пересказываешь чужие указания — ты формируешь самостоятельное заключение системы.
{_STYLE_RULES}

АНАЛИЗ ЧЕРТЕЖА (приоритетные сведения):
{notes[:12000]}

ДОПОЛНИТЕЛЬНЫЕ СВЕДЕНИЯ С ЧЕРТЕЖА:
{json.dumps(ocr_fields, ensure_ascii=False, indent=2)}

Шероховатость: {json.dumps(roughness, ensure_ascii=False)}
Допуски: {json.dumps(tolerances, ensure_ascii=False)}

ПАРАМЕТРЫ НОРМИРОВКИ:
- Материал заготовки: {material or "—"}
- Описание заготовки: {blank or "—"}
- Тип оборудования: {calc.get("equipment_label")}
- Партия, шт: {norm_inputs.get("batch_size", 1)}
- Диаметр заготовки, мм: {norm_inputs.get("blank_diameter_mm") or calc.get("assumed_diameter_mm")}
- Длина заготовки, мм: {norm_inputs.get("blank_length_mm") or calc.get("assumed_length_mm")}

ЭКСПРЕСС-РАСЧЁТ (ориентир; при необходимости скорректируй с кратким обоснованием):
{json.dumps(calc, ensure_ascii=False, indent=2)}

МЕТОДИЧКА (кратко):
- Сначала: материал, квалитеты Ra/H, габариты.
- Tшт = Tо + Tv + Tтех + Tорг + Tпл + Tпз/n; на практике Tшт ≈ Tо × Kвсп (Kвсп для универсальных 1.4–1.7, ЧПУ 1.2–1.3, сложные корпуса 1.8–2.0).
- Учти: внутренние радиусы карманов, глубокие отверстия H>3D, канавки (+0.5–1 мин на переход).
- Тпз: универсальные 20–40 мин/партию, ЧПУ 60–120 мин.

СТРУКТУРА ОТЧЁТА:
1. **Описание детали** — форма, назначение, ключевые элементы (как установлено по чертежу).
2. **Отверстия, пазы, резьбы, допуски, шероховатость** — перечисли фактами, без отсылок к источникам.
3. **Предлагаемая заготовка и базирование**.
4. **Технологический маршрут** — операции по порядку, без лишнего.
5. **Нормировка времени** — таблица Tо по переходам, Kвсп, Tпз, **Tшт**, время на партию.
6. **Дополнительно рекомендуется** — 3–5 пунктов проверки на чертеже или в процессе (без блока «риски» и без «требуется уточнение»).

Пиши конкретно и уверенно. Без тегов thinking."""


def finalize_flow_norm_analysis(
    project_name: str,
    user_folder: str,
    task_id: str,
    norm_inputs: Dict[str, Any],
    *,
    user_email: str = "",
) -> Dict[str, Any]:
    """После готовности hybrid job — нормировка (не deep_analysis)."""
    from flow_norm_analysis import HybridJobError, refresh_job_status

    job = refresh_job_status(project_name, user_folder, task_id)
    status = job.get("status")

    if status == "timeout":
        raise HybridJobError("timeout", ui_message="Анализ временно недоступен, попробуйте позже")
    if status == "error":
        raise HybridJobError(
            "error",
            ui_message=job.get("error_ui") or "Анализ временно недоступен, попробуйте позже",
        )
    if status != "ready":
        raise HybridJobError("pending", ui_message="Распознавание чертежа ещё выполняется")

    suffler_text = (job.get("suffler_text") or "").strip()
    if not suffler_text:
        raise HybridJobError("error", ui_message="Нет данных распознавания чертежа")

    import payment as pay

    email = (user_email or job.get("user_email") or "").strip()
    pending_entry = pay.find_flow_pending_by_task_id(email, task_id)
    if pending_entry:
        balance = pay.get_flow_token_balance(email)
        return {
            "status": "pending_payment",
            "rub_required": int(pending_entry.get("rub_required") or 0),
            "balance": balance,
            "pending_id": pending_entry.get("pending_id") or "",
            "ui_message": (
                f"Анализ выполнен. Для просмотра пополните баланс: "
                f"нужно **{pending_entry.get('rub_required')} ₽, на счёте **{balance}**."
            ),
        }

    structured = merge_structured(
        suffler_text,
        job.get("suffler_parsed"),
        job.get("auto_extraction"),
    )
    calc = compute_norm_hours(structured, norm_inputs)
    prompt = build_technologist_norm_prompt(structured, norm_inputs, calc)

    from expert_analyzer import _call_llm_with_fallback, format_llm_analysis_prefix, strip_llm_thinking_blocks
    from expert_analyzer import HYBRID_MAX_OUTPUT_TOKENS, PPLX_MODEL_HYBRID

    analysis, api_used = _call_llm_with_fallback(
        prompt,
        primary="perplexity",
        perplexity_model=PPLX_MODEL_HYBRID,
        max_tokens_primary=HYBRID_MAX_OUTPUT_TOKENS,
        max_tokens_fallback=HYBRID_MAX_OUTPUT_TOKENS,
        timeout_perplexity=300,
    )
    if not analysis:
        return {
            "status": "error",
            "message": "Не удалось сформировать отчёт по нормировке",
            "norm_calc": calc,
            "structured": structured,
        }

    analysis = strip_llm_thinking_blocks(analysis)
    result = {
        "status": "ok",
        "analysis": format_llm_analysis_prefix(api_used) + analysis,
        "api_used": api_used,
        "norm_calc": calc,
        "structured": structured,
        "hybrid_task_id": task_id,
        "flow_mode": "norm_hours_2d",
    }
    charged = int(job.get("flow_tokens_charged") or 0)
    if charged:
        result["flow_rub_charged"] = charged
        result["flow_balance"] = job.get("flow_balance_after_debit")

    job["finalize_result"] = result
    job["finalized_at"] = job.get("finalized_at") or __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    from flow_norm_analysis import save_job

    save_job(job)
    return result

def build_refine_flow_prompt(
    *,
    previous_report: str,
    channel_blocks: list,
    chat_turns: list,
    norm_inputs: dict,
    calc: dict,
    latest_text: str = "",
) -> str:
    ch_parts = []
    for i, block in enumerate(channel_blocks, 1):
        ch_parts.append(f"### Ответ канала {i}\n{(block.get('text') or '')[:8000]}")
    chat_parts = []
    for i, turn in enumerate(chat_turns, 1):
        chat_parts.append(f"**Вопрос {i}:** {(turn.get('question') or '')[:2000]}")
        chat_parts.append(f"**Ответ {i}:** {(turn.get('answer') or '')[:8000]}")
    latest_block = ""
    if latest_text:
        latest_block = f"\n### Последний ответ канала\n{latest_text[:12000]}\n"
    return f"""Ты — эксперт-технолог. Обнови отчёт по нормировке 2D-детали с учётом новых данных.
{_STYLE_RULES}

ТЕКУЩИЙ ОТЧЁТ (сохрани структуру и верное, уточни остальное):
{previous_report[:16000]}

ДАННЫЕ КАНАЛА:
{chr(10).join(ch_parts) or "—"}

ДИАЛОГ:
{chr(10).join(chat_parts) or "—"}
{latest_block}

ПАРАМЕТРЫ:
{json.dumps(norm_inputs, ensure_ascii=False, indent=2)}

ЭКСПРЕСС-РАСЧЁТ:
{json.dumps(calc, ensure_ascii=False, indent=2)}

Выдай полный обновлённый отчёт. Без thinking-тегов. Не упоминай email или внешних исполнителей.
"""


def refine_flow_report(
    project_name: str,
    user_folder: str,
    task_id: str,
    norm_inputs: Dict[str, Any],
    *,
    latest_channel_text: str = "",
    drawing_path: str = "",
) -> Dict[str, Any]:
    from flow_data_store import load_flow_data
    from flow_norm_analysis import load_job, save_job

    job = load_job(project_name, user_folder, task_id)
    prev = job.get("finalize_result") or {}
    previous_report = (prev.get("analysis") or "").strip()
    if not previous_report:
        raise HybridJobError("error", ui_message="Нет предыдущего отчёта")

    path = drawing_path or job.get("drawing_path") or job.get("pdf_path") or ""
    data = load_flow_data(path) if path else {}
    channel_blocks = data.get("channel_responses") or []
    if not channel_blocks and job.get("suffler_text"):
        channel_blocks = [{"text": job.get("suffler_text"), "task_id": task_id}]
    chat_turns = data.get("chat") or []

    structured = prev.get("structured") or merge_structured(
        job.get("suffler_text") or "",
        job.get("suffler_parsed"),
        job.get("auto_extraction"),
    )
    calc = prev.get("norm_calc") or compute_norm_hours(structured, norm_inputs)
    prompt = build_refine_flow_prompt(
        previous_report=previous_report,
        channel_blocks=channel_blocks,
        chat_turns=chat_turns,
        norm_inputs=norm_inputs,
        calc=calc,
        latest_text=latest_channel_text,
    )
    from expert_analyzer import (
        HYBRID_MAX_OUTPUT_TOKENS,
        PPLX_MODEL_HYBRID,
        _call_llm_with_fallback,
        format_llm_analysis_prefix,
        strip_llm_thinking_blocks,
    )

    analysis, api_used = _call_llm_with_fallback(
        prompt,
        primary="perplexity",
        perplexity_model=PPLX_MODEL_HYBRID,
        max_tokens_primary=HYBRID_MAX_OUTPUT_TOKENS,
        max_tokens_fallback=HYBRID_MAX_OUTPUT_TOKENS,
        timeout_perplexity=300,
    )
    if not analysis:
        return prev
    analysis = strip_llm_thinking_blocks(analysis)
    result = {
        "status": "ok",
        "analysis": format_llm_analysis_prefix(api_used) + analysis,
        "api_used": api_used,
        "norm_calc": calc,
        "structured": structured,
        "hybrid_task_id": task_id,
        "flow_mode": "norm_hours_2d",
        "refined": True,
    }
    job["finalize_result"] = result
    save_job(job)
    from flow_norm_chat import persist_initial_flow_data

    persist_initial_flow_data(job, result)
    return result

