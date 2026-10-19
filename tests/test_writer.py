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

    # v2.1 invariants: every <citationref> resolves to a real
    # <citation>, every <sourceref> on a citation resolves to a real
    # <source>, every <citation> has a parent <sourceref> (no orphans).
    sources = root.findall(f"{{{GRAMPS_NS}}}sources/{{{GRAMPS_NS}}}source")
    citations = root.findall(f"{{{GRAMPS_NS}}}citations/{{{GRAMPS_NS}}}citation")
    source_handles = {s.get("handle") for s in sources}
    citation_handles = {c.get("handle") for c in citations}
    assert len(sources) > 0, "no <source> elements emitted"
    assert len(citations) > 0, "no <citation> elements emitted"

    # Person / Family / Source / Event all carry citationrefs (we
    # only emit citationrefs that resolve).
    for owner in (*people, *families, *sources, *events):
        for cref in owner.findall(f"{{{GRAMPS_NS}}}citationref"):
            assert cref.get("hlink") in citation_handles, (
                f"{owner.tag.split('}')[-1]} {owner.get('id')} "
                f"citationref points to missing citation "
                f"{cref.get('hlink')}"
            )

    # Every <sourceref> on a citation resolves; every citation has
    # at least the wrapper emitted even if SourceID=0.
    for c in citations:
        sr = c.find(f"{{{GRAMPS_NS}}}sourceref")
        if sr is not None:
            assert sr.get("hlink") in source_handles, (
                f"citation {c.get('id')} sourceref points to missing "
                f"source {sr.get('hlink')}"
            )

    # v2.2 invariants: every <noteref> resolves to a real <note>,
    # every <note> has at least one <noteref> (no dangling notes).
    notes = root.findall(f"{{{GRAMPS_NS}}}notes/{{{GRAMPS_NS}}}note")
    if notes:
        note_handles = {n.get("handle") for n in notes}
        for owner in (*people, *families, *sources, *events, *places, *citations):
            for nref in owner.findall(f"{{{GRAMPS_NS}}}noteref"):
                assert nref.get("hlink") in note_handles, (
                    f"{owner.tag.split('}')[-1]} {owner.get('id')} "
                    f"noteref points to missing note {nref.get('hlink')}"
                )
        for note in notes:
            nrefs = note.findall(f"{{{GRAMPS_NS}}}noteref")
            assert len(nrefs) == 0, (
                f"note {note.get('id')} has its own <noteref> children "
                f"— should only be referenced, never carry refs itself"
            )
        # Every <note> must be referenced at least once. We use the
        # cross-reference set built above by walking every owner's
        # <noteref> children.
        referenced_notes: set[str] = set()
        for owner in (*people, *families, *sources, *events, *places, *citations):
            for nref in owner.findall(f"{{{GRAMPS_NS}}}noteref"):
                referenced_notes.add(nref.get("hlink"))
        for note in notes:
            assert note.get("handle") in referenced_notes, (
                f"note {note.get('id')} ({note.get('handle')}) is "
                f"emitted but no owner references it — dangling note"
            )

    # v2.2 invariants: every <mediaref> resolves to a real <object>,
    # every <reporef> resolves to a real <repository>.
    objects = root.findall(f"{{{GRAMPS_NS}}}media/{{{GRAMPS_NS}}}object")
    repos = root.findall(
        f"{{{GRAMPS_NS}}}repositories/{{{GRAMPS_NS}}}repository"
    )
    if objects:
        object_handles = {o.get("handle") for o in objects}
        for owner in (*people, *sources, *citations, *events):
            for mref in owner.findall(f"{{{GRAMPS_NS}}}mediaref"):
                assert mref.get("hlink") in object_handles, (
                    f"{owner.tag.split('}')[-1]} {owner.get('id')} "
                    f"mediaref points to missing object {mref.get('hlink')}"
                )
    if repos:
        repo_handles = {r.get("handle") for r in repos}
        for c in citations:
            for rref in c.findall(f"{{{GRAMPS_NS}}}reporef"):
                assert rref.get("hlink") in repo_handles, (
                    f"citation {c.get('id')} reporef points to missing "
                    f"repository {rref.get('hlink')}"
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


# --- narrowing invariants -----------------------------------------------
#
# docs/README.md claims `--person-ids` narrows *everything*
# transitively. These tests pin that for each object type. They use
# strict `<` — an earlier version asserted `<=`, which passes when
# narrowing is entirely absent (subset == full) and so hid the bug.
#
# Each test also checks the cross-reference invariant, because a
# narrowed export that emits a leaf nothing references is exactly the
# defect being fixed.


def _section(root: ET.Element, name: str, elem: str) -> list[ET.Element]:
    return root.findall(f"{{{GRAMPS_NS}}}{name}/{{{GRAMPS_NS}}}{elem}")


def _handles(elements: list[ET.Element]) -> set[str]:
    return {e.get("handle") for e in elements if e.get("handle")}


def _all_hlinks(root: ET.Element) -> set[str]:
    return {
        el.get("hlink")
        for el in root.iter()
        if el.get("hlink") is not None
    }


@pytest.fixture(scope="module")
def two_ids() -> list[int]:
    from rmread import open_database

    db = open_database(SAMPLE_TREE)
    try:
        return [
            r[0] for r in db.con.execute(
                "SELECT PersonID FROM PersonTable ORDER BY PersonID LIMIT 2"
            ).fetchall()
        ]
    finally:
        db.close()


@pytest.fixture(scope="module")
def full_root() -> ET.Element:
    return ET.fromstring(export_database(SAMPLE_TREE))


@pytest.fixture(scope="module")
def sub_root(two_ids: list[int]) -> ET.Element:
    return ET.fromstring(export_database(SAMPLE_TREE, person_ids=two_ids))


def test_subset_narrows_places(full_root: ET.Element, sub_root: ET.Element) -> None:
    """Places must narrow. Pre-fix, all 545 shipped for a 2-person subset."""
    full = _section(full_root, "places", "placeobj")
    sub = _section(sub_root, "places", "placeobj")
    assert len(sub) < len(full), (
        f"subset places ({len(sub)}) must be < full ({len(full)})"
    )


def test_subset_narrows_sources(full_root: ET.Element, sub_root: ET.Element) -> None:
    """Sources must narrow. Pre-fix, all 204 shipped for any subset."""
    full = _section(full_root, "sources", "source")
    sub = _section(sub_root, "sources", "source")
    assert len(sub) < len(full), (
        f"subset sources ({len(sub)}) must be < full ({len(full)})"
    )


def test_subset_narrows_repositories(
    full_root: ET.Element, sub_root: ET.Element
) -> None:
    """Repositories must narrow. Pre-fix, all 5 always shipped."""
    full = _section(full_root, "repositories", "repository")
    sub = _section(sub_root, "repositories", "repository")
    assert len(sub) < len(full), (
        f"subset repositories ({len(sub)}) must be < full ({len(full)})"
    )


def test_subset_narrows_citations(
    full_root: ET.Element, sub_root: ET.Element
) -> None:
    """Citations must narrow meaningfully, not by 2 of 434."""
    full = _section(full_root, "citations", "citation")
    sub = _section(sub_root, "citations", "citation")
    assert len(sub) < len(full) / 2, (
        f"subset citations ({len(sub)}) should be well under half of "
        f"full ({len(full)}); a near-equal count means the walker's "
        f"Source bucket is leaking unrequested citations"
    )


def test_subset_narrows_media(
    full_root: ET.Element, sub_root: ET.Element
) -> None:
    full = _section(full_root, "media", "object")
    sub = _section(sub_root, "media", "object")
    assert len(sub) < len(full), (
        f"subset media ({len(sub)}) must be < full ({len(full)})"
    )


def test_subset_emits_no_unreferenced_leaves(sub_root: ET.Element) -> None:
    """Every narrowed leaf object must be referenced by something.

    Places and repositories in a narrowed export exist only to satisfy
    a cross-reference. An unreferenced <placeobj> or <repository> is
    dead weight the researcher did not ask for.
    """
    hlinks = _all_hlinks(sub_root)
    for section, elem in (
        ("places", "placeobj"),
        ("repositories", "repository"),
        ("citations", "citation"),
        ("media", "object"),
        ("notes", "note"),
    ):
        orphans = _handles(_section(sub_root, section, elem)) - hlinks
        assert not orphans, (
            f"{section}: {len(orphans)} unreferenced {elem} in subset "
            f"export, e.g. {sorted(orphans)[:3]}"
        )


def test_empty_subset_emits_no_people() -> None:
    """An unknown PersonID must not ship 40% of the database.

    Regression: with no narrowing on sources/places/repositories,
    ``--person-ids 999999`` emitted zero people and ~200KB of
    citations, sources, and places.
    """
    root = ET.fromstring(export_database(SAMPLE_TREE, person_ids=[999999]))
    assert _section(root, "people", "person") == []
    # With no people, no family can reach a person either.
    assert _section(root, "families", "family") == []


def test_citationrefs_survive_noteref_injection(full_root: ET.Element) -> None:
    """<citationref> must survive the later <noteref>/<mediaref> pass.

    Regression: the noteref pass rebuilt people/families/sources from
    the *_pre strings, silently discarding every <citationref>
    injected beforehand. Person I0001 — whose only cross-reference is
    citation _g_c3 — came out with no citationref at all.

    Scope note: this only asserts that citations attached to a
    *person* survive. The full export legitimately contains many
    citations reachable only from their parent <source>, which is how
    Gramps models a source's own bibliography.
    """
    people = _section(full_root, "people", "person")

    with_citref = [p for p in people
                   if p.find(f"{{{GRAMPS_NS}}}citationref") is not None]
    assert with_citref, (
        "no person carries a <citationref>; the noteref pass is "
        "discarding the citationref injection"
    )

    # A person-attached citation must resolve to an emitted citation.
    citation_handles = _handles(_section(full_root, "citations", "citation"))
    person_cited = {
        c.get("hlink")
        for p in people
        for c in p.findall(f"{{{GRAMPS_NS}}}citationref")
        if c.get("hlink") is not None
    }
    dangling = person_cited - citation_handles
    assert not dangling, (
        f"{len(dangling)} citations referenced by a person are not "
        f"emitted, e.g. {sorted(dangling)[:3]}"
    )
