"""Tests for rm2gramps.writer — the SQL-walk layer that feeds the renderers.

T9 (writer half): the pure renderers from T4–T8 take pre-loaded
dataclasses. This module is the layer in between — it opens a
``RMDatabase``, runs the queries that produce those dataclasses,
calls the renderers, and feeds the resulting strings into
``xml.write_database``.

The big test is ``test_writer_round_trip_against_sample_tree``:
run the full pipeline against ``SampleTree.rmtree``, gunzip /
parse the output, and assert structural invariants (every
``<childof>`` resolves to a real ``<family>`` handle, etc.). That
is the test that proves the writer layer is correct.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rm2gramps.writer import export_database


SAMPLE_TREE = Path("/home/tristan/genealogy_tools/SampleTree.rmtree")
GRAMPS_NS = "http://gramps-project.org/xml/1.7.2/"


def test_writer_round_trip_against_sample_tree() -> None:
    """Run the full export against SampleTree.rmtree and verify structure."""
    payload = export_database(SAMPLE_TREE)
    # export_database returns bytes; we parse the XML directly.
    root = ET.fromstring(payload)

    # Root is the namespaced <database>
    assert root.tag == f"{{{GRAMPS_NS}}}database"

    # At least one of each object type — sanity check on SampleTree.
    events = root.findall(f"{{{GRAMPS_NS}}}events/{{{GRAMPS_NS}}}event")
    people = root.findall(f"{{{GRAMPS_NS}}}people/{{{GRAMPS_NS}}}person")
    families = root.findall(f"{{{GRAMPS_NS}}}families/{{{GRAMPS_NS}}}family")
    places = root.findall(f"{{{GRAMPS_NS}}}places/{{{GRAMPS_NS}}}placeobj")
    assert len(events) > 0, "no <event> elements emitted"
    assert len(people) > 0, "no <person> elements emitted"
    assert len(families) > 0, "no <family> elements emitted"
    assert len(places) > 0, "no <placeobj> elements emitted"

    # Build handle sets for cross-reference checks.
    event_handles = {e.get("handle") for e in events}
    person_handles = {p.get("handle") for p in people}
    family_handles = {f.get("handle") for f in families}
    place_handles = {pl.get("handle") for pl in places}

    # Every <eventref hlink> on a <person> resolves to a real <event>.
    for p in people:
        for evref in p.findall(f"{{{GRAMPS_NS}}}eventref"):
            assert evref.get("hlink") in event_handles, (
                f"person {p.get('id')} has eventref to missing event "
                f"{evref.get('hlink')}"
            )
        # _UID attribute carries the RM UniqueID.
        uid_attr = p.find(f"{{{GRAMPS_NS}}}attribute[@type='_UID']")
        assert uid_attr is not None, f"person {p.get('id')} has no _UID"
        assert uid_attr.get("value"), f"person {p.get('id')} has empty _UID"

    # Every <eventref hlink> on a <family> resolves to a real <event>.
    for f in families:
        for evref in f.findall(f"{{{GRAMPS_NS}}}eventref"):
            assert evref.get("hlink") in event_handles, (
                f"family {f.get('id')} has eventref to missing event "
                f"{evref.get('hlink')}"
            )
        # Father / mother / childref all resolve to real persons.
        for tag in ("father", "mother"):
            ref = f.find(f"{{{GRAMPS_NS}}}{tag}")
            if ref is not None:
                assert ref.get("hlink") in person_handles, (
                    f"family {f.get('id')} {tag} points to missing person "
                    f"{ref.get('hlink')}"
                )
        for childref in f.findall(f"{{{GRAMPS_NS}}}childref"):
            assert childref.get("hlink") in person_handles, (
                f"family {f.get('id')} childref points to missing person "
                f"{childref.get('hlink')}"
            )

    # Every <childof> / <parentin> on a <person> resolves to a real <family>.
    for p in people:
        for childof in p.findall(f"{{{GRAMPS_NS}}}childof"):
            assert childof.get("hlink") in family_handles, (
                f"person {p.get('id')} childof points to missing family "
                f"{childof.get('hlink')}"
            )
        for parentin in p.findall(f"{{{GRAMPS_NS}}}parentin"):
            assert parentin.get("hlink") in family_handles, (
                f"person {p.get('id')} parentin points to missing family "
                f"{parentin.get('hlink')}"
            )

    # Every <place hlink> on an <event> resolves to a real <placeobj>.
    for ev in events:
        place_ref = ev.find(f"{{{GRAMPS_NS}}}place")
        if place_ref is not None:
            assert place_ref.get("hlink") in place_handles, (
                f"event {ev.get('id')} place hlink points to missing "
                f"placeobj {place_ref.get('hlink')}"
            )


def test_writer_is_deterministic_across_two_runs() -> None:
    """Two exports of the same DB produce byte-equal XML."""
    payload_a = export_database(SAMPLE_TREE)
    payload_b = export_database(SAMPLE_TREE)
    assert payload_a == payload_b


def test_writer_rejects_non_rmtree(tmp_path: Path) -> None:
    import sqlite3

    bogus = tmp_path / "not_rmtree.db"
    con = sqlite3.connect(bogus)
    con.execute("CREATE TABLE foo (x INTEGER)")
    con.execute("INSERT INTO foo VALUES (1)")
    con.close()

    from rmread import SchemaError

    with pytest.raises(SchemaError):
        export_database(bogus)


def test_writer_rejects_missing_file(tmp_path: Path) -> None:
    from rm2gramps.writer import export_database as _export

    with pytest.raises(FileNotFoundError):
        _export(tmp_path / "does_not_exist.rmtree")


def test_writer_subset_person_ids() -> None:
    """``person_ids`` filter restricts the exported <people> set."""
    payload_full = export_database(SAMPLE_TREE)
    full_root = ET.fromstring(payload_full)
    full_people = full_root.findall(f"{{{GRAMPS_NS}}}people/{{{GRAMPS_NS}}}person")
    full_count = len(full_people)
    assert full_count >= 2, "SampleTree should have ≥2 people"

    # Pick the first two PersonIDs from the database, restrict export to them.
    import sqlite3

    con = sqlite3.connect(f"file:{SAMPLE_TREE}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    import unicodedata

    con.create_collation(
        "RMNOCASE",
        lambda s, _n=None: None if s is None else "".join(
            c for c in unicodedata.normalize("NFKD", str(s))
            if not unicodedata.combining(c)
        ).casefold(),
    )
    ids = [r[0] for r in con.execute(
        "SELECT PersonID FROM PersonTable ORDER BY PersonID LIMIT 2"
    ).fetchall()]
    con.close()

    payload_sub = export_database(SAMPLE_TREE, person_ids=ids)
    sub_root = ET.fromstring(payload_sub)
    sub_people = sub_root.findall(f"{{{GRAMPS_NS}}}people/{{{GRAMPS_NS}}}person")
    assert len(sub_people) == 2
    assert full_count > 2