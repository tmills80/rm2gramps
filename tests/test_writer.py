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
from collections.abc import Iterator
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

    # v2.2 invariants: every <objref> resolves to a real <object>,
    # every <reporef> resolves to a real <repository>.
    #
    # The section is <objects> (Gramps' name for media) and the
    # reference element is <objref> — both per the 1.7.2 DTD. This
    # previously looked for a <media> section containing <object>,
    # which matched nothing, so the `if objects:` guard made the whole
    # block a no-op: it could not fail. Assert the objects are present
    # rather than skipping the check when the fixture changes.
    objects = root.findall(f"{{{GRAMPS_NS}}}objects/{{{GRAMPS_NS}}}object")
    repos = root.findall(
        f"{{{GRAMPS_NS}}}repositories/{{{GRAMPS_NS}}}repository"
    )
    assert objects, "no <object> elements emitted"
    object_handles = {o.get("handle") for o in objects}
    for owner in (*people, *sources, *citations, *events):
        for oref in owner.findall(f"{{{GRAMPS_NS}}}objref"):
            assert oref.get("hlink") in object_handles, (
                f"{owner.tag.split('}')[-1]} {owner.get('id')} "
                f"objref points to missing object {oref.get('hlink')}"
            )
    assert repos, "no <repository> elements emitted"
    repo_handles = {r.get("handle") for r in repos}
    for c in (*citations, *sources):
        for rref in c.findall(f"{{{GRAMPS_NS}}}reporef"):
            assert rref.get("hlink") in repo_handles, (
                f"{c.tag.split('}')[-1]} {c.get('id')} reporef points to "
                f"missing repository {rref.get('hlink')}"
            )


def test_writer_is_deterministic_across_two_runs() -> None:
    """Two exports of the same DB produce byte-equal XML.

    `change_ts` must be pinned. Without it the writer stamps
    `datetime.now()` into every `change="…"` attribute, so two runs
    a second apart legitimately differ — documented in the tool README
    ("CLI output is not byte-reproducible unless you script the
    library call"). This test asserts the property that *is* ours to
    guarantee: same input plus same change_ts → same bytes.
    """
    payload_a = export_database(SAMPLE_TREE, change_ts=1700000000)
    payload_b = export_database(SAMPLE_TREE, change_ts=1700000000)
    assert payload_a == payload_b


def test_pinned_change_ts_appears_in_output() -> None:
    """The pinned timestamp is what actually lands in the document.

    Without this, the determinism test above could pass for the wrong
    reason — e.g. if change_ts were silently ignored and the attribute
    came from somewhere else entirely.
    """
    payload = export_database(SAMPLE_TREE, change_ts=1700000000)
    assert b'change="1700000000"' in payload
    assert b'change="1700000001"' not in payload


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


# --- query-count guards ---------------------------------------------------
#
# load_people used to fire five queries per person — primary name, alt
# names, event refs, parent families, child families — so building 429
# people cost 2146 statements. The fix batches each of those into one
# query for the whole export scope.
#
# Counting uses sqlite3's trace callback rather than a mock: the real
# SQL really executes, and the connection is read-only so there is no
# side effect to unwind.


def _trace(db, fn):
    """Run fn(db.con) with tracing on; return (result, statements)."""
    seen: list[str] = []
    db.con.set_trace_callback(seen.append)
    try:
        result = fn(db.con)
    finally:
        db.con.set_trace_callback(None)
    return result, seen


def test_load_people_query_count_is_bounded(two_ids: list[int]) -> None:
    """Two people must not cost more statements than a full export.

    Pre-fix this was 5 per person (11 for two); the batched loaders
    run the same small number of statements for two people as for the
    whole tree, because every lookup is scoped to the export rather
    than to one person at a time.
    """
    from rmread import open_database
    from rm2gramps.writer import load_people

    db = open_database(SAMPLE_TREE)
    try:
        people, statements = _trace(
            db, lambda con: load_people(con, person_ids=two_ids)
        )
        kinds = {" ".join(s.split())[:60] for s in statements}

        assert len(people) == 2, f"expected 2 people, got {len(people)}"
        assert len(statements) <= 8, (
            f"load_people issued {len(statements)} statements for 2 people "
            f"(N+1 lookup regression):\n  " + "\n  ".join(sorted(kinds))
        )
    finally:
        db.close()


def test_load_people_query_count_does_not_grow_with_people() -> None:
    """The invariant: statement count is flat in the number of people.

    Two people and every person must both fit under the same ceiling.
    If a per-person query returns, the full-tree count grows with the
    row count and this fails.
    """
    from rmread import open_database
    from rm2gramps.writer import load_people

    db = open_database(SAMPLE_TREE)
    try:
        all_ids = [
            r[0] for r in db.con.execute(
                "SELECT PersonID FROM PersonTable ORDER BY PersonID"
            ).fetchall()
        ]
        small, small_stmts = _trace(
            db, lambda con: load_people(con, person_ids=all_ids[:5])
        )
        big, big_stmts = _trace(db, lambda con: load_people(con))

        assert len(small) == 5
        assert len(big) > 5
        assert len(big_stmts) <= 10, (
            f"loading {len(big)} people cost {len(big_stmts)} statements; "
            f"expected a small constant, so the batched loaders are not "
            f"in effect"
        )
        assert len(big_stmts) <= len(small_stmts) + 2, (
            f"statement count grew from {len(small_stmts)} (5 people) to "
            f"{len(big_stmts)} ({len(big)} people) — per-person queries "
            f"are back"
        )
    finally:
        db.close()


def test_load_people_batches_each_lookup(two_ids: list[int]) -> None:
    """Each of the five per-person lookups appears at most once.

    Names, event refs, parent families and child families each become a
    single scoped query. A per-person pattern shows up as many
    near-identical statements.
    """
    from rmread import open_database
    from rm2gramps.writer import load_people

    db = open_database(SAMPLE_TREE)
    try:
        _, statements = _trace(
            db, lambda con: load_people(con, person_ids=two_ids)
        )
        by_table: dict[str, int] = {}
        for s in statements:
            for table in ("NameTable", "EventTable", "FamilyTable",
                          "ChildTable", "PersonTable"):
                if table in s:
                    by_table[table] = by_table.get(table, 0) + 1
                    break
        for table, n in by_table.items():
            assert n <= 1, (
                f"{table} queried {n} times for 2 people — expected 1 "
                f"(batched) query"
            )
    finally:
        db.close()


# --- synthetic coverage for what SampleTree cannot exercise ---------------
#
# SampleTree.rmtree has zero NameTable rows with NameType <> 0, so its
# alt-name and missing-primary paths never run. These tests build a
# small synthetic DB that does cover them — the case where a person has
# alt names but no NameType=0 row at all, which is what the batched
# name loader's `None` primary exists to handle.

_OWNER_TYPE_EVENT = 1  # Birth


@pytest.fixture()
def synthetic_db() -> Iterator[str]:
    import sqlite3
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".rmtree", delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE ConfigTable (RecID INTEGER, RecType INTEGER, Title TEXT,
                                  DataRec BLOB, UTCModDate FLOAT);
        CREATE TABLE PersonTable (PersonID INTEGER PRIMARY KEY, UniqueID TEXT,
                                  Sex INTEGER, Living INTEGER,
                                  IsPrivate INTEGER);
        CREATE TABLE NameTable (NameID INTEGER PRIMARY KEY, OwnerID INTEGER,
                                Surname TEXT, Given TEXT, Prefix TEXT,
                                Suffix TEXT, Nickname TEXT, NameType INTEGER,
                                SortDate BIGINT, IsPrimary INTEGER,
                                Sentence TEXT, BirthYear INTEGER);
        CREATE TABLE EventTable (EventID INTEGER PRIMARY KEY,
                                 EventType INTEGER, OwnerType INTEGER,
                                 OwnerID INTEGER, PlaceID INTEGER, Date TEXT,
                                 SortDate BIGINT, IsPrimary INTEGER,
                                 Sentence TEXT, Details TEXT, Note TEXT);
        CREATE TABLE FamilyTable (FamilyID INTEGER PRIMARY KEY,
                                  FatherID INTEGER, MotherID INTEGER,
                                  ChildID INTEGER);
        CREATE TABLE ChildTable (RecID INTEGER PRIMARY KEY, ChildID INTEGER,
                                 FamilyID INTEGER, RelFather INTEGER,
                                 RelMother INTEGER, ChildOrder INTEGER);
        CREATE TABLE PlaceTable (PlaceID INTEGER PRIMARY KEY, Name TEXT);
        CREATE TABLE FactTypeTable (FactTypeID INTEGER PRIMARY KEY, Name TEXT);
    """)
    cur.execute(
        "INSERT INTO ConfigTable VALUES (1, 1, '', ?, 0)",
        (b"<Root><Version>11000</Version><STVersion>700</STVersion>"
         b"<UniqueID>FAKE-UUID</UniqueID><RootPerson>1</RootPerson></Root>",),
    )
    for pid, uid, sex in ((1, "synth-1", 1), (2, "synth-2", 2), (3, "synth-3", 0)):
        cur.execute(
            "INSERT INTO PersonTable VALUES (?, ?, ?, 0, 0)", (pid, uid, sex)
        )
    # Person 1: primary + three alt names. Person 2: ONLY an alt name —
    # no NameType=0 row, the edge case. Person 3: primary only.
    for nid, owner, surname, given, ntype, sdate in (
        (10, 1, "AAAAAA", "Zed", 0, 1),
        (11, 1, "MARR-NAME", "Zed", 1, 1),
        (12, 1, "AKA-NAME", "Zed", 2, 2),
        (13, 1, "IMM-NAME", "Zed", 3, 3),
        (20, 2, "ONLY-ALT", "Uma", 1, 1),
        (30, 3, "CCCCCC", "Vic", 0, 1),
    ):
        cur.execute(
            "INSERT INTO NameTable (NameID, OwnerID, Surname, Given, "
            "NameType, SortDate, IsPrimary, Sentence) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (nid, owner, surname, given, ntype, sdate, f"{given} {surname}"),
        )
    for eid, owner in ((100, 1), (101, 1), (200, 2)):
        cur.execute(
            "INSERT INTO EventTable (EventID, EventType, OwnerType, OwnerID,"
            " Date, SortDate, IsPrimary, Sentence) "
            "VALUES (?, ?, 0, ?, '1 JAN 1900', 1, 0, '')",
            (eid, _OWNER_TYPE_EVENT, owner),
        )
    # Family 1: person 1 + person 3 as parents, person 2 as their child.
    # Family 2: person 1 father, person 2 mother.
    cur.execute("INSERT INTO FamilyTable VALUES (1, 1, 3, 0)")
    cur.execute("INSERT INTO ChildTable VALUES (1, 2, 1, 1, 1, 1)")
    cur.execute("INSERT INTO FamilyTable VALUES (2, 1, 2, 0)")
    con.commit()
    con.close()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture()
def synthetic_people(synthetic_db: str) -> dict[int, object]:
    from rm2gramps.writer import load_people
    from rmread import open_database

    db = open_database(synthetic_db)
    try:
        return {p.person_id: p for p in load_people(db.con)}
    finally:
        db.close()


def test_load_people_attaches_alt_names(synthetic_people) -> None:
    """Alt names are attached, ordered by NameType, primary separated."""
    p1 = synthetic_people[1]
    assert p1.primary_name.surname == "AAAAAA"
    assert [a.name_type for a in p1.alt_names] == [1, 2, 3]
    assert [a.surname for a in p1.alt_names] == [
        "MARR-NAME", "AKA-NAME", "IMM-NAME",
    ]


def test_load_people_handles_missing_primary_name(synthetic_people) -> None:
    """A person with alt names but no NameType=0 row still loads.

    The batched name loader returns None for the primary in this case;
    load_people substitutes an empty NameRecord so <name> still emits
    and the handle resolves. Pre-batching, _load_primary_name handled
    this by returning an empty record.
    """
    p2 = synthetic_people[2]
    assert p2.primary_name.surname == ""
    assert p2.primary_name.given == ""
    assert len(p2.alt_names) == 1
    assert p2.alt_names[0].surname == "ONLY-ALT"


def test_load_people_keeps_family_links(synthetic_people) -> None:
    """childof / parentin survive the batched family queries."""
    p1 = synthetic_people[1]
    assert p1.parent_families == (1, 2)
    assert p1.child_families == ()

    p2 = synthetic_people[2]
    assert p2.child_families == (1,)
    assert p2.parent_families == (2,)

    p3 = synthetic_people[3]
    assert p3.parent_families == (1,)
    assert p3.child_families == ()


def test_load_people_handles_person_with_nothing(synthetic_people) -> None:
    """A person with no events and no child link yields empty tuples."""
    p3 = synthetic_people[3]
    assert p3.event_refs == ()
    assert isinstance(p3.child_families, tuple)


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
    full = _section(full_root, "objects", "object")
    sub = _section(sub_root, "objects", "object")
    assert len(sub) < len(full), (
        f"subset objects ({len(sub)}) must be < full ({len(full)})"
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


# --- MediaLinkTable OwnerType -> target table ----------------------------
#
# SampleTree.rmtree has every MediaLinkTable bucket populated with
# enough ids to disambiguate which table those OwnerIDs really belong
# to. The pre-fix writer trio "(2,Source), (3,Citation), (4,Event)"
# is the inverse of the data:
#
#     MediaLink OT=0 -> Person   (writer: Person, OK)
#     MediaLink OT=2 -> Event    (writer: Source, WRONG)
#     MediaLink OT=3 -> Source   (writer: Citation, WRONG)
#     MediaLink OT=4 -> Citation (writer: Event, WRONG)
#
# These tests assert the schema-level invariant the writer broke.


@pytest.mark.parametrize("owner_type,expected", [
    (0, "Person"),
    (2, "Event"),
    (3, "Source"),
    (4, "Citation"),
])
def test_medialink_ownertype_resolves_to_target_table(
    owner_type: int, expected: str,
) -> None:
    """Every MediaLinkTable OwnerID must land in the right table."""
    from rmread import open_database

    db = open_database(SAMPLE_TREE)
    try:
        con = db.con
        ids = {
            r[0] for r in con.execute(
                "SELECT DISTINCT OwnerID FROM MediaLinkTable "
                "WHERE OwnerType = ?", (owner_type,)
            )
        }
        assert len(ids) >= 2, (
            f"SampleTree MediaLink OT={owner_type} has too few rows "
            f"({len(ids)}) to test"
        )

        column = {
            "Person": "PersonID", "Family": "FamilyID",
            "Source": "SourceID", "Citation": "CitationID",
            "Event": "EventID",
        }[expected]
        ok = {r[0] for r in con.execute(
            f"SELECT {column} FROM {expected}Table"
        )}
        assert ids <= ok, (
            f"MediaLinkTable OwnerType={owner_type}: "
            f"{len(ids - ok)} of {len(ids)} OwnerIDs are not "
            f"{expected}IDs"
        )
    finally:
        db.close()


# --- AddressLinkTable 3 is Source, not Citation --------------------------


def test_writer_repolinks_resolve_to_sources(full_root: ET.Element) -> None:
    """<reporef> children live on <source>, pointing at <repository>.

    Pre-fix, AddressLinkTable.OwnerType=3 OwnerIDs were treated as
    CitationIDs. That mapped Repository/Address → Citation, which
    only makes sense if a citation "owns" a repository — but in
    Gramps and in RM, a source has repository addresses. After the
    fix, AddressLinkTable's OwnerType=3 IDs are SourceIDs, so
    <reporef> goes on <source> children and points at <repository>.
    """
    sources = _section(full_root, "sources", "source")
    source_handles = _handles(sources)
    repo_handles = _handles(_section(full_root, "repositories", "repository"))

    dead = []
    for src in sources:
        for r in src.findall(f"{{{GRAMPS_NS}}}reporef"):
            h = r.get("hlink")
            if not h:
                continue
            if h not in repo_handles:
                dead.append((src.get("handle"), h))
    assert not dead, (
        f"{len(dead)} <reporef> on <source> resolve to nothing: "
        f"{dead[:3]}"
    )

    # At least the major repository-bearing sources carry reporef.
    # SourceID 9 is the canonical one in SampleTree — 5 sources link
    # to AddressID=2, so at least one of them must carry it.
    cited_source_ids = [
        r.get("handle") for r in sources if r.findall(
            f"{{{GRAMPS_NS}}}reporef"
        )
    ]
    assert cited_source_ids, "no <source> carries a <reporef>"
