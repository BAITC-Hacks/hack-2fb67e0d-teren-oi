from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Hashable
from typing import TypeVar

from .models import Change, Comparison, SourceDocument

Key = TypeVar("Key", bound=Hashable)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _positions(values: list[Key], remaining: set[int]) -> dict[Key, list[int]]:
    """Group document positions, retaining every occurrence and its original order."""
    groups: defaultdict[Key, list[int]] = defaultdict(list)
    for index, value in enumerate(values):
        if index in remaining:
            groups[value].append(index)
    return groups


def compare_documents(old: SourceDocument, new: SourceDocument) -> Comparison:
    """Match exact unique text first, then exact text within an ID, then ID occurrence.

    Cross-ID matches require nonempty text occurring exactly once in each complete
    document. Repeated text cannot establish a unique move, even after other clauses
    have been matched. Residual duplicate IDs are paired in document order; that is
    a structural comparison, not evidence of semantic or organizational continuity.
    """
    old_remaining = set(range(len(old.clauses)))
    new_remaining = set(range(len(new.clauses)))
    old_texts = [normalize(clause.text) for clause in old.clauses]
    new_texts = [normalize(clause.text) for clause in new.clauses]
    modified: list[Change] = []
    unchanged: list[Change] = []

    def pair(old_index: int, new_index: int) -> None:
        before, after = old.clauses[old_index], new.clauses[new_index]
        target = unchanged if old_texts[old_index] == new_texts[new_index] else modified
        target.append(Change(after.clause_id, before, after))
        old_remaining.remove(old_index)
        new_remaining.remove(new_index)

    # Reserve every unambiguous exact match before an ID match can consume it.
    old_by_text = _positions(old_texts, old_remaining)
    new_by_text = _positions(new_texts, new_remaining)
    for text, old_positions in old_by_text.items():
        new_positions = new_by_text.get(text, [])
        if text and len(old_positions) == len(new_positions) == 1:
            pair(old_positions[0], new_positions[0])

    # Same-ID repeated text remains comparable without inventing a cross-ID move.
    old_exact = _positions(
        [(clause.clause_id, text) for clause, text in zip(old.clauses, old_texts)],
        old_remaining,
    )
    new_exact = _positions(
        [(clause.clause_id, text) for clause, text in zip(new.clauses, new_texts)],
        new_remaining,
    )
    for key, old_positions in old_exact.items():
        for old_index, new_index in zip(old_positions, new_exact.get(key, [])):
            pair(old_index, new_index)

    old_by_id = _positions([clause.clause_id for clause in old.clauses], old_remaining)
    new_by_id = _positions([clause.clause_id for clause in new.clauses], new_remaining)
    for clause_id, old_positions in old_by_id.items():
        for old_index, new_index in zip(old_positions, new_by_id.get(clause_id, [])):
            pair(old_index, new_index)

    added = [Change(new.clauses[i].clause_id, None, new.clauses[i])
             for i in sorted(new_remaining)]
    removed = [Change(old.clauses[i].clause_id, old.clauses[i], None)
               for i in sorted(old_remaining)]

    def key_order(item: Change) -> list[str | int]:
        return [int(part) if part.isdigit() else part
                for part in re.split(r"(\d+)", item.clause_id)]

    return Comparison(
        old, new,
        tuple(sorted(added, key=key_order)), tuple(sorted(removed, key=key_order)),
        tuple(sorted(modified, key=key_order)), tuple(sorted(unchanged, key=key_order)),
    )
