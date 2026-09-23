from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from teren_oi.analyzer import AnalysisError
from teren_oi import web


class WebIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(web.app)

    def test_ai_failure_keeps_local_comparison_and_report(self) -> None:
        with patch.dict(web.os.environ, {"OPENAI_API_KEY": "test-only-key"}):
            with patch.object(web, "analyze_changes", side_effect=AnalysisError("AI временно недоступен")):
                response = self.client.post(
                    "/api/analyze", data={"demo": "true", "use_ai": "true"}
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["removed"], 1)
        self.assertEqual(payload["summary"]["loss_count"], 1)
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


if __name__ == "__main__":
    unittest.main()
