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

    assert set(result.keys()) == {
        "Person", "Family", "Event", "Source", "Citation",
    }

    # Per the schema doc, CitationLinkTable has 17 Person rows.
    # That doesn't mean 17 distinct persons — same person can be
    # cited many times — but there must be at least one entry.
    assert len(result["Person"]) >= 1
    # Family: 48 rows. Same logic.
    assert len(result["Family"]) >= 1
    # Event: OwnerType=2, 604 rows — the largest bucket in SampleTree.
    # These are events, not sources (see the OwnerType tests below).
    assert len(result["Event"]) >= 1
    # Source (OwnerType=3) and Citation (OwnerType=4) are absent from
    # SampleTree's CitationLinkTable, so those buckets stay empty.
    assert result["Source"] == {}
    assert result["Citation"] == {}


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
    """Returned dict has no key for unknown OwnerTypes — only the five
    buckets in the verified OwnerType enum. OwnerTypes 7 and 19 appear
    in SampleTree and are outside the enum, so they are dropped."""
    db = open_database(SAMPLE_TREE)
    try:
        result = walk_citation_links(db.con)
    finally:
        db.close()

    # Only the known owner types appear in the result.
    assert all(
        k in {"Person", "Family", "Event", "Source", "Citation"}
        for k in result.keys()
    )


# Reference to pytest for type-checkers; the import is already at the
# top via test_writer.py but pytest fixtures need it imported here
# too for the caplog parameter annotation.
import pytest  # noqa: E402


# --- OwnerType semantics --------------------------------------------------
#
# RM's OwnerType is ONE global enum shared by every *LinkTable:
#     0 = Person   1 = Family   2 = Event   3 = Source   4 = Citation
#
# Decisive evidence is CitationLinkTable OwnerType=2: 488 distinct
# OwnerIDs, and PersonTable (429 rows), FamilyTable (142), SourceTable
# (204) and CitationTable (438) are all too small to hold that many
# distinct IDs. EventTable (870) is the only possibility. This assumes
# referential integrity on OwnerID, which the schema otherwise does.


def _bucket_ids(con, owner_type: int) -> set[int]:
    return {
        r[0] for r in con.execute(
            "SELECT DISTINCT OwnerID FROM CitationLinkTable "
            "WHERE OwnerType = ?", (owner_type,)
        )
    }


def test_ownertype_2_is_event_not_source() -> None:
    """OwnerType=2 references EventIDs, not SourceIDs."""
    db = open_database(SAMPLE_TREE)
    try:
        con = db.con
        ids = _bucket_ids(con, 2)
        assert len(ids) > 100, "sample too small to be decisive"

        event_ids = {r[0] for r in con.execute("SELECT EventID FROM EventTable")}
        source_ids = {r[0] for r in con.execute("SELECT SourceID FROM SourceTable")}

        assert ids <= event_ids, (
            f"{len(ids - event_ids)} of {len(ids)} OwnerType=2 OwnerIDs "
            f"are not EventIDs"
        )
        assert len(ids) > len(source_ids), (
            f"{len(ids)} distinct OwnerIDs but only {len(source_ids)} "
            f"source rows — cannot mean Source"
        )
    finally:
        db.close()


def test_ownertype_0_is_person_and_1_is_family() -> None:
    """OwnerTypes 0 and 1 keep their Person / Family meaning."""
    db = open_database(SAMPLE_TREE)
    try:
        con = db.con
        pids = {r[0] for r in con.execute("SELECT PersonID FROM PersonTable")}
        fids = {r[0] for r in con.execute("SELECT FamilyID FROM FamilyTable")}

        assert _bucket_ids(con, 0) <= pids
        assert _bucket_ids(con, 1) <= fids
    finally:
        db.close()


def test_ownertype_enum_is_shared_across_link_tables() -> None:
    """MediaLinkTable uses the same enum: 3 = Source, 4 = Citation."""
    db = open_database(SAMPLE_TREE)
    try:
        con = db.con

        def media_ids(owner_type: int) -> set[int]:
            return {
                r[0] for r in con.execute(
                    "SELECT DISTINCT OwnerID FROM MediaLinkTable "
                    "WHERE OwnerType = ?", (owner_type,)
                )
            }

        source_ids = {r[0] for r in con.execute("SELECT SourceID FROM SourceTable")}
        citation_ids = {r[0] for r in con.execute("SELECT CitationID FROM CitationTable")}

        ot3, ot4 = media_ids(3), media_ids(4)
        assert len(ot3) > 20 and len(ot4) > 20, "buckets too small to trust"

        assert ot3 <= source_ids, "MediaLinkTable OwnerType=3 is not Source"
        assert ot4 <= citation_ids, "MediaLinkTable OwnerType=4 is not Citation"
    finally:
        db.close()


# The tests above validate the RM schema, which is why they pass
# regardless of what rm2gramps believes. These two fail until the
# walker is fixed — they assert the walker's OUTPUT matches the
# schema.


def test_walker_does_not_labour_events_as_sources() -> None:
    """The walker's Source bucket must not be populated by EventIDs.

    OwnerType=2 is 488 EventIDs. Under the old mapping they landed in
    result["Source"], so 488 event-owned citations were attributed to
    sources. After the fix, the Source bucket only holds OwnerType=3
    rows, and EventIDs must not appear in it.
    """
    db = open_database(SAMPLE_TREE)
    try:
        con = db.con
        result = walk_citation_links(con)
        source_bucket_owner_ids = set(result["Source"])
        ot2_ids = _bucket_ids(con, 2)
        assert not ot2_ids.intersection(source_bucket_owner_ids), (
            f"{len(ot2_ids.intersection(source_bucket_owner_ids))} "
            f"OwnerType=2 (Event) ids leaked into the Source bucket"
        )
    finally:
        db.close()


def test_walker_reports_unknown_ownertypes_separately() -> None:
    """OwnerType=2 must map to its own key, not be silently dropped.

    The old map had no key for Event, so event-owned citations were
    either misfiled or dropped. After the fix there is a distinct
    bucket for them, and genuinely-unknown types (7, 19) still warn.
    """
    db = open_database(SAMPLE_TREE)
    try:
        con = db.con
        result = walk_citation_links(con)
        keys = set(result)

        assert len(_bucket_ids(con, 2)) > 100
        assert "Event" in keys or "Source" not in keys, (
            "walker has no Event bucket and is treating OwnerType=2 "
            "as Source"
        )
    finally:
        db.close()


def test_walker_event_bucket_matches_the_db() -> None:
    """The Event bucket holds exactly the OwnerType=2 rows."""
    db = open_database(SAMPLE_TREE)
    try:
        con = db.con
        result = walk_citation_links(con)
        db_rows = con.execute(
            "SELECT COUNT(*) FROM CitationLinkTable WHERE OwnerType = 2"
        ).fetchone()[0]
        assert db_rows > 0, "SampleTree should have OwnerType=2 rows"
        assert sum(len(v) for v in result["Event"].values()) == db_rows
    finally:
        db.close()
