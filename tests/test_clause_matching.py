from __future__ import annotations

import unittest
from collections import Counter

from teren_oi.diff import compare_documents, validate_analysis_response
from teren_oi.models import AnalysisResponse, Citation, Clause, Finding, SourceDocument


def document(name: str, rows: list[tuple[str, str]]) -> SourceDocument:
    return SourceDocument(
        name,
        tuple(Clause(clause_id, text, name, f"line {index}")
              for index, (clause_id, text) in enumerate(rows, start=1)),
    )


class DiffTests(unittest.TestCase):
    def test_unique_renumbered_text_preserves_both_original_identifiers(self) -> None:
        old = document("old.txt", [("1.1", "Проводит   аудит")])
        new = document("new.txt", [("4.2", "проводит аудит")])

        result = compare_documents(old, new)

        self.assertEqual(len(result.unchanged), 1)
        self.assertEqual(result.unchanged[0].before.clause_id, "1.1")
        self.assertEqual(result.unchanged[0].after.clause_id, "4.2")
        self.assertEqual(result.unchanged[0].clause_id, "4.2")
        self.assertFalse(result.added or result.removed or result.modified)

    def test_swapped_numbering_reserves_all_exact_matches_before_pairing_ids(self) -> None:
        old = document("old.txt", [("1", "Аудит"), ("2", "Контроль")])
        new = document("new.txt", [("1", "Контроль"), ("2", "Аудит")])

        result = compare_documents(old, new)

        self.assertEqual(len(result.unchanged), 2)
        self.assertFalse(result.added or result.removed or result.modified)
        self.assertEqual(
            {(change.before.clause_id, change.after.clause_id) for change in result.unchanged},
            {("1", "2"), ("2", "1")},
        )

    def test_duplicate_ids_reordered_with_repeated_text_match_exact_content_first(self) -> None:
        old = document("old.txt", [("1", "Аудит"), ("1", "Контроль"), ("1", "Аудит")])
        new = document("new.txt", [("1", "Контроль"), ("1", "Аудит"), ("1", "Аудит")])

        result = compare_documents(old, new)

        self.assertEqual(len(result.unchanged), 3)
        self.assertFalse(result.added or result.removed or result.modified)

    def test_repeated_text_does_not_infer_ambiguous_cross_id_matches(self) -> None:
        old = document("old.txt", [("1", "Аудит"), ("2", "Аудит")])
        new = document("new.txt", [("3", "Аудит"), ("4", "Аудит")])

        result = compare_documents(old, new)

        self.assertEqual(len(result.removed), 2)
        self.assertEqual(len(result.added), 2)
        self.assertFalse(result.unchanged or result.modified)

    def test_same_id_anchor_does_not_make_repeated_text_globally_unique(self) -> None:
        old = document("old.txt", [("1", "Аудит"), ("2", "Аудит")])
        new = document("new.txt", [("1", "Аудит"), ("3", "Аудит")])

        result = compare_documents(old, new)

        self.assertEqual(len(result.unchanged), 1)
        self.assertEqual(result.removed[0].clause_id, "2")
        self.assertEqual(result.added[0].clause_id, "3")

    def test_duplicate_ids_keep_exact_match_then_pair_remaining_occurrences(self) -> None:
        old = document("old.txt", [("1", "Аудит"), ("1", "Контроль"), ("1", "Архив")])
        new = document("new.txt", [("1", "Контроль"), ("1", "Новый аудит")])

        result = compare_documents(old, new)

        self.assertEqual(result.unchanged[0].before.text, "Контроль")
        self.assertEqual(result.modified[0].before.text, "Аудит")
        self.assertEqual(result.modified[0].after.text, "Новый аудит")
        self.assertEqual(result.removed[0].before.text, "Архив")

    def test_preserves_every_occurrence_without_synthetic_id_collisions(self) -> None:
        old = document("old.txt", [("1", "А"), ("1", "Б"), ("1#2", "В"), ("2", "Г")])
        new = document("new.txt", [("1", "Б"), ("3", "А"), ("1#2", "В2"), ("4", "Д")])

        result = compare_documents(old, new)
        changes = result.added + result.removed + result.modified + result.unchanged

        self.assertEqual(
            Counter(id(change.before) for change in changes if change.before is not None),
            Counter(id(clause) for clause in old.clauses),
        )
        self.assertEqual(
            Counter(id(change.after) for change in changes if change.after is not None),
            Counter(id(clause) for clause in new.clauses),
        )

    def test_empty_text_does_not_prove_renumbering(self) -> None:
        result = compare_documents(
            document("old.txt", [("1", "")]), document("new.txt", [("2", " ")]),
        )

        self.assertEqual(len(result.removed), 1)
        self.assertEqual(len(result.added), 1)
        self.assertFalse(result.unchanged)


class MergedEvidenceValidationTests(unittest.TestCase):
    def validate_finding(self, comparison, kind, citations):
        finding = Finding(
            kind=kind, title="Проверка", explanation="Проверьте источники",
            confidence="low", citations=citations,
        )
        return validate_analysis_response(
            AnalysisResponse(summary="Исходная сводка", department_changes=[],
                             function_mappings=[], findings=[finding]),
            comparison, before_complete=True, after_complete=True,
        )

    def test_ambiguous_duplicate_id_quote_is_not_a_verified_source(self) -> None:
        comparison = compare_documents(
            document("old.txt", [("1", "Отдел А проводит аудит"),
                                 ("1", "Отдел Б проводит аудит")]),
            document("new.txt", []),
        )

        result = self.validate_finding(comparison, "possible_loss", [
            Citation(document_label="до", clause_id="1", quote="проводит аудит"),
        ])

        self.assertEqual(result.findings, [])

    def test_duplicate_id_can_be_disambiguated_by_exact_quote(self) -> None:
        comparison = compare_documents(
            document("old.txt", [("1", "Отдел А проводит аудит"),
                                 ("1", "Отдел Б проводит аудит")]),
            document("new.txt", []),
        )

        result = self.validate_finding(comparison, "possible_loss", [
            Citation(document_label="до", clause_id="1", quote="Отдел А проводит аудит"),
        ])

        self.assertEqual(len(result.findings), 1)

    def test_two_excerpts_from_one_point_do_not_establish_two_sources(self) -> None:
        comparison = compare_documents(
            document("old.txt", []),
            document("new.txt", [("1", "Отдел А проводит аудит и контроль")]),
        )

        for kind in ("possible_duplication", "possible_conflict"):
            with self.subTest(kind=kind):
                result = self.validate_finding(comparison, kind, [
                    Citation(document_label="после", clause_id="1", quote="проводит аудит"),
                    Citation(document_label="после", clause_id="1", quote="и контроль"),
                ])
                self.assertEqual(result.findings, [])

    def test_two_distinct_occurrences_with_same_id_can_supply_two_sources(self) -> None:
        comparison = compare_documents(
            document("old.txt", []),
            document("new.txt", [("1", "Отдел А проводит аудит"),
                                 ("1", "Отдел Б проводит аудит")]),
        )

        result = self.validate_finding(comparison, "possible_duplication", [
            Citation(document_label="после", clause_id="1", quote="Отдел А проводит аудит"),
            Citation(document_label="после", clause_id="1", quote="Отдел Б проводит аудит"),
        ])

        self.assertEqual(len(result.findings), 1)

    def test_legacy_general_findings_are_not_reclassified_as_conflicts(self) -> None:
        comparison = compare_documents(
            document("old.txt", []), document("new.txt", [("1", "Контролирует качество")]),
        )

        for kind in ("перераспределение ответственности", "другое изменение"):
            with self.subTest(kind=kind):
                result = self.validate_finding(comparison, kind, [
                    Citation(document_label="после", clause_id="1", quote="Контролирует качество"),
                ])
                self.assertEqual(result.findings[0].kind, kind)


if __name__ == "__main__":
    unittest.main()
