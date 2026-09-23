from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .models import Clause, SourceDocument

NUMERIC_CLAUSE_RE = re.compile(
    r"^\s*(?P<clause_id>\d+(?:\.\d+){0,9})\s*[.)]?\s*(?P<body>.*?)\s*$",
    re.DOTALL,
)
LETTERED_SUBPOINT_RE = re.compile(
    r"^\s*(?P<letter>[A-Za-zА-Яа-яЁё])\s*[.)]\s*(?P<body>.*?)\s*$",
    re.DOTALL,
)
CLAUSE_ID_ONLY_RE = re.compile(r"^\s*\d+(?:\.\d+){0,9}\s*[.)]?\s*$")
SUBPOINT_ID_ONLY_RE = re.compile(r"^\s*[A-Za-zА-Яа-яЁё]\s*[.)]\s*$")


@dataclass(frozen=True)
class TextBlock:
    """A text fragment and its location in the source document."""

    text: str
    location: str


def compact_text(value: object) -> str:
    """Normalize extraction whitespace without changing the words used as evidence."""

    return " ".join(str(value).replace("\xa0", " ").split())


def is_standalone_clause_id(text: str) -> bool:
    return bool(CLAUSE_ID_ONLY_RE.fullmatch(text) or SUBPOINT_ID_ONLY_RE.fullmatch(text))


def _starts_clause(text: str) -> bool:
    return bool(NUMERIC_CLAUSE_RE.match(text) or LETTERED_SUBPOINT_RE.match(text))


def _logical_fragments(block: TextBlock) -> list[TextBlock]:
    """Split a multiline block only where a new explicit clause starts.

    PDF extractors commonly wrap one paragraph across many visual lines. Joining those
    lines is preferable, while manual line breaks before ``5.3.2`` or ``б)`` must remain
    separate clauses.
    """

    raw_lines = [compact_text(line) for line in block.text.splitlines()]
    lines = [line for line in raw_lines if line]
    if not lines:
        return []

    groups: list[list[str]] = []
    for line in lines:
        if groups and _starts_clause(line):
            groups.append([line])
        elif groups:
            groups[-1].append(line)
        else:
            groups.append([line])

    if len(groups) == 1:
        return [TextBlock(" ".join(groups[0]), block.location)]
    return [
        TextBlock(" ".join(group), f"{block.location} / segment {index}")
        for index, group in enumerate(groups, start=1)
    ]


def _clause_location(location: str, clause_id: str, letter: str | None = None) -> str:
    if letter is None:
        return f"{location} / section {clause_id}"
    return f"{location} / section {clause_id} / subpoint {letter}"


def parse_blocks(blocks: Iterable[TextBlock], name: str) -> SourceDocument:
    """Build a ``SourceDocument`` while preserving existing shared model contracts."""

    fragments = [
        fragment
        for block in blocks
        for fragment in _logical_fragments(block)
        if compact_text(fragment.text)
    ]
    clauses: list[Clause] = []
    unnumbered: list[str] = []
    current_numeric_id: str | None = None
    pending_numeric: tuple[str, TextBlock] | None = None
    pending_lettered: tuple[str, str | None, TextBlock] | None = None

    for fragment in fragments:
        text = compact_text(fragment.text)
        numeric = NUMERIC_CLAUSE_RE.match(text)
        lettered = LETTERED_SUBPOINT_RE.match(text)

        if pending_numeric is not None:
            pending_id, pending_block = pending_numeric
            if numeric is None and lettered is None:
                clauses.append(
                    Clause(
                        clause_id=pending_id,
                        text=text,
                        source=name,
                        location=_clause_location(
                            f"{pending_block.location} / continuation {fragment.location}",
                            pending_id,
                        ),
                    )
                )
                current_numeric_id = pending_id
                pending_numeric = None
                continue
            unnumbered.append(compact_text(pending_block.text))
            pending_numeric = None

        if pending_lettered is not None:
            pending_letter, pending_parent, pending_block = pending_lettered
            if numeric is None and lettered is None:
                clause_id = (
                    f"{pending_parent}.{pending_letter}" if pending_parent else pending_letter
                )
                clauses.append(
                    Clause(
                        clause_id=clause_id,
                        text=text,
                        source=name,
                        location=_clause_location(
                            f"{pending_block.location} / continuation {fragment.location}",
                            pending_parent or clause_id,
                            pending_letter,
                        ),
                    )
                )
                pending_lettered = None
                continue
            unnumbered.append(compact_text(pending_block.text))
            pending_lettered = None

        if numeric is not None:
            clause_id = numeric.group("clause_id").rstrip(".")
            body = compact_text(numeric.group("body"))
            if not body:
                pending_numeric = (clause_id, fragment)
                current_numeric_id = clause_id
                continue
            clauses.append(
                Clause(
                    clause_id=clause_id,
                    text=body,
                    source=name,
                    location=_clause_location(fragment.location, clause_id),
                )
            )
            current_numeric_id = clause_id
            continue

        if lettered is not None:
            letter = lettered.group("letter").casefold()
            body = compact_text(lettered.group("body"))
            if not body:
                pending_lettered = (letter, current_numeric_id, fragment)
                continue
            clause_id = f"{current_numeric_id}.{letter}" if current_numeric_id else letter
            clauses.append(
                Clause(
                    clause_id=clause_id,
                    text=body,
                    source=name,
                    location=_clause_location(
                        fragment.location,
                        current_numeric_id or clause_id,
                        letter,
                    ),
                )
            )
            continue

        unnumbered.append(text)

    if pending_numeric is not None:
        unnumbered.append(compact_text(pending_numeric[1].text))
    if pending_lettered is not None:
        unnumbered.append(compact_text(pending_lettered[2].text))

    return SourceDocument(name=name, clauses=tuple(clauses), unnumbered_blocks=tuple(unnumbered))
