import unittest
from fastapi.testclient import TestClient
from teren_oi import web

class DocumentBundleTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web.app)

    def test_duplicate_clause_numbers_keep_sources_and_exports(self):
        files = [("before_files", ("audit.txt", "1.1 Готовит отчёт.".encode())),
                 ("before_files", ("network.txt", "1.1 Проверяет сеть.".encode())),
                 ("after_files", ("network.txt", "1.1 Проверяет сеть ежедневно.".encode())),
                 ("after_files", ("audit.txt", "1.1 Готовит отчёт.".encode()))]
        response = self.client.post("/api/analyze", files=files)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["modified"], 1)
        self.assertEqual(data["summary"]["unchanged"], 1)
        self.assertEqual(data["coverage"]["before"]["clauses"], 2)
        changed = next(c for c in data["changes"] if c["status"] == "modified")
        self.assertIn("network.txt", changed["before_source"])
        self.assertIn("network.txt", changed["after_source"])
        self.assertIn("audit.txt", data["report_markdown"])
        for fmt in ("pdf", "docx"):
            self.assertEqual(self.client.post("/api/export", json={"analysis_id": data["analysis_id"], "format": fmt}).status_code, 200)

    def test_invalid_bundle_rejected(self):
        one = ("same.txt", b"1.1 Test")
        for files in ([one, one], [(str(i)+".txt", b"1.1 Test") for i in range(9)]):
            response = self.client.post("/api/analyze", files=[("before_files", f) for f in files], data={"after_text": "1.1 After"})
            self.assertEqual(response.status_code, 400)

    def test_same_number_different_files_not_paired(self):
        response = self.client.post("/api/analyze", files=[
            ("before_files", ("a.txt", b"1.1 Apples")),
            ("before_files", ("b.txt", b"1.1 Bananas")),
            ("after_files", ("c.txt", b"1.1 Cherries"))])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["modified"], 0)
        self.assertEqual(response.json()["summary"]["removed"], 2)
