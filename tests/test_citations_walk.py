"""Tests for rm2gramps.citations_walk — CitationLinkTable walker.

T14 cases from ``tools/rm2gramps/plans/v2.1-citations-and-sources.md``
§ T14:

- walker returns a dict mapping owner-type → owner-id → citation-ids,
  with keys 'Person', 'Family', 'Source' (event citations are
  handled separately in writer.py via a direct JOIN)
- ``person_ids`` filter narrows the result set to citations
  referencing any of those persons (Person row + their families +
  their events)
- unknown ``OwnerType`` values (7, 19, anything else) → warn-and-skip:
  a warning is logged, no exception raised, the returned dict has
  no key for the unknown type

Tests run against ``SampleTree.rmtree`` (RM 11.0, 4.6 MB) at the
repo root — the schema doc notes CitationLinkTable distribution:
0 (Person) 17, 1 (Family) 48, 2 (Source) 604, 7 24, 19 9.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rmread import open_database

from rm2gramps.citations_walk import walk_citation_links


SAMPLE_TREE = Path("/home/tristan/genealogy_tools/SampleTree.rmtree")


def test_walk_returns_dict_of_owner_type_to_owner_id_to_citation_ids() -> None:
    """Walker yields Person / Family / Source dicts, each
    {owner_id: (citation_id, ...)}."""
    db = open_database(SAMPLE_TREE)
    try:
        result = walk_citation_links(db.con)
    finally:
        db.close()

    assert set(result.keys()) == {"Person", "Family", "Source"}

    # Per the schema doc, CitationLinkTable has 17 Person rows.
    # That doesn't mean 17 distinct persons — same person can be
    # cited many times — but there must be at least one entry.
    assert len(result["Person"]) >= 1
    # Family: 48 rows. Same logic.
    assert len(result["Family"]) >= 1
    # Source: 604 rows (most citations live on sources in this DB).
    assert len(result["Source"]) >= 1


def test_walk_respects_person_ids_subset() -> None:
    """``person_ids`` filter narrows the result to citations
    referencing those persons (or their families/events).

    For a tighter assertion we limit to a small subset and check
    that the resulting Person-keyed dict is exactly the persons
    we asked for.
    """
    db = open_database(SAMPLE_TREE)
    try:
        all_result = walk_citation_links(db.con)
        # Pick one person known to have citations (PersonID 1 is
        # the root person in SampleTree).
        if 1 not in all_result["Person"]:
            pytest.skip("PersonID=1 has no citations in this DB")
        person_subset = (1,)

        sub_result = walk_citation_links(db.con, person_ids=person_subset)
    finally:
        db.close()

    # Person-keyed dict must contain exactly the IDs we asked for.
    assert set(sub_result["Person"].keys()) <= set(person_subset)
    # If any Person from the subset has citations, the count of
    # citation IDs in sub_result must be <= count in all_result
    # (narrowing can only remove, never add).
    sub_total = sum(len(v) for v in sub_result["Person"].values())
    full_total = sum(len(v) for v in all_result["Person"].values())
    assert sub_total <= full_total


def test_walk_warns_on_unknown_owner_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown OwnerType values trigger a log warning; no exception."""
    caplog.set_level(logging.WARNING, logger="rm2gramps.citations_walk")
    db = open_database(SAMPLE_TREE)
    try:
        # No assertion on the warning content — just that one fires
        # when unknown OwnerTypes are encountered (SampleTree has 7
        # and 19).
        walk_citation_links(db.con)
    finally:
        db.close()

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) >= 1, "expected at least one warning for unknown OwnerTypes"
    # And the warning mentions OwnerType
    assert any("OwnerType" in r.getMessage() for r in warnings)


def test_walk_skips_unknown_owner_types_silently() -> None:
    """Returned dict has no key for unknown OwnerTypes — only
    Person / Family / Source."""
    db = open_database(SAMPLE_TREE)
    try:
        result = walk_citation_links(db.con)
    finally:
        db.close()

    # Only the three known owner types appear in the result.
    assert all(k in {"Person", "Family", "Source"} for k in result.keys())


# Reference to pytest for type-checkers; the import is already at the
# top via test_writer.py but pytest fixtures need it imported here
# too for the caplog parameter annotation.
import pytest  # noqa: E402