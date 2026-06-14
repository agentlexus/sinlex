"""Извлечение и разбор текста чертежей (PDF)."""

from drawing_analysis.config import DRAWING_PIPELINE_VERSION
from drawing_analysis.config import effective_ocr_engine
from drawing_analysis.reader import (
    CascadeReader,
    extract_text_from_pdf,
    extract_text_per_page,
    merge_pages,
)
from drawing_analysis.compare import compare_drawing_to_step
from drawing_analysis.criteria_config import COSTING_CRITERIA_VERSION
from drawing_analysis.manufacturing_criteria import (
    criteria_applies_to_pdf,
    extract_manufacturing_criteria,
)
from drawing_analysis.layout import extract_layout_from_pdf
from drawing_analysis.parser import (
    merge_fields_with_layout,
    parse_dimensions_from_text,
    parse_drawing_text_to_fields,
)

__all__ = [
    "COSTING_CRITERIA_VERSION",
    "DRAWING_PIPELINE_VERSION",
    "CascadeReader",
    "compare_drawing_to_step",
    "criteria_applies_to_pdf",
    "extract_manufacturing_criteria",
    "effective_ocr_engine",
    "extract_layout_from_pdf",
    "extract_text_from_pdf",
    "extract_text_per_page",
    "merge_fields_with_layout",
    "merge_pages",
    "parse_dimensions_from_text",
    "parse_drawing_text_to_fields",
]
