import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

import requests

from drawing_analysis import DRAWING_PIPELINE_VERSION

LOG = logging.getLogger("expert_analyzer")

# Суффиксы кэша analysis_cache (см. docs/ТЗ-смена-приоритета-LLM.md)
LLM_STACK_CLASSIC = "ds_primary_v1"  # «Анализировать»: DeepSeek → Perplexity sonar
LLM_STACK_HYBRID = "hybrid_sonar_rp_v1"  # Углублённый: Perplexity sonar-reasoning-pro → DeepSeek
PPLX_MODEL_DEFAULT = "sonar"
PPLX_MODEL_HYBRID = "sonar-reasoning-pro"
# sonar-reasoning-pro тратит completion_tokens на <think>; на видимый ответ
# нужен запас (иначе после strip_llm_thinking_blocks остаётся 1–2 абзаца).
HYBRID_MAX_OUTPUT_TOKENS = 16000
LLM_UI_ERROR_MESSAGE = "Сервер анализа временно недоступен"
# обратная совместимость тестов / логов
LLM_STACK_VERSION = LLM_STACK_CLASSIC

# Маркеры: 🔵 Sinlex AI 1.0 = deepseek, ⚫ Sinlex AI 1.2 = perplexity (по api_used ответа)
MARKER_SINLEX_V10 = "🔵"
MARKER_SINLEX_V12 = "⚫"
LABEL_SINLEX_V10 = "Sinlex AI 1.0"
LABEL_SINLEX_V12 = "Sinlex AI 1.2"

# Краткий LP-1 бренд — снимаем при показе / перед LLM (обе привязки эмодзи)
_SUPER_SERVER_BRAND = "Супер-серверный анализ"
_LEGACY_SUPER_SERVER_PREFIXES = (
    f"{MARKER_SINLEX_V10} {_SUPER_SERVER_BRAND}",
    f"{MARKER_SINLEX_V12} {_SUPER_SERVER_BRAND}",
)

_ANALYSIS_PREFIXES_FOR_LLM = (
    f"{MARKER_SINLEX_V10} {LABEL_SINLEX_V10}",
    f"{MARKER_SINLEX_V12} {LABEL_SINLEX_V12}",
    *_LEGACY_SUPER_SERVER_PREFIXES,
)
from drawing_analysis.reader import extract_text_from_pdf

def _load_secrets() -> Dict[str, str]:
    out: Dict[str, str] = {}
    path = os.environ.get("SINLEX_SECRETS_FILE", "/opt/sinlex/secrets.env")
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


_SECRETS = _load_secrets()
DS_API_KEY = os.environ.get("SINLEX_DS_API_KEY") or _SECRETS.get("SINLEX_DS_API_KEY", "")
DS_URL = "https://api.deepseek.com/v1/chat/completions"
PPLX_API_KEY = (
    os.environ.get("SINLEX_PPLX_API_KEY")
    or os.environ.get("PERPLEXITY_API_KEY")
    or _SECRETS.get("SINLEX_PPLX_API_KEY")
    or _SECRETS.get("PERPLEXITY_API_KEY", "")
)
PPLX_URL = "https://api.perplexity.ai/chat/completions"

def _get_project_dir(project_name: str, user_folder: str = "") -> str:
    from project_store import projects_base_dir, _safe_dir_name

    safe = _safe_dir_name(project_name)
    return os.path.join(projects_base_dir(user_folder), safe)


def _load_project_data(
    project_name: str,
    user_folder: str = "",
) -> Optional[Dict[str, Any]]:
    if not project_name:
        return None
    from project_store import load_project_data

    data = load_project_data(project_name, user_folder)
    return data if data else None

def _call_deepseek(prompt: str, *, max_tokens: int = 4000) -> Optional[str]:
    """Возвращает ответ DeepSeek или None при ошибке."""
    try:
        resp = requests.post(DS_URL,
            headers={"Authorization": f"Bearer {DS_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.05},
            timeout=180)
        if resp.status_code == 200:
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content", "")
            if choice.get("finish_reason") == "length":
                LOG.warning(
                    "deepseek truncated finish_reason=length chars=%s max_tokens=%s",
                    len(content or ""),
                    max_tokens,
                )
            return content
        return None
    except Exception:
        return None


def _call_perplexity(
    prompt: str,
    *,
    model: str = PPLX_MODEL_DEFAULT,
    max_tokens: int = 400,
    timeout: int = 180,
) -> Optional[str]:
    """Ответ Perplexity (model: sonar | sonar-reasoning-pro | …)."""
    if not PPLX_API_KEY:
        return None
    try:
        resp = requests.post(
            PPLX_URL,
            headers={"Authorization": f"Bearer {PPLX_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content", "")
            finish = choice.get("finish_reason")
            usage = data.get("usage") or {}
            comp_tok = usage.get("completion_tokens")
            if comp_tok is not None:
                LOG.info(
                    "perplexity usage model=%s completion_tokens=%s finish=%s max_tokens=%s",
                    model,
                    comp_tok,
                    finish,
                    max_tokens,
                )
            if finish == "length":
                LOG.warning(
                    "perplexity truncated finish_reason=length model=%s chars=%s max_tokens=%s",
                    model,
                    len(content or ""),
                    max_tokens,
                )
            return content
        LOG.warning("perplexity http status=%s model=%s", resp.status_code, model)
        return None
    except Exception:
        LOG.exception("perplexity request failed model=%s", model)
        return None


def _call_llm_with_fallback(
    prompt: str,
    *,
    primary: str = "deepseek",
    perplexity_model: str = PPLX_MODEL_DEFAULT,
    max_tokens_primary: int = 4000,
    max_tokens_fallback: int = 4000,
    timeout_perplexity: int = 180,
) -> Tuple[Optional[str], Optional[str]]:
    """
    primary=deepseek: DeepSeek → Perplexity (классика, техкарта).
    primary=perplexity: Perplexity → DeepSeek (углублённый анализ).
    Returns (text, api_used) where api_used is perplexity|deepseek|None.
    """
    if primary == "deepseek":
        text = _call_deepseek(prompt, max_tokens=max_tokens_primary)
        if text:
            LOG.info("llm api_used=deepseek stack=ds_primary")
            return text.strip(), "deepseek"
        text = _call_perplexity(
            prompt,
            model=perplexity_model,
            max_tokens=max_tokens_fallback,
            timeout=timeout_perplexity,
        )
        if text:
            LOG.info("llm api_used=perplexity stack=ds_primary_fallback model=%s", perplexity_model)
            return text.strip(), "perplexity"
    else:
        text = _call_perplexity(
            prompt,
            model=perplexity_model,
            max_tokens=max_tokens_primary,
            timeout=timeout_perplexity,
        )
        if text:
            LOG.info("llm api_used=perplexity stack=hybrid model=%s", perplexity_model)
            return text.strip(), "perplexity"
        text = _call_deepseek(prompt, max_tokens=max_tokens_fallback)
        if text:
            LOG.info("llm api_used=deepseek stack=hybrid_fallback")
            return text.strip(), "deepseek"
    LOG.warning("llm api_used=none primary=%s model=%s", primary, perplexity_model)
    return None, None


def format_llm_analysis_prefix(api_used: Optional[str]) -> str:
    """Видимый префикс: ⚫ Sinlex AI 1.2 (основной) / 🔵 Sinlex AI 1.0 (резерв)."""
    if api_used == "perplexity":
        return f"{MARKER_SINLEX_V12} {LABEL_SINLEX_V12}\n\n"
    if api_used == "deepseek":
        return f"{MARKER_SINLEX_V10} {LABEL_SINLEX_V10}\n\n"
    return ""


def build_expert_cache_suffix(suffler_text: Optional[str] = None) -> str:
    """Суффикс имени файла кэша экспертного анализа."""
    base = f"draw_v{DRAWING_PIPELINE_VERSION}"
    if suffler_text and str(suffler_text).strip():
        norm = "\n".join(line.strip() for line in suffler_text.strip().splitlines())
        suffler_hash = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
        return f"{base}_{LLM_STACK_HYBRID}_hybrid_{suffler_hash}"
    return f"{base}_{LLM_STACK_CLASSIC}"



_LLM_THINKING_PATTERNS = (
    r"<think>\s*.*?\s*</think>\s*",
    r"<thinking>\s*.*?\s*</thinking>\s*",
)


def strip_llm_thinking_blocks(text: str) -> str:
    """Убрать служебные блоки рассуждений модели (не показывать в UI)."""
    if not text:
        return ""
    out = text
    for pat in _LLM_THINKING_PATTERNS:
        out = re.sub(pat, "", out, flags=re.DOTALL | re.IGNORECASE)
    return out.strip()


def strip_analysis_prefix_for_llm(text: str) -> str:
    """Убрать маркеры перед отправкой текста в LLM (техкарта и т.п.)."""
    if not text:
        return ""
    out = text.strip()
    for prefix in _ANALYSIS_PREFIXES_FOR_LLM:
        if out.startswith(prefix):
            out = out[len(prefix) :].lstrip("\n")
    return out.strip()


def normalize_analysis_display(text: str) -> str:
    """Для UI: снять thinking-блоки и устаревший «Супер-серверный анализ»."""
    if not text:
        return ""
    out = strip_llm_thinking_blocks(text)
    for legacy in _LEGACY_SUPER_SERVER_PREFIXES:
        if out.startswith(legacy):
            return out[len(legacy) :].lstrip("\n")
    return out


def _normalize_brief_text(text: str) -> str:
    """2–3 строки без markdown и вводных фраз."""
    if not text:
        return ""
    lines = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip().lstrip("-•* ").strip()
        if not line or line.startswith("```"):
            continue
        for prefix in ("я думаю", "возможно", "вероятно", "скорее всего", "похоже"):
            if line.lower().startswith(prefix):
                line = line[len(prefix):].strip(" ,.—")
        if line:
            lines.append(line)
    return "\n".join(lines[:3])


def manufacturing_brief(
    context: Dict[str, Any],
    project_name: str = "",
    user_folder: str = "",
) -> Dict[str, Any]:
    """Краткое резюме по STEP (DeepSeek → Perplexity, LP-5). Кэш с суффиксом LLM_STACK_CLASSIC."""
    if not context:
        return {"status": "error", "message": "Нет данных для анализа", "api_used": None}

    payload = json.dumps(context, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    cache_file = None
    if project_name:
        cache_dir = os.path.join(_get_project_dir(project_name, user_folder), "analysis_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(
            cache_dir,
            f"manufacturing_brief_{digest}_{LLM_STACK_CLASSIC}.json",
        )
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    if cached.get("summary"):
                        if "api_used" not in cached:
                            cached["api_used"] = "deepseek"
                        if "llm_stack_version" not in cached:
                            cached["llm_stack_version"] = LLM_STACK_CLASSIC
                        return cached
            except Exception:
                pass

    prompt = f"""Ты инженер-технолог-наладчик станков с ЧПУ. Проанализируй данные по STEP-модели и сделай вывод по изготовлению данной детали.
Пиши сухо — по делу. Без «я думаю», «возможно», «вероятно» и подобных оговорок.
Охвати: время и стоимость изготовления (резание), наладку, написание УП, распределение затрат на партию.
Ровно 2–3 короткие строки текста на русском. Без списков, заголовков и markdown.

ДАННЫЕ (JSON):
{json.dumps(context, ensure_ascii=False, indent=2)}"""

    summary, api_used = _call_llm_with_fallback(
        prompt,
        primary="deepseek",
        perplexity_model=PPLX_MODEL_DEFAULT,
        max_tokens_primary=350,
        max_tokens_fallback=350,
    )

    if not summary:
        return {"status": "error", "message": LLM_UI_ERROR_MESSAGE, "api_used": None}

    clean_summary = _normalize_brief_text(
        strip_analysis_prefix_for_llm(summary.strip()),
    )
    result = {
        "status": "ok",
        "summary": clean_summary,
        "api_used": api_used,
        "llm_stack_version": LLM_STACK_CLASSIC,
    }
    if cache_file:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return result

def deep_analysis(
    pdf_bytes: bytes = None,
    step_data: Optional[Dict[str, Any]] = None,
    project_name: str = "",
    *,
    suffler_text: Optional[str] = None,
    hybrid_task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Экспертный анализ (Perplexity → DeepSeek) с OCR/STEP и опциональным suffler_text."""
    step_data_local: Dict[str, Any] = {}
    if not project_name:
        return {"status": "error", "message": "Не указан проект", "api_used": None}

    user_folder = (step_data or {}).get("user_folder", "") if step_data else ""
    try:
        step_data_local = _load_project_data(project_name, user_folder) or (step_data or {})
    except Exception:
        step_data_local = dict(step_data or {})

    project_dir = _get_project_dir(project_name, user_folder)
    cache_dir = os.path.join(project_dir, "analysis_cache")
    os.makedirs(cache_dir, exist_ok=True)

    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest() if pdf_bytes else "no_pdf"
    analysis_ver = str(step_data_local.get("step_analysis_version") or "legacy")
    cache_suffix = build_expert_cache_suffix(suffler_text)
    cache_file = os.path.join(cache_dir, f"{pdf_hash}_{analysis_ver}_{cache_suffix}.json")

    # Возвращаем кэш, если он есть
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
                if "api_used" not in cached:
                    cached["api_used"] = "deepseek"
                if cached.get("analysis"):
                    a = cached["analysis"]
                    cleaned = strip_llm_thinking_blocks(a)
                    if cleaned != a:
                        cached["analysis"] = cleaned
                return cached
        except:
            pass

    drawing_extraction = (
        step_data_local.get("drawing_extraction")
        if isinstance(step_data_local.get("drawing_extraction"), dict)
        else None
    )
    if not drawing_extraction and pdf_bytes:
        drawing_extraction = extract_text_from_pdf(pdf_bytes)
    elif not drawing_extraction:
        drawing_extraction = {}
    drawing_manufacturing_criteria = None
    drawing_data = dict(drawing_extraction.get("fields") or {}) if drawing_extraction else {}
    if isinstance(drawing_data, dict) and "material" in drawing_data:
        del drawing_data["material"]
    dims = step_data_local.get("dimensions", {}) if step_data_local else {}
    geom = step_data_local.get("geometry", {}) if step_data_local else {}
    rod_features = step_data_local.get("rod_features") or []

    try:
        from extraction_tool.extractor import build_expert_geometry_brief

        geometry_brief = build_expert_geometry_brief(project_name, step_data_local)
    except Exception:
        geometry_brief = ""

    holes = step_data_local.get("holes") or geom.get("holes") or []
    shafts = step_data_local.get("shafts") or geom.get("shafts") or []
    ms = step_data_local.get("model_size") or {}

    suffler_block = ""
    if suffler_text and str(suffler_text).strip():
        suffler_block = f"""
ДАННЫЕ УГЛУБЛЁННОГО РАСПОЗНАВАНИЯ (приоритет 1):
{str(suffler_text).strip()}

Правила:
- Эти данные считай основным источником по чертежу.
- При расхождении с автоматическим OCR/парсером — доверяй блоку приоритета 1.
- По отверстиям и количествам — опирайся на данные STEP и блок распознавания.
- Не упоминай источник данных и качество распознавания.
"""

    criteria_block = ""
    try:
        from drawing_analysis.manufacturing_criteria import extract_manufacturing_criteria

        pre_crit = extract_manufacturing_criteria(
            drawing_extraction, expert_text=""
        )
        crit_summary = (pre_crit.get("summary_ru") or "").strip()
        if crit_summary and pre_crit.get("active_codes"):
            criteria_block = f"""
Критерии для расчёта Sinlex (из чертежа; Ø и количества — из STEP):
{crit_summary}
"""
    except Exception:
        pass
    if not criteria_block:
        saved_crit = step_data_local.get("drawing_manufacturing_criteria") or {}
        crit_summary = (saved_crit.get("summary_ru") or "").strip()
        if crit_summary and saved_crit.get("active_codes"):
            criteria_block = f"""
Критерии для расчёта Sinlex (из чертежа; Ø и количества — из STEP):
{crit_summary}
"""

    prompt = f"""Ты — эксперт-технолог. Проанализируй деталь.

ДАННЫЕ ИЗ ЧЕРТЕЖА (распознано OCR):
{json.dumps(drawing_data, ensure_ascii=False, indent=2)}

ДАННЫЕ ИЗ 3D-МОДЕЛИ (STEP):
- Название: {project_name}
- Материал (основной): {step_data_local.get('material', 'не указан') if step_data_local else 'нет данных'}
- Объём: {step_data_local.get('volume', '?')} мм³
- Габариты (X×Y×Z): {dims.get('x','?')} × {dims.get('y','?')} × {dims.get('z','?')} мм
- Модель (основной размер): {json.dumps(ms, ensure_ascii=False)}
- Сложность: {geom.get('complexity') or step_data_local.get('complexity', '?')}
- Семейство: {geom.get('family') or step_data_local.get('part_type') or step_data_local.get('part_family', '?')}
- Наружные контуры (shafts): {json.dumps(shafts, ensure_ascii=False)}
- Отверстия (holes): {json.dumps(holes, ensure_ascii=False)}
- Признаки прутка: {json.dumps(rod_features, ensure_ascii=False) if rod_features else '—'}
- Заготовка (STEP): {json.dumps(step_data_local.get('workpiece') or {}, ensure_ascii=False)}
- Процессы (STEP): {json.dumps(step_data_local.get('operations') or [], ensure_ascii=False)}

ИНТЕРПРЕТАЦИЯ ГЕОМЕТРИИ (обязательно учти, не противоречь):
{geometry_brief or '—'}
{suffler_block}{criteria_block}
ЗАДАЧА:
1. Тип детали — по названию и блоку «ИНТЕРПРЕТАЦИЯ ГЕОМЕТРИИ».
2. Наружные цилиндры (тело вала/прутка) и отверстия — только как в интерпретации и списках shafts/holes. Запрещено правило «Ø>20 мм = вал, ≤20 мм = отверстие»: у валов наружный Ø часто 8–20 мм.
3. Техпроцесс, инструмент, оснастка — по процессам STEP и форме детали; без лишних операций (термообработка, шлифование), если в чертеже нет указаний.
4. Чертёж: только ясные допуски, шероховатость, требования; без комментариев про OCR.
5. Развёрнутое итоговое резюме: по каждому пункту 1–4 — не менее 2–3 предложений; в п.5 — сводка на 4–6 предложений.

Пиши по делу, без «я думаю», «возможно», «вероятно».
Не выводи теги thinking, redacted_thinking и ход рассуждений — только итоговый текст по пунктам задачи."""

    is_hybrid = bool(suffler_text and str(suffler_text).strip())
    if is_hybrid:
        analysis, api_used = _call_llm_with_fallback(
            prompt,
            primary="perplexity",
            perplexity_model=PPLX_MODEL_HYBRID,
            max_tokens_primary=HYBRID_MAX_OUTPUT_TOKENS,
            max_tokens_fallback=HYBRID_MAX_OUTPUT_TOKENS,
            timeout_perplexity=300,
        )
        stack_version = LLM_STACK_HYBRID
    else:
        analysis, api_used = _call_llm_with_fallback(
            prompt,
            primary="deepseek",
            perplexity_model=PPLX_MODEL_DEFAULT,
            max_tokens_primary=4000,
            max_tokens_fallback=4000,
        )
        stack_version = LLM_STACK_CLASSIC

    if not analysis:
        return {
            "status": "error",
            "message": LLM_UI_ERROR_MESSAGE,
            "api_used": None,
        }

    raw_len = len(analysis or "")
    analysis = strip_llm_thinking_blocks(analysis)
    if is_hybrid and api_used == "perplexity" and raw_len > 800 and len(analysis) < 1500:
        LOG.warning(
            "hybrid perplexity short visible text after thinking strip raw=%s visible=%s",
            raw_len,
            len(analysis),
        )

    result = {
        "status": "ok",
        "analysis": format_llm_analysis_prefix(api_used) + analysis,
        "api_used": api_used,
        "llm_stack_version": stack_version,
    }
    if drawing_extraction:
        result["drawing_extraction"] = drawing_extraction
    if hybrid_task_id:
        result["hybrid_task_id"] = hybrid_task_id
    if suffler_text and str(suffler_text).strip():
        result["hybrid_suffler_applied"] = True

    if drawing_extraction:
        from drawing_analysis.manufacturing_criteria import extract_manufacturing_criteria

        drawing_manufacturing_criteria = extract_manufacturing_criteria(
            drawing_extraction,
            expert_text=result.get("analysis", ""),
        )
        if pdf_hash and pdf_hash != "no_pdf":
            drawing_manufacturing_criteria["pdf_hash"] = pdf_hash
        result["drawing_manufacturing_criteria"] = drawing_manufacturing_criteria

    try:
        from project_store import load_project_data, save_project_data

        pdata = load_project_data(project_name, user_folder) or {}
        if drawing_extraction:
            pdata["drawing_extraction"] = drawing_extraction
        if drawing_manufacturing_criteria:
            pdata["drawing_manufacturing_criteria"] = drawing_manufacturing_criteria
        if pdata:
            save_project_data(project_name, pdata, user_folder)
    except Exception:
        pass

    with open(cache_file, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result

def tech_card_analysis(analysis_text: str = "", step_data: Optional[Dict[str, Any]] = None, log_data: Optional[list] = None) -> Dict[str, Any]:
    """Техкарта (DeepSeek → Perplexity sonar). Входной analysis_text — без UI-маркеров."""
    clean_analysis = strip_analysis_prefix_for_llm(analysis_text or "")

    log_context = ""
    if log_data and isinstance(log_data, list) and len(log_data) > 0:
        prev = [
            strip_analysis_prefix_for_llm(str(e.get("analysis", "")))
            for e in log_data[-3:]
        ]
        log_context = "\nПРЕДЫДУЩИЕ АНАЛИЗЫ:\n" + "\n---\n".join(
            [json.dumps(p, ensure_ascii=False) for p in prev if p]
        )

    sd = step_data if isinstance(step_data, dict) else {}
    quote = sd.get("costing_quote") or {}
    step_geom = {k: v for k, v in sd.items() if k != "costing_quote"}

    quote_block = ""
    if quote:
        quote_lines = "\n".join(f"- {k}: {v}" for k, v in quote.items())
        quote_block = f"""
РАСЧЁТ ВРЕМЕНИ И СТОИМОСТИ ИЗ ПРИЛОЖЕНИЯ SINLEX (источник истины, не выдумывай другие цифры):
{quote_lines}
"""

    prompt = f"""Ты — главный технолог. Составь ТЕХНОЛОГИЧЕСКУЮ КАРТУ.

РЕЗУЛЬТАТ ЭКСПЕРТНОГО АНАЛИЗА ЧЕРТЕЖА (операции, инструмент, геометрия, допуски):
{clean_analysis[:5000]}

ДАННЫЕ ЗАГОТОВКИ И STEP:
{json.dumps(step_geom, ensure_ascii=False, indent=2)}
{quote_block}
{log_context}

ФОРМАТ:
1. Маршрут обработки (по результату экспертного анализа)
2. Для каждой операции: оборудование, инструмент, оснастка, режимы
3. Количество установов — если в расчёте Sinlex есть «Количество установов (OCC)», используй это число и поясни переворот/переналадку при «Переворот плиты: да»
4. Контрольные операции
5. **Итоговое время обработки** — только из блока расчёта Sinlex:
   - Партия: N шт.
   - Время на 1 деталь: X ч (целое число из «Время на 1 деталь, ч»)
   - Время на партию: Y ч (целое из «Время на партию, ч»)
   Только часы, без минут, без десятичных дробей. Пиши по-русски, без технических кодов.
   Если блока расчёта нет — оцени в целых часах вверх и пометь «оценка».

Пиши кратко, только понятный технологу текст. В конце DEBUG_TECHCARD_2026."""

    result, api_used = _call_llm_with_fallback(
        prompt,
        primary="deepseek",
        perplexity_model=PPLX_MODEL_DEFAULT,
        max_tokens_primary=4000,
        max_tokens_fallback=4000,
    )

    if not result:
        return {
            "status": "error",
            "message": LLM_UI_ERROR_MESSAGE,
            "api_used": None,
        }

    return {
        "status": "ok",
        "analysis": format_llm_analysis_prefix(api_used) + result,
        "api_used": api_used,
        "llm_stack_version": LLM_STACK_CLASSIC,
    }
