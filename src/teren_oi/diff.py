from __future__ import annotations

import re
from collections import defaultdict

from .models import Change, Comparison, SourceDocument


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _clause_index(document: SourceDocument) -> dict[str, str]:
    """Index clauses by stable id; duplicate IDs are kept distinct instead of silently lost."""
    totals: defaultdict[str, int] = defaultdict(int)
    index: dict[str, str] = {}
    for clause in document.clauses:
        totals[clause.clause_id] += 1
        key = clause.clause_id if totals[clause.clause_id] == 1 else f"{clause.clause_id}#{totals[clause.clause_id]}"
        index[key] = clause.clause_id
    return index


def compare_documents(old: SourceDocument, new: SourceDocument) -> Comparison:
    old_index, new_index = _clause_index(old), _clause_index(new)
    old_by_key = {key: clause for clause, (key, _) in zip(old.clauses, old_index.items())}
    new_by_key = {key: clause for clause, (key, _) in zip(new.clauses, new_index.items())}
    added: list[Change] = []
    removed: list[Change] = []
    modified: list[Change] = []
    unchanged: list[Change] = []
    for key in old_by_key.keys() | new_by_key.keys():
        before, after = old_by_key.get(key), new_by_key.get(key)
        clause_id = (after or before).clause_id  # type: ignore[union-attr]
        if before is None:
            added.append(Change(clause_id, None, after))
        elif after is None:
            removed.append(Change(clause_id, before, None))
        elif normalize(before.text) == normalize(after.text):
            unchanged.append(Change(clause_id, before, after))
        else:
            modified.append(Change(clause_id, before, after))
    key_order = lambda item: [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", item.clause_id)]
    return Comparison(old, new, tuple(sorted(added, key=key_order)), tuple(sorted(removed, key=key_order)),
                      tuple(sorted(modified, key=key_order)), tuple(sorted(unchanged, key=key_order)))
