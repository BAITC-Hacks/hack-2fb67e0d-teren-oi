from io import BytesIO
import unittest
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from teren_oi import web
from teren_oi.analyzer import AnalysisResult
from teren_oi.models import AnalysisResponse, DepartmentChange, FunctionMapping


BEFORE = "3.4 Проверка\nа) Департамент ДНМ: проверяет качество сети.\n3.5 Отдел контроля: готовит отчёт."
AFTER = "3.4 Проверка\nв) Департамент ДНМ: контролирует качество сети."


def structured_result():
    citations = [
        {"document_label": "до", "clause_id": "3.4.а", "quote": "Департамент ДНМ: проверяет качество сети."},
        {"document_label": "после", "clause_id": "3.4.в", "quote": "Департамент ДНМ: контролирует качество сети."},
    ]
    return AnalysisResponse(
        summary="Непроверенное резюме не должно отображаться",
        department_changes=[DepartmentChange(name_before="Департамент ДНМ", name_after="Департамент ДНМ",
                                             status="retained", citations=citations)],
        function_mappings=[FunctionMapping(old_function="Проверять качество сети", new_function="Контролировать качество сети",
                                          old_department="Департамент ДНМ", new_department="Департамент ДНМ",
                                          status="retained", confidence="high", citations=citations)],
    )


class SemanticIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web.app)

    def analyze(self, structured, complete=True, before=BEFORE, after=AFTER):
        result = AnalysisResult([], True, {"total_clauses": 4, "included_clauses": 4,
            "omitted_clauses": 0, "truncated_clauses": 0, "before_complete": complete, "after_complete": complete},
            structured=structured)
        with patch.dict(web.os.environ, {"OPENAI_API_KEY": "test-only"}), patch.object(web, "analyze_with_metadata", return_value=result) as analyze:
            response = self.client.post(
                "/api/analyze",
                data={"before_text": before, "after_text": after, "use_ai": "true"},
            )
        self.assertEqual(response.status_code, 200)
        analyze.assert_called_once()
        return response.json()

    def test_retained_department_and_mapping_leave_exact_diff_unchanged(self):
        local = self.client.post("/api/analyze", data={"before_text": BEFORE, "after_text": AFTER}).json()
        result = self.analyze(structured_result())
        self.assertEqual(result["changes"], local["changes"])
        unit = next(unit for unit in result["units"] if unit["name"] == "Департамент ДНМ")
        self.assertEqual(unit["status"], "retained")
        self.assertEqual(unit["origin"], "ai")
        self.assertEqual(len(unit["change_ids"]), 2)
        self.assertTrue(result["summary"]["removed"])
        self.assertEqual(result["summary"]["ai_loss_count"], 0)
        losses = [
            finding for finding in result["findings"]
            if finding["kind"] == "потенциальная потеря функции"
        ]
        self.assertEqual(len(losses), 1)
        self.assertEqual(losses[0]["citations"][0]["clause_id"], "3.5")
        self.assertEqual(result["summary"]["loss_count"], 0)
        self.assertEqual(result["function_mappings"][0]["status"], "retained")
        self.assertIn("location", result["function_mappings"][0]["citations"][0])
        self.assertNotIn("Непроверенное резюме", result["ai_summary"])
        self.assertIn("сопоставлений функций: 1", result["ai_summary"])
        self.assertIn("Проверять качество сети", result["report_markdown"])
        self.assertIn("Контролировать качество сети", result["report_markdown"])
        self.assertIn("3.4.а", result["report_markdown"])
        self.assertIn("3.4.в", result["report_markdown"])
        local_section = result["report_markdown"].split("## Local Signals", 1)[1].split(
            "## Potential Duplications", 1
        )[0]
        self.assertIn("3.5", local_section)
        self.assertNotIn("3.4.а", local_section)
        report = self.client.post("/api/export", json={"analysis_id": result["analysis_id"], "format": "docx"})
        self.assertEqual(report.status_code, 200)
        text = "\n".join(p.text for p in Document(BytesIO(report.content)).paragraphs)
        self.assertIn("Контролировать качество сети", text)
        self.assertIn("3.4.в", text)

    def test_no_ai_exposes_empty_sections_and_unchecked_metrics(self):
        result = self.client.post("/api/analyze", data={"demo": "true"}).json()
        self.assertEqual(result["department_changes"], [])
        self.assertEqual(result["function_mappings"], [])
        self.assertIsNone(result["ai_summary"])
        self.assertIsNone(result["summary"]["ai_loss_count"])
        self.assertIn("не проверено", result["report_markdown"])

    def test_invalid_evidence_cannot_override_local_units(self):
        structured = structured_result()
        structured.department_changes[0].citations[0].quote = "Выдуманная цитата"
        structured.function_mappings[0].citations[0].quote = "Выдуманная цитата"
        result = self.analyze(structured)
        self.assertEqual(result["department_changes"], [])
        self.assertEqual(result["function_mappings"], [])
        self.assertTrue(all(unit["origin"] == "local" for unit in result["units"]))
        losses = [
            finding for finding in result["findings"]
            if finding["kind"] == "потенциальная потеря функции"
        ]
        self.assertTrue(any(item["citations"][0]["clause_id"] == "3.4.а" for item in losses))
        self.assertEqual(result["summary"]["loss_count"], 0)

    def test_conflicting_department_assessments_keep_local_status(self):
        structured = structured_result()
        structured.department_changes.append(structured.department_changes[0].model_copy(update={"status": "reorganized"}))
        result = self.analyze(structured)
        unit = next(unit for unit in result["units"] if unit["name"] == "Департамент ДНМ")
        self.assertEqual(unit["origin"], "local")

    def test_incomplete_context_rejects_lost_mapping(self):
        structured = structured_result()
        structured.function_mappings = [structured.function_mappings[0].model_copy(update={
            "status": "lost", "new_function": None, "citations": structured.function_mappings[0].citations[:1]})]
        result = self.analyze(structured, complete=False)
        self.assertEqual(result["function_mappings"], [])

    def test_duplicate_clause_ids_suppress_only_the_resolved_occurrence(self):
        before = (
            "1.1 Отдел Альфа: выполняет проверку сети.\n"
            "1.1 Отдел Бета: готовит ежемесячный отчёт."
        )
        after = "2.1 Отдел Альфа: продолжает проверку сети."
        structured = AnalysisResponse(function_mappings=[FunctionMapping(
            old_function="Выполнять проверку сети",
            new_function="Продолжать проверку сети",
            old_department="Отдел Альфа",
            new_department="Отдел Альфа",
            status="reassigned",
            confidence="high",
            citations=[
                {"document_label": "до", "clause_id": "1.1", "quote": "Отдел Альфа: выполняет проверку сети."},
                {"document_label": "после", "clause_id": "2.1", "quote": "Отдел Альфа: продолжает проверку сети."},
            ],
        )])

        result = self.analyze(structured, before=before, after=after)

        losses = [
            finding for finding in result["findings"]
            if finding["kind"] == "потенциальная потеря функции"
        ]
        self.assertEqual(len(losses), 1)
        self.assertIn("Отдел Бета", losses[0]["citations"][0]["quote"])
        self.assertNotIn("Отдел Альфа", losses[0]["citations"][0]["quote"])
        self.assertEqual(result["summary"]["removed"], 2)
        self.assertEqual(result["summary"]["loss_count"], 0)

    def test_lost_mapping_does_not_suppress_local_loss(self):
        structured = structured_result()
        structured.function_mappings = [structured.function_mappings[0].model_copy(update={
            "status": "lost",
            "new_function": None,
            "citations": structured.function_mappings[0].citations[:1],
        })]

        result = self.analyze(structured)

        losses = [
            finding for finding in result["findings"]
            if finding["kind"] == "потенциальная потеря функции"
        ]
        self.assertTrue(any(item["citations"][0]["clause_id"] == "3.4.а" for item in losses))
        self.assertEqual(result["summary"]["loss_count"], 0)

    def test_changed_mapping_suppresses_the_resolved_local_signal(self):
        structured = structured_result()
        structured.function_mappings = [structured.function_mappings[0].model_copy(update={
            "status": "changed",
        })]

        result = self.analyze(structured)

        loss_ids = {
            finding["citations"][0]["clause_id"]
            for finding in result["findings"]
            if finding["kind"] == "потенциальная потеря функции"
        }
        self.assertEqual(loss_ids, {"3.5"})

    def test_fabricated_mapping_citation_cannot_suppress_local_signal(self):
        structured = structured_result()
        structured.department_changes = []
        structured.function_mappings[0].citations[0].quote = "Выдуманная функция"

        result = self.analyze(structured)

        self.assertEqual(result["function_mappings"], [])
        loss_ids = {
            finding["citations"][0]["clause_id"]
            for finding in result["findings"]
            if finding["kind"] == "потенциальная потеря функции"
        }
        self.assertEqual(loss_ids, {"3.4.а", "3.5"})

    def test_ambiguous_mapping_citation_cannot_suppress_local_signals(self):
        before = (
            "1.1 Отдел Альфа выполняет общую проверку.\n"
            "1.1 Отдел Бета выполняет общую отчётность."
        )
        after = "2.1 Отдел Альфа продолжает проверку."
        structured = AnalysisResponse(function_mappings=[FunctionMapping(
            old_function="Выполнять общую функцию",
            new_function="Продолжать проверку",
            status="changed",
            confidence="medium",
            citations=[
                {"document_label": "до", "clause_id": "1.1", "quote": "выполняет общую"},
                {"document_label": "после", "clause_id": "2.1", "quote": "продолжает проверку"},
            ],
        )])

        local = self.client.post(
            "/api/analyze", data={"before_text": before, "after_text": after}
        ).json()
        result = self.analyze(structured, before=before, after=after)

        self.assertEqual(result["changes"], local["changes"])
        self.assertEqual(result["function_mappings"], [])
        losses = [
            finding for finding in result["findings"]
            if finding["kind"] == "потенциальная потеря функции"
        ]
        self.assertEqual(len(losses), 2)


if __name__ == "__main__":
    unittest.main()
