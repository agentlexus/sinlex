"""Тесты LLM LP-0…LP-2 (docs/ТЗ-смена-приоритета-LLM.md)."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from expert_analyzer import (
    LABEL_SINLEX_V10,
    LABEL_SINLEX_V12,
    LLM_STACK_CLASSIC,
    LLM_STACK_HYBRID,
    LLM_UI_ERROR_MESSAGE,
    MARKER_SINLEX_V10,
    MARKER_SINLEX_V12,
    HYBRID_MAX_OUTPUT_TOKENS,
    PPLX_MODEL_HYBRID,
    _call_llm_with_fallback,
    build_expert_cache_suffix,
    deep_analysis,
    format_llm_analysis_prefix,
    manufacturing_brief,
    normalize_analysis_display,
    strip_analysis_prefix_for_llm,
    tech_card_analysis,
)


class TestLlmFallback(unittest.TestCase):
    @patch("expert_analyzer._call_deepseek", return_value="ответ deepseek")
    @patch("expert_analyzer._call_perplexity", return_value=None)
    def test_classic_deepseek_primary(self, _pplx, _ds) -> None:
        text, api_used = _call_llm_with_fallback("prompt test", primary="deepseek")
        self.assertEqual(api_used, "deepseek")
        self.assertEqual(text, "ответ deepseek")

    @patch("expert_analyzer._call_deepseek", return_value=None)
    @patch("expert_analyzer._call_perplexity", return_value="ответ pplx")
    def test_classic_deepseek_fail_pplx_ok(self, pplx_mock, _ds) -> None:
        text, api_used = _call_llm_with_fallback("prompt test", primary="deepseek")
        self.assertEqual(api_used, "perplexity")
        self.assertEqual(text, "ответ pplx")
        pplx_mock.assert_called_once()

    @patch("expert_analyzer._call_deepseek", return_value=None)
    @patch("expert_analyzer._call_perplexity", return_value=None)
    def test_both_fail(self, _pplx, _ds) -> None:
        text, api_used = _call_llm_with_fallback("prompt test", primary="deepseek")
        self.assertIsNone(text)
        self.assertIsNone(api_used)
        self.assertIn("недоступен", LLM_UI_ERROR_MESSAGE)

    @patch("expert_analyzer._call_deepseek")
    @patch("expert_analyzer._call_perplexity", return_value="ответ hybrid")
    def test_hybrid_sonar_reasoning_pro_primary(self, pplx_mock, ds_mock) -> None:
        text, api_used = _call_llm_with_fallback(
            "prompt test",
            primary="perplexity",
            perplexity_model=PPLX_MODEL_HYBRID,
        )
        self.assertEqual(api_used, "perplexity")
        self.assertEqual(text, "ответ hybrid")
        ds_mock.assert_not_called()
        self.assertEqual(pplx_mock.call_args.kwargs.get("model"), PPLX_MODEL_HYBRID)


class TestMarkers(unittest.TestCase):
    def test_prefix_perplexity(self) -> None:
        p = format_llm_analysis_prefix("perplexity")
        self.assertIn(MARKER_SINLEX_V12, p)
        self.assertIn(LABEL_SINLEX_V12, p)
        self.assertNotIn("Perplexity", p)

    def test_prefix_deepseek(self) -> None:
        p = format_llm_analysis_prefix("deepseek")
        self.assertIn(MARKER_SINLEX_V10, p)
        self.assertIn(LABEL_SINLEX_V10, p)

    def test_strip_for_llm_removes_sinlex_header(self) -> None:
        raw = f"{MARKER_SINLEX_V12} {LABEL_SINLEX_V12}\n\nТекст анализа"
        self.assertEqual(strip_analysis_prefix_for_llm(raw), "Текст анализа")

    def test_normalize_keeps_sinlex(self) -> None:
        raw = f"{MARKER_SINLEX_V10} {LABEL_SINLEX_V10}\n\nТекст"
        self.assertEqual(normalize_analysis_display(raw), raw)

    def test_normalize_strips_super_server(self) -> None:
        raw = f"{MARKER_SINLEX_V10} Супер-серверный анализ\n\nСтарый текст"
        self.assertEqual(normalize_analysis_display(raw), "Старый текст")


class TestCacheSuffix(unittest.TestCase):
    def test_classic_stack_in_suffix(self) -> None:
        self.assertIn(LLM_STACK_CLASSIC, build_expert_cache_suffix())

    def test_hybrid_suffix(self) -> None:
        s = build_expert_cache_suffix("Ra 1.6")
        self.assertIn("_hybrid_", s)
        self.assertIn(LLM_STACK_HYBRID, s)


class TestDeepAnalysisLp1(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = "Test_LP1"
        self.pdir = os.path.join(self.tmp.name, self.project)
        os.makedirs(self.pdir, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_deep(self, **kwargs):
        with patch("expert_analyzer._get_project_dir", return_value=self.pdir):
            with patch(
                "expert_analyzer.extract_text_from_pdf",
                return_value={"fields": {}, "full_text": "ocr"},
            ):
                with patch(
                    "drawing_analysis.manufacturing_criteria.extract_manufacturing_criteria",
                    return_value={"active_codes": [], "summary_ru": ""},
                ):
                        with patch(
                            "project_store.load_project_data",
                            return_value={},
                        ):
                            with patch("project_store.save_project_data"):
                                with patch(
                                    "extraction_tool.extractor.build_expert_geometry_brief",
                                    return_value="brief",
                                ):
                                    return deep_analysis(
                                        b"%PDF-test",
                                        step_data={
                                            "user_folder": "",
                                            "step_analysis_version": "v1",
                                        },
                                        project_name=self.project,
                                        **kwargs,
                                    )

    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=("Текст экспертного анализа", "deepseek"),
    )
    def test_deep_analysis_classic_deepseek(self, mock_fb) -> None:
        result = self._run_deep()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["api_used"], "deepseek")
        self.assertIn(MARKER_SINLEX_V10, result["analysis"])
        self.assertEqual(mock_fb.call_args.kwargs.get("primary"), "deepseek")
        self.assertEqual(result.get("llm_stack_version"), LLM_STACK_CLASSIC)

    @patch("expert_analyzer._call_llm_with_fallback", return_value=(None, None))
    def test_deep_analysis_llm_unavailable(self, _fb) -> None:
        result = self._run_deep()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], LLM_UI_ERROR_MESSAGE)

    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=("гибридный ответ", "perplexity"),
    )
    def test_deep_analysis_suffler_hybrid_model(self, mock_fb) -> None:
        result = self._run_deep(suffler_text="Маховик Ra 0.8")
        self.assertEqual(result["status"], "ok")
        prompt = mock_fb.call_args[0][0]
        self.assertIn("ДАННЫЕ УГЛУБЛЁННОГО РАСПОЗНАВАНИЯ", prompt)
        self.assertIn("Маховик Ra 0.8", prompt)
        self.assertTrue(result.get("hybrid_suffler_applied"))
        self.assertEqual(mock_fb.call_args.kwargs.get("primary"), "perplexity")
        self.assertEqual(mock_fb.call_args.kwargs.get("perplexity_model"), PPLX_MODEL_HYBRID)
        self.assertEqual(
            mock_fb.call_args.kwargs.get("max_tokens_primary"), HYBRID_MAX_OUTPUT_TOKENS
        )
        self.assertEqual(result.get("llm_stack_version"), LLM_STACK_HYBRID)

    def test_cache_path_includes_stack_version(self) -> None:
        suffix = build_expert_cache_suffix()
        self.assertIn(LLM_STACK_CLASSIC, suffix)
        self.assertTrue(suffix.startswith("draw_v"))

    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=("Текст с кэшем", "perplexity"),
    )
    def test_hybrid_cache_stores_api_used(self, _fb) -> None:
        """LP-4: analysis_cache.json содержит api_used после углублённого анализа."""
        result = self._run_deep(suffler_text="Маховик Ra 1.6", hybrid_task_id="hybrid-t1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["api_used"], "perplexity")
        cache_dir = os.path.join(self.pdir, "analysis_cache")
        files = glob.glob(os.path.join(cache_dir, "*.json"))
        self.assertTrue(files, "cache file expected")
        with open(files[0], encoding="utf-8") as f:
            cached = json.load(f)
        self.assertEqual(cached.get("api_used"), "perplexity")
        self.assertIn(LLM_STACK_HYBRID, files[0])
        self.assertIn(MARKER_SINLEX_V12, cached.get("analysis", ""))


class TestManufacturingBriefLp5(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = "Test_LP5"
        self.pdir = os.path.join(self.tmp.name, self.project)
        os.makedirs(self.pdir, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=("Строка 1\nСтрока 2", "deepseek"),
    )
    def test_brief_deepseek_primary(self, mock_fb) -> None:
        ctx = {"material": "Сталь", "volume": 1000}
        with patch("expert_analyzer._get_project_dir", return_value=self.pdir):
            result = manufacturing_brief(ctx, project_name=self.project)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["api_used"], "deepseek")
        self.assertEqual(result.get("llm_stack_version"), LLM_STACK_CLASSIC)
        self.assertIn("Строка 1", result["summary"])
        self.assertEqual(mock_fb.call_args.kwargs.get("primary"), "deepseek")

    @patch("expert_analyzer._call_llm_with_fallback", return_value=(None, None))
    def test_brief_llm_unavailable(self, _fb) -> None:
        with patch("expert_analyzer._get_project_dir", return_value=self.pdir):
            result = manufacturing_brief({"x": 1}, project_name=self.project)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], LLM_UI_ERROR_MESSAGE)

    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=(
            f"{MARKER_SINLEX_V12} {LABEL_SINLEX_V12}\n\nРезюме по детали",
            "perplexity",
        ),
    )
    def test_brief_strips_accidental_marker(self, _fb) -> None:
        with patch("expert_analyzer._get_project_dir", return_value=self.pdir):
            result = manufacturing_brief({"part": "вал"}, project_name=self.project)
        self.assertNotIn(LABEL_SINLEX_V12, result["summary"])
        self.assertIn("Резюме по детали", result["summary"])
        self.assertEqual(result["api_used"], "perplexity")

    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=("Кэшируемое резюме", "deepseek"),
    )
    def test_brief_cache_filename_includes_stack(self, _fb) -> None:
        ctx = {"batch": 10}
        with patch("expert_analyzer._get_project_dir", return_value=self.pdir):
            manufacturing_brief(ctx, project_name=self.project)
            manufacturing_brief(ctx, project_name=self.project)
        self.assertEqual(_fb.call_count, 1)
        cache_path = os.path.join(
            self.pdir,
            "analysis_cache",
            f"manufacturing_brief_{hashlib.sha256(json.dumps(ctx, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]}_{LLM_STACK_CLASSIC}.json",
        )
        self.assertTrue(os.path.isfile(cache_path))
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        self.assertEqual(cached.get("api_used"), "deepseek")


class TestTechCardLp2(unittest.TestCase):
    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=("Маршрут обработки", "deepseek"),
    )
    def test_tech_card_strips_input_prefix(self, mock_fb) -> None:
        raw = f"{MARKER_SINLEX_V12} {LABEL_SINLEX_V12}\n\nТело экспертного анализа"
        result = tech_card_analysis(raw, step_data={}, log_data=[])
        self.assertEqual(result["status"], "ok")
        prompt = mock_fb.call_args[0][0]
        self.assertIn("Тело экспертного анализа", prompt)
        self.assertNotIn(LABEL_SINLEX_V12, prompt.split("РЕЗУЛЬТАТ")[1][:200])
        self.assertEqual(mock_fb.call_args.kwargs.get("primary"), "deepseek")
        self.assertIn(MARKER_SINLEX_V10, result["analysis"])
        self.assertIn(LABEL_SINLEX_V10, result["analysis"])

    @patch("expert_analyzer._call_llm_with_fallback", return_value=(None, None))
    def test_tech_card_llm_unavailable(self, _fb) -> None:
        result = tech_card_analysis("текст", step_data={}, log_data=[])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], LLM_UI_ERROR_MESSAGE)

    @patch(
        "expert_analyzer._call_llm_with_fallback",
        return_value=("карта", "deepseek"),
    )
    def test_tech_card_sinlex_header_stripped_from_prompt(self, mock_fb) -> None:
        raw = f"{MARKER_SINLEX_V10} {LABEL_SINLEX_V10}\n\nСтарый анализ"
        tech_card_analysis(raw, step_data={}, log_data=[])
        prompt = mock_fb.call_args[0][0]
        self.assertIn("Старый анализ", prompt)
        self.assertNotIn(LABEL_SINLEX_V10, prompt)


if __name__ == "__main__":
    unittest.main()
