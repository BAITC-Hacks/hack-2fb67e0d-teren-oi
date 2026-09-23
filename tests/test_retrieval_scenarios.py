from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from teren_oi import analyzer
from teren_oi.diff import compare_documents
from teren_oi.models import (
    AnalysisResponse,
    Citation,
    Clause,
    Comparison,
    FunctionMapping,
    SourceDocument,
)


def _document(name: str, clauses: list[tuple[str, str]]) -> SourceDocument:
    return SourceDocument(name, tuple(
        Clause(clause_id, body, name, f"paragraph {index}")
        for index, (clause_id, body) in enumerate(clauses)
    ))


def _comparison(old: list[tuple[str, str]], new: list[tuple[str, str]]) -> Comparison:
    return compare_documents(_document("before", old), _document("after", new))


class RetrievalScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        guard = patch.object(analyzer, "OpenAI", side_effect=AssertionError("Unmocked API call"))
        guard.start()
        self.addCleanup(guard.stop)

    def _neighbors(
        self, comparison: Comparison,
    ) -> tuple[list[analyzer._Evidence], dict[int, list[tuple[int, float]]]]:
        candidates = analyzer._candidates(comparison)
        cross, _, _ = analyzer._candidate_retrieval(
            candidates, [analyzer._features(item[3]) for item in candidates],
        )
        return candidates, cross

    def _assert_edge(
        self, candidates: list[analyzer._Evidence], edges: dict[int, list[tuple[int, float]]],
        source: tuple[str, str], target: tuple[str, str],
    ) -> None:
        index = next(i for i, item in enumerate(candidates) if item[1:3] == source)
        self.assertIn(target, [candidates[i][1:3] for i, _ in edges.get(index, [])])
        self.assertLessEqual(len(edges[index]), analyzer._CANDIDATES_PER_CLAUSE)

    def test_reworded_owner_transfer_is_retrieved_and_can_validate_as_reassigned(self) -> None:
        old = "Department Alpha coordinates cryptographic key rotation and exception approvals."
        new = ("Department Beta reviews exception approvals "
               "and coordinates cryptographic key rotation.")
        comparison = _comparison([("7.1.a", old)], [("12.4.b", new)])
        candidates, cross = self._neighbors(comparison)
        self._assert_edge(candidates, cross, ("до", "7.1.a"), ("после", "12.4.b"))
        self._assert_edge(candidates, cross, ("после", "12.4.b"), ("до", "7.1.a"))
        response = AnalysisResponse(function_mappings=[FunctionMapping(
            old_function="Coordinate cryptographic key rotation and exception approvals",
            new_function="Coordinate cryptographic key rotation and review exception approvals",
            old_department="Department Alpha", new_department="Department Beta",
            status="reassigned", confidence="medium", citations=[
                Citation(document_label="до", clause_id="7.1.a", quote=old),
                Citation(document_label="после", clause_id="12.4.b", quote=new),
            ],
        )])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder"}), \
                patch.object(analyzer, "OpenAI") as client:
            client.return_value.responses.parse.return_value = SimpleNamespace(
                output_parsed=response,
            )
            result = analyzer.analyze_with_metadata(comparison, "test-model")
        self.assertIsNotNone(result.structured)
        assert result.structured is not None
        self.assertEqual(result.structured.function_mappings, response.function_mappings)
        self.assertEqual(result.structured.findings, [])
        request = client.return_value.responses.parse.call_args.kwargs
        payload = json.loads(request["input"][1]["content"])
        self.assertEqual({(item["document_label"], item["clause_id"], item["text"])
                          for item in payload["clauses"]},
                         {("до", "7.1.a", old), ("после", "12.4.b", new)})
        client.return_value.responses.parse.assert_called_once()

    def test_split_responsibility_retrieves_both_new_candidates(self) -> None:
        comparison = _comparison(
            [("7.2", "Coordinates satellite telemetry anomaly diagnosis and orbital drift "
              "correction scheduling.")],
            [("12.1", "Diagnoses anomalies in satellite telemetry."),
             ("12.2", "Schedules correction of orbital drift."),
             ("12.3", "Approves warehouse refrigeration invoices.")],
        )
        candidates, cross = self._neighbors(comparison)
        for new_id in ("12.1", "12.2"):
            self._assert_edge(candidates, cross, ("до", "7.2"), ("после", new_id))
            self._assert_edge(candidates, cross, ("после", new_id), ("до", "7.2"))
        _, allowed = analyzer._payload_evidence(comparison)
        self.assertTrue({("до", "7.2"), ("после", "12.1"), ("после", "12.2")}
                        <= {(label, clause_id) for label, clause_id, _ in allowed})

    def test_merged_responsibility_retrieves_both_old_candidates(self) -> None:
        comparison = _comparison(
            [("2.1", "Diagnoses anomalies in satellite telemetry."),
             ("2.2", "Schedules correction of orbital drift."),
             ("2.3", "Approves warehouse refrigeration invoices.")],
            [("9.8", "Coordinates satellite telemetry anomaly diagnosis and orbital drift "
              "correction scheduling.")],
        )
        candidates, cross = self._neighbors(comparison)
        for old_id in ("2.1", "2.2"):
            self._assert_edge(candidates, cross, ("после", "9.8"), ("до", old_id))
            self._assert_edge(candidates, cross, ("до", old_id), ("после", "9.8"))
        _, allowed = analyzer._payload_evidence(comparison)
        self.assertTrue({("до", "2.1"), ("до", "2.2"), ("после", "9.8")}
                        <= {(label, clause_id) for label, clause_id, _ in allowed})

    def test_distinctive_terms_outrank_generic_work_vocabulary_in_both_languages(self) -> None:
        examples = [
            ("Department control organization work: coordinates satellite telemetry anomalies.",
             "Department control organization work: approves warehouse refrigeration invoices.",
             "Reviews anomalies from satellite telemetry."),
            ("Подразделение контролирует организацию работы: анализирует спутниковые сигналы.",
             "Подразделение контролирует организацию работы: проверяет складские накладные.",
             "Проверяет спутниковые сигналы при отклонениях."),
        ]
        for old, generic, distinctive in examples:
            with self.subTest(old=old):
                comparison = _comparison([("1.1", old)],
                                         [("2.1", generic), ("2.2", distinctive)])
                candidates, cross = self._neighbors(comparison)
                index = next(i for i, item in enumerate(candidates) if item[1] == "до")
                neighbors = [candidates[i][2] for i, _ in cross[index]]
                self.assertEqual(neighbors[0], "2.2")
                self.assertNotIn("2.1", neighbors)

    def test_large_mixed_fixture_sends_relevant_pairs_and_reports_actual_coverage(self) -> None:
        # The distinctive clauses are late in both source order and ID order.
        # Escapes and long filler also exercise real serialized and truncated costs.
        filler_topics = (
            "kitchen pantry inventory forms", "warehouse refrigeration maintenance receipts",
            "vehicle mileage parking permits", "visitor badge reception schedules",
            "training attendance certificate registers", "office furniture warranty records",
        )
        old = [(f"1.{i}", ('Records routine "ledger" C:\\archive\\daily.\n'
                           + filler_topics[i % len(filler_topics)] + ". ") * 30)
               for i in range(460)]
        new = [(f"1.{i}", ('Updates routine "ledger" C:\\archive\\daily.\n'
                           + filler_topics[i % len(filler_topics)] + ". ") * 30)
               for i in range(460)]
        moved = "Organizes cross-functional interaction between the project team and owner."
        old_owner = ("Department Alpha coordinates cryptographic key rotation schedules "
                     "and exception approvals.")
        new_owner = ("Department Beta reviews exception approvals and coordinates schedules "
                     "for cryptographic key rotation.")
        unmatched = "Archives historical calibration certificates for tidal instruments."
        old.extend([
            ("80.1.a", "Department Alpha"), ("80.1.b", "Department Beta"),
            ("90.1.g", moved), ("90.2.a", old_owner), ("90.8.z", unmatched),
        ])
        new.extend([
            ("80.1.a", "Department Gamma"), ("80.1.b", "Department Delta"),
            ("80.1.c", "Department Alpha"), ("80.1.d", "Department Beta"),
            ("90.3.g", moved), ("91.2.b", new_owner),
            ("95.1.a", "Department Gamma monitors satellite telemetry anomalies "
             "and orbital drift."),
            ("95.2.b", "Department Delta monitors orbital drift "
             "and satellite telemetry anomalies."),
        ])
        comparison = _comparison(old, new)
        candidates = analyzer._candidates(comparison)
        cross, duplicates, _ = analyzer._candidate_retrieval(
            candidates, [analyzer._features(item[3]) for item in candidates],
        )
        self._assert_edge(candidates, cross, ("до", "90.2.a"), ("после", "91.2.b"))
        self._assert_edge(candidates, cross, ("после", "91.2.b"), ("до", "90.2.a"))
        self._assert_edge(candidates, duplicates, ("после", "95.1.a"), ("после", "95.2.b"))
        self._assert_edge(candidates, duplicates, ("после", "95.2.b"), ("после", "95.1.a"))
        unmatched_index = next(i for i, item in enumerate(candidates)
                               if item[1:3] == ("до", "90.8.z"))
        self.assertEqual(cross.get(unmatched_index, []), [])

        # Empty model output isolates retrieval; it must not create automatic
        # lost/created assertions from missing neighbors in this partial sample.
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder"}), \
                patch.object(analyzer, "OpenAI") as client:
            client.return_value.responses.parse.return_value = SimpleNamespace(
                output_parsed=AnalysisResponse(),
            )
            result = analyzer.analyze_with_metadata(comparison, "test-model")
        serialized = client.return_value.responses.parse.call_args.kwargs["input"][1]["content"]
        payload = json.loads(serialized)
        sent = payload["clauses"]
        references = {(item["document_label"], item["clause_id"]) for item in sent}
        references.update((alias["document_label"], alias["clause_id"])
                          for item in sent for alias in item["aliases"])
        important = {
            ("до", "80.1.a"), ("до", "80.1.b"),
            ("после", "80.1.a"), ("после", "80.1.b"),
            ("после", "80.1.c"), ("после", "80.1.d"),
            ("до", "90.1.g"), ("после", "90.3.g"),
            ("до", "90.2.a"), ("после", "91.2.b"), ("до", "90.8.z"),
            ("после", "95.1.a"), ("после", "95.2.b"),
        }
        self.assertTrue(important <= references, important - references)
        source_bodies = {(label, clause.clause_id): clause.text
                         for label, document in (("до", comparison.old_document),
                                                 ("после", comparison.new_document))
                         for clause in document.clauses}
        truncated = 0
        for item in sent:
            original = source_bodies[(item["document_label"], item["clause_id"])]
            self.assertEqual(item["text"], original[:analyzer._MAX_CLAUSE_CHARS])
            truncated += len(original) > len(item["text"])
            for alias in item["aliases"]:
                self.assertEqual(source_bodies[(alias["document_label"], alias["clause_id"])],
                                 original)
        self.assertGreater(truncated, 0)
        self.assertLessEqual(len(serialized), analyzer._MAX_EVIDENCE_CHARS)
        self.assertEqual(payload["context_complete"], {"до": False, "после": False})
        self.assertEqual(result.coverage, {
            "total_clauses": len(candidates), "included_clauses": len(sent),
            "omitted_clauses": len(candidates) - len(sent), "truncated_clauses": truncated,
            "before_complete": False, "after_complete": False,
        })
        self.assertGreater(result.coverage["omitted_clauses"], 0)
        self.assertEqual(analyzer.evidence_coverage(comparison, sent=True), result.coverage)
        self.assertIsNotNone(result.structured)
        assert result.structured is not None
        self.assertEqual(result.structured.function_mappings, [])
        self.assertEqual(result.structured.department_changes, [])
        self.assertEqual(result.structured.findings, [])
        client.assert_called_once_with(timeout=60.0, max_retries=0)
        client.return_value.responses.parse.assert_called_once()

    def test_missing_parsed_response_fails_safely_without_exposing_provider_text(self) -> None:
        comparison = _comparison([("1", "Maintains incident escalation records.")],
                                 [("2", "Reviews incident escalation records.")])
        secret_response = "Sensitive provider body: confidential document and secret key"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder"}), \
                patch.object(analyzer, "OpenAI") as client:
            client.return_value.responses.parse.return_value = SimpleNamespace(
                output_parsed=None, output_text=secret_response,
            )
            with self.assertRaises(analyzer.AnalysisError) as raised:
                analyzer.analyze_with_metadata(comparison, "test-model")
        self.assertEqual(str(raised.exception), "Модель не вернула структурированный ответ.")
        self.assertNotIn(secret_response, str(raised.exception))
        self.assertEqual(len(comparison.removed), 1)
        self.assertEqual(len(comparison.added), 1)
        client.return_value.responses.parse.assert_called_once()


if __name__ == "__main__":
    unittest.main()
