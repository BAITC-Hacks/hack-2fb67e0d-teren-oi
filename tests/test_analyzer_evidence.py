from __future__ import annotations

import unittest

from teren_oi.analyzer import _evidence
from teren_oi.diff import compare_documents
from teren_oi.models import Clause, SourceDocument


class AnalyzerEvidenceTests(unittest.TestCase):
    def test_retained_functions_and_repeated_ids_remain_available(self) -> None:
        old = SourceDocument(
            "before.txt",
            (
                Clause("1.1", "Проверяет качество", "before.txt", "line 1"),
                Clause("1.1", "Готовит отчёт", "before.txt", "line 2"),
            ),
        )
        new = SourceDocument(
            "after.txt",
            (
                Clause("1.1", "Проверяет качество", "after.txt", "line 1"),
                Clause("1.1", "Готовит итоговый отчёт", "after.txt", "line 2"),
                Clause("1.2", "Повторно проверяет качество", "after.txt", "line 3"),
            ),
        )

        evidence = _evidence(compare_documents(old, new))
        after_texts = [text for _, label, _, text in evidence if label == "после"]

        self.assertIn("Проверяет качество", after_texts)
        self.assertIn("Готовит итоговый отчёт", after_texts)
        self.assertIn("Повторно проверяет качество", after_texts)


if __name__ == "__main__":
    unittest.main()
