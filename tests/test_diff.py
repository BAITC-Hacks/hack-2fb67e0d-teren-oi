from __future__ import annotations

import unittest
from collections import Counter

from teren_oi.diff import compare_documents
from teren_oi.models import Clause, SourceDocument


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


if __name__ == "__main__":
    unittest.main()
