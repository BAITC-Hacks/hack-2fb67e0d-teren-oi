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

    def analyze(self, structured, complete=True):
        result = AnalysisResult([], True, {"total_clauses": 4, "included_clauses": 4,
            "omitted_clauses": 0, "truncated_clauses": 0, "before_complete": complete, "after_complete": complete},
            structured=structured)
        with patch.dict(web.os.environ, {"OPENAI_API_KEY": "test-only"}), patch.object(web, "analyze_with_metadata", return_value=result) as analyze:
            response = self.client.post("/api/analyze", data={"before_text": BEFORE, "after_text": AFTER, "use_ai": "true"})
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
        self.assertEqual(result["summary"]["loss_count"], 0)
        self.assertEqual(result["function_mappings"][0]["status"], "retained")
        self.assertIn("location", result["function_mappings"][0]["citations"][0])
        self.assertNotIn("Непроверенное резюме", result["ai_summary"])
        self.assertIn("сопоставлений функций: 1", result["ai_summary"])
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


if __name__ == "__main__":
    unittest.main()
