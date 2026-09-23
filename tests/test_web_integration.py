from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from teren_oi.analyzer import AnalysisError, AnalysisResult
from teren_oi.models import Finding
from teren_oi import web


class WebIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(web.app)

    def test_ai_failure_keeps_local_comparison_and_report(self) -> None:
        with patch.dict(web.os.environ, {"OPENAI_API_KEY": "test-only-key"}):
            with patch.object(web, "analyze_with_metadata", side_effect=AnalysisError("AI временно недоступен")):
                response = self.client.post(
                    "/api/analyze", data={"demo": "true", "use_ai": "true"}
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["removed"], 1)
        self.assertEqual(payload["summary"]["loss_count"], 1)
        self.assertEqual(payload["ai"]["status"], "failed")
        self.assertEqual(payload["warnings"], [])
        self.assertIn("AI временно недоступен", payload["ai_error"])
        self.assertIn("AI-проверка не завершилась", payload["report_markdown"])

    def test_mixed_numbered_input_warns_about_omitted_text(self) -> None:
        response = self.client.post(
            "/api/analyze",
            files={
                "before_file": ("before.txt", "Заголовок\n1.1 Проверяет отчёт".encode()),
                "after_file": ("after.txt", "1.1 Проверяет отчёт".encode()),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["unchanged"], 1)
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertIn("до: 1, после: 0", payload["warnings"][0])
        self.assertIn("Охват исходных документов", payload["report_markdown"])

    def test_demo_without_ai_has_exact_move_and_server_report(self) -> None:
        with patch.object(web, "analyze_with_metadata") as model:
            payload = self.client.post("/api/analyze", data={"demo": "true"}).json()
        model.assert_not_called()
        self.assertEqual(payload["ai"]["status"], "disabled")
        self.assertEqual(payload["ai"]["coverage"]["included_clauses"], 0)
        self.assertEqual({key: payload["summary"][key] for key in ("added", "removed", "modified", "unchanged")},
                         {"added": 1, "removed": 1, "modified": 1, "unchanged": 2})
        self.assertEqual(payload["findings"][0]["origin"], "local")
        moved = next(item for item in payload["changes"] if item["before_clause_id"] == "2.4")
        self.assertEqual(moved["after_clause_id"], "2.5")
        self.assertEqual(moved["status"], "unchanged")
        group = next(unit for unit in payload["units"] if unit["name"] == "Группа обратной связи")
        self.assertEqual(group["change_ids"], [moved["id"]])
        self.assertEqual(web.REPORTS.get(payload["analysis_id"]), payload["report_markdown"])

    def test_missing_key_keeps_result(self) -> None:
        with patch.dict(web.os.environ, {"OPENAI_API_KEY": ""}), patch.object(web, "analyze_with_metadata") as model:
            response = self.client.post("/api/analyze", data={"demo": "true", "use_ai": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ai"]["status"], "unavailable")
        self.assertTrue(response.json()["changes"])
        model.assert_not_called()

    def test_identical_text_does_not_claim_ai_ran(self) -> None:
        with patch.dict(web.os.environ, {"OPENAI_API_KEY": "test-only-key"}):
            response = self.client.post("/api/analyze", data={
                "before_text": "1.1 Готовит отчёт", "after_text": "1.1 Готовит отчёт", "use_ai": "true",
            })
        self.assertEqual(response.json()["ai"]["status"], "skipped")
        self.assertIsNone(response.json()["ai"]["summary"])

    def test_verified_ai_findings_drive_summary_counts_and_report(self) -> None:
        finding = Finding(kind="другое изменение", title="Новая аналитическая роль",
                          explanation="В новой редакции добавлен анализ обращений и отзывов.",
                          confidence="средняя", citations=[{
                              "document_label": "после", "clause_id": "2.4",
                              "quote": "анализирует обращения и отзывы клиентов",
                          }])
        invalid = finding.model_copy(update={"title": "Неподтверждённый вывод", "citations": []})
        result = AnalysisResult([finding, invalid], True, {
            "total_clauses": 6, "included_clauses": 6, "omitted_clauses": 0, "truncated_clauses": 0,
        }, 0)
        with patch.dict(web.os.environ, {"OPENAI_API_KEY": "test-only-key"}), patch.object(web, "analyze_with_metadata", return_value=result):
            payload = self.client.post("/api/analyze", data={"demo": "true", "use_ai": "true"}).json()
        self.assertEqual(payload["ai"]["status"], "succeeded")
        self.assertEqual(payload["ai"]["summary_origin"], "verified_findings")
        self.assertEqual(payload["ai"]["rejected_findings"], 1)
        self.assertEqual(len(payload["ai"]["finding_ids"]), 1)
        self.assertNotIn("Неподтверждённый вывод", payload["report_markdown"])
        self.assertIn(finding.explanation, payload["report_markdown"])
        model_finding = next(item for item in payload["findings"] if item["origin"] == "ai")
        self.assertIn(model_finding["id"], payload["ai"]["finding_ids"])
        self.assertEqual(model_finding["citations"][0]["source"], "Демо: после.txt")

    def test_export_uses_immutable_snapshot_and_rejects_mixed_input(self) -> None:
        payload = self.client.post("/api/analyze", data={"demo": "true"}).json()
        with patch.object(web, "export_report", return_value=(b"file", "application/pdf", "report.pdf")) as exporter:
            response = self.client.post("/api/export", json={"analysis_id": payload["analysis_id"], "format": "pdf"})
        self.assertEqual(response.status_code, 200)
        exporter.assert_called_once_with(payload["report_markdown"], "pdf")
        invalid = self.client.post("/api/export", json={"analysis_id": payload["analysis_id"], "report_markdown": "changed", "format": "pdf"})
        self.assertEqual(invalid.status_code, 400)
        expired = self.client.post("/api/export", json={"analysis_id": "missing", "format": "pdf"})
        self.assertEqual(expired.status_code, 410)

    def test_input_errors_are_actionable(self) -> None:
        for name, content, expected in (("wrong.csv", b"1,2", "UNSUPPORTED_FORMAT"), ("empty.txt", b"", "DOCUMENT_READ_ERROR")):
            response = self.client.post("/api/analyze", files={"before_file": (name, content)}, data={"after_text": "1.1 Текст"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], expected)
        with patch.object(web, "MAX_UPLOAD_BYTES", 3):
            response = self.client.post("/api/analyze", files={"before_file": ("large.txt", b"1234")}, data={"after_text": "1.1 Текст"})
        self.assertEqual(response.status_code, 413)
        missing = self.client.post("/api/analyze", data={"before_text": " "})
        self.assertEqual(missing.json()["error"]["code"], "MISSING_INPUT")

    def test_synthetic_ids_and_duplicate_numbers_are_disclosed(self) -> None:
        prose = self.client.post("/api/analyze", data={"before_text": "Обычный текст", "after_text": "Новый текст"}).json()
        self.assertTrue(prose["coverage"]["before"]["synthetic_ids"])
        self.assertTrue(any("временные номера" in warning for warning in prose["warnings"]))
        duplicate = self.client.post("/api/analyze", data={
            "before_text": "1.1 Проверяет отчёт\n1.1 Проверяет отчёт", "after_text": "1.2 Другая функция",
        }).json()
        self.assertEqual(duplicate["summary"]["removed"], 2)
        self.assertEqual(duplicate["findings"], [])
        self.assertTrue(any("неоднознач" in warning for warning in duplicate["warnings"]))

    def test_corrupt_docx_xml_is_a_readable_input_error(self) -> None:
        original = BytesIO()
        document = Document()
        document.add_paragraph("1.1 Проверяет отчёт")
        document.save(original)
        broken = BytesIO()
        with ZipFile(original) as source, ZipFile(broken, "w") as target:
            for item in source.infolist():
                target.writestr(item.filename, b"<broken" if item.filename == "word/document.xml" else source.read(item))
        response = self.client.post("/api/analyze", files={
            "before_file": ("broken.docx", broken.getvalue()),
        }, data={"after_text": "1.1 Проверяет отчёт"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "DOCUMENT_READ_ERROR")
        self.assertIn("Проверьте", response.json()["error"]["message"])


if __name__ == "__main__":
    unittest.main()
