import os
import re
import subprocess
import tempfile
from typing import Any, Dict, Optional

RED_PATTERNS = [
    r"\bсекретно\b", r"\bсов\.?\s*секретно\b", r"\bсовершенно\s+секретно\b",
    r"\bособой\s+важности\b", r"\bдсп\b", r"для\s+служебного\s+пользования",
]
YELLOW_PATTERNS = [
    r"\bконфиденциально\b", r"\bэкз\.?\s*№?\s*\d+\b", r"\bопк\b",
    r"экспортн(ый|ого)\s+контрол", r"гособоронзаказ", r"минобороны",
    r"военная\s+приемка", r"гриф",
]


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Извлекает текст из PDF через pdftotext, с фолбэком на прямой decode"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        result = subprocess.run(
            ["pdftotext", "-layout", tmp_path, "-"],
            capture_output=True, text=True, timeout=30
        )
        os.unlink(tmp_path)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception:
        pass
    # Фолбэк — старый метод на случай если pdftotext недоступен
    try:
        return pdf_bytes.decode("utf-8", errors="ignore")
    except:
        return pdf_bytes.decode("latin-1", errors="ignore")

def scan_pdf_bytes(pdf_bytes: bytes, step_data: Optional[Dict[str, Any]] = None) -> dict:
    """Только проверка PDF на грифы. Без вызова ИИ."""
    text = _extract_text_from_pdf_bytes(pdf_bytes)

    result = {
        "success": True, "classification": "safe", "pages": 1,
        "detections": [], "matched_text": [], "notes": [], "error": ""
    }

    if any(re.findall(pat, text.lower(), flags=re.IGNORECASE) for pat in RED_PATTERNS):
        result["classification"] = "blocked"
        result["notes"].append("Найдены запрещённые слова/грифы")
    elif any(re.findall(pat, text.lower(), flags=re.IGNORECASE) for pat in YELLOW_PATTERNS):
        result["classification"] = "review"
        result["notes"].append("Найдены подозрительные маркеры")
    else:
        result["notes"].append("Запрещённых слов и явных грифов не найдено")

    return result
