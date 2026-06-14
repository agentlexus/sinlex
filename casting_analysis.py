"""ИИ-анализ литьевого проекта: промпт, LLM, хранение data_casting.json."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from casting_io import data_casting_path
from project_store import load_project_data

DATA_CASTING_FILE = "data_casting.json"


def load_data_casting(project_name: str, user_folder: str) -> Dict[str, Any]:
    path = data_casting_path(project_name, user_folder)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_data_casting(
    project_name: str,
    user_folder: str,
    *,
    analysis_text: str,
    api_used: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    cost: Optional[Dict[str, Any]] = None,
    prompt_hash: str = "",
) -> None:
    path = data_casting_path(project_name, user_folder)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "project_name": project_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_text": (analysis_text or "").strip(),
        "api_used": api_used or "",
        "params": params or {},
        "cost_snapshot": cost or {},
        "prompt_hash": prompt_hash,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _compact_occ_data(data: Dict[str, Any]) -> Dict[str, Any]:
    if not data:
        return {}
    geom = data.get("geometry") or {}
    keys = (
        "project_name",
        "volume",
        "surface_area",
        "dimensions",
        "model_size",
        "bbox_dimensions",
        "part_family",
        "part_type",
        "operations",
        "workpiece",
        "workpiece_analysis",
        "min_wall_thickness_mm",
        "thin_walls",
        "detail_index",
        "elongation_index",
        "complexity",
        "holes",
        "shafts",
        "rod_features",
        "face_count",
        "has_internal_void",
    )
    out: Dict[str, Any] = {}
    for key in keys:
        if key in data and data[key] is not None:
            out[key] = data[key]
    if geom:
        out["geometry"] = geom
    sa = data.get("step_analysis")
    if isinstance(sa, dict) and sa.get("volume") is not None:
        out["step_analysis_summary"] = {
            "volume": sa.get("volume"),
            "surface_area": sa.get("surface_area"),
            "min_wall_thickness_mm": sa.get("min_wall_thickness_mm"),
            "part_family": sa.get("part_family"),
        }
    return out


def build_casting_analysis_prompt(
    project_name: str,
    *,
    params: Dict[str, Any],
    cost: Dict[str, Any],
    occ_data: Dict[str, Any],
) -> str:
    from extraction_tool.extractor import build_expert_geometry_brief

    brief = build_expert_geometry_brief(project_name, occ_data)
    occ_json = json.dumps(_compact_occ_data(occ_data), ensure_ascii=False, indent=2)
    params_json = json.dumps(params, ensure_ascii=False, indent=2)
    cost_json = json.dumps(cost, ensure_ascii=False, indent=2)

    return f"""Роль: технолог-литейщик. Проанализируй деталь для изготовления методом литья.

Стиль ответа (обязательно):
- Без приветствий и прощаний («Приветствую», «Здравствуйте», «Добрый день» и т.п.).
- Без вводных фраз о себе («Как технолог-литейщик…», «Провёл анализ…», «На основе данных…»).
- Начни сразу с первого содержательного раздела анализа (заголовок или пункт 1).

## Проект
Название: {project_name}

## Параметры литья (выбор пользователя)
{params_json}

## Расчёт стоимости (модель Sinlex, ориентир ₽/кг + оснастка)
{cost_json}

## Геометрия STEP (pythonOCC, краткая сводка)
{brief}

## Данные анализа STEP (pythonOCC, фрагмент data.txt)
{occ_json}

## Задача
1. Оцени пригодность выбранного **типа литья** и **материала** для данной геометрии (риски недолива, усадочных раковин, коробления, стержней).
2. Укажи замечания по **минимальной толщине стенки**, габаритам, массе, сложности.
3. Прокомментируй **усадку** и **припуск** — достаточны ли для технологии.
4. На основе **всех данных** (параметры, геометрия pythonOCC, блок «Расчёт стоимости») обязательно выведи отдельный блок **«Стоимость»**:
   - **За 1 шт, ₽** — полная цена одной отливки с учётом литья и доли оснастки на партию (ориентир: `cost_per_unit` из расчёта Sinlex; при необходимости кратко расшифруй: литьё + оснастка/N).
   - **На партию, ₽** — итог за указанное количество шт (ориентир: `total_cost`, партия = `batch_size` из параметров).
   - Укажи размерность **₽**, целые рубли; не придумывай другие цифры, если они уже есть в расчёте — используй их и поясни состав.
5. Сопоставь расчёт с типичной логикой литья (без выдуманных точных цен завода).
6. Дай **рекомендации**: оптимальный процесс, доработка модели, партия, контроль качества.

Формат ответа: структурированный текст на русском (заголовки ## или нумерованные блоки). Блок «Стоимость» — обязателен. Без JSON. Без рассуждений вслух. Без приветствий и вводных фраз — только анализ."""


def run_casting_ai_analysis(
    project_name: str,
    user_folder: str,
    *,
    params: Dict[str, Any],
    cost: Dict[str, Any],
) -> Tuple[str, Optional[str]]:
    """Вызов LLM; возвращает (текст анализа, api_used)."""
    from expert_analyzer import (
        LLM_UI_ERROR_MESSAGE,
        _call_llm_with_fallback,
        format_llm_analysis_prefix,
        strip_llm_thinking_blocks,
    )

    occ_data = load_project_data(project_name, user_folder, storage="casting") or {}
    prompt = build_casting_analysis_prompt(
        project_name, params=params, cost=cost, occ_data=occ_data
    )
    analysis, api_used = _call_llm_with_fallback(
        prompt,
        primary="deepseek",
        max_tokens_primary=6000,
        max_tokens_fallback=6000,
    )
    if not analysis:
        return LLM_UI_ERROR_MESSAGE, None
    analysis = strip_llm_thinking_blocks(analysis)
    prefix = format_llm_analysis_prefix(api_used)
    return prefix + analysis, api_used
