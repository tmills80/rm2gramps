"""Tests for rm2gramps.notes_dedup — inline-note dedup loader.

T25 covers the writer-side inline-note dedup logic: collect every
non-empty inline ``Note`` column from Person / Event / Family /
Source / Place / Citation, dedup by sha256 of the text, return
``(notes_by_id, hash_to_id)`` so the writer can attach
``<noteref>`` children to owners.

Schema reference: ``tools/rmread/docs/rm11-schema.md``. RM stores
notes inline on each table — there is no separate NoteTable.

Tests run against ``SampleTree.rmtree`` (RM 11.0, 4.6 MB).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rmread import open_database

from rm2gramps.notes_dedup import load_notes
from ._fixture import sample_tree_path


SAMPLE_TREE = sample_tree_path()


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()



#: Skip every test in this module when the sample database is absent.
#: A fresh clone without `SampleTree.rmtree` is a normal state.
pytestmark = pytest.mark.skipif(
    SAMPLE_TREE is None,
    reason=(
        "the RootsMagic sample database is not available; set RM_SAMPLE_TREE "
        "to its path to run these tests"
    ),
)

def test_load_notes_returns_notes_by_id_and_hash_to_id() -> None:
    """Both return shapes are populated when DB has inline notes."""
    db = open_database(SAMPLE_TREE)
    try:
        notes_by_id, hash_to_id = load_notes(db.con)
    finally:
        db.close()

    # SampleTree has hundreds of inline notes across persons, events,
    # and other tables. Both maps should be non-empty.
    assert len(notes_by_id) > 0, "no notes loaded from SampleTree"
    assert len(hash_to_id) > 0
    assert len(notes_by_id) == len(hash_to_id), (
        f"notes_by_id ({len(notes_by_id)}) and hash_to_id "
        f"({len(hash_to_id)}) should match"
    )


def test_load_notes_dedup_by_text_hash() -> None:
    """Identical text → one note, not many."""
    db = open_database(SAMPLE_TREE)
    try:
        notes_by_id, hash_to_id = load_notes(db.con)
    finally:
        db.close()

    # Walk the keys: each hash should map to exactly one note.
    for h, nid in hash_to_id.items():
        assert nid in notes_by_id, f"hash {h[:8]} → {nid} but no note {nid}"
        # The note's text should hash to the same key.
        note = notes_by_id[nid]
        assert _hash(note.text) == h, (
            f"hash mismatch for note {nid}: {h[:8]} vs "
            f"{_hash(note.text)[:8]}"
        )


def test_load_notes_assigns_ids_in_first_seen_order() -> None:
    """note_id integers start at 1 and increase monotonically."""
    db = open_database(SAMPLE_TREE)
    try:
        notes_by_id, _ = load_notes(db.con)
    finally:
        db.close()

    ids = sorted(notes_by_id.keys())
    assert ids[0] == 1, f"first note_id should be 1, got {ids[0]}"
    assert ids == list(range(1, len(ids) + 1)), (
        f"ids should be 1..N, got {ids[:5]}…"
    )


def test_load_notes_empty_database_returns_empty_dicts(
    tmp_path: Path,
) -> None:
    """A minimal database with no inline notes → empty maps."""
    import sqlite3
    import unicodedata

    # Build a tiny valid-looking .rmtree with empty Note columns.
    bogus = tmp_path / "empty_notes.rmtree"
    con = sqlite3.connect(bogus)
    # executescript doesn't support parameter binding; use plain
    # execute with the BLOB passed as a parameter.
    con.execute("""
        CREATE TABLE ConfigTable (
            RecID INTEGER PRIMARY KEY,
            RecType INTEGER,
            Title TEXT,
            DataRec BLOB
        )
    """)
    root_blob = (
        b'<Root><Version>11000</Version><STVersion>700</STVersion>'
        b'<UniqueID>x</UniqueID><RootPerson>1</RootPerson></Root>'
    )
    con.create_collation(
        "RMNOCASE",
        lambda s, _n=None: None if s is None else "".join(
            c for c in unicodedata.normalize("NFKD", str(s))
            if not unicodedata.combining(c)
        ).casefold(),
    )
    con.execute(
        "INSERT INTO ConfigTable VALUES (1, 1, '', ?)",
        (root_blob,),
    )
    for ddl in (
        "CREATE TABLE PersonTable ("
        "PersonID INTEGER PRIMARY KEY, UniqueID TEXT, Sex INTEGER,"
        "Living INTEGER, IsPrivate INTEGER, Note TEXT)",
        "CREATE TABLE EventTable ("
        "EventID INTEGER PRIMARY KEY, EventType INTEGER,"
        "OwnerType INTEGER, OwnerID INTEGER, Note TEXT)",
        "CREATE TABLE FamilyTable ("
        "FamilyID INTEGER PRIMARY KEY, Note TEXT)",
        "CREATE TABLE SourceTable ("
        "SourceID INTEGER PRIMARY KEY, Note TEXT)",
        "CREATE TABLE PlaceTable ("
        "PlaceID INTEGER PRIMARY KEY, Note TEXT)",
        "CREATE TABLE CitationTable ("
        "CitationID INTEGER PRIMARY KEY, Comments TEXT)",
    ):
        con.execute(ddl)
    con.commit()
    con.close()

    from rmread import open_database

    db = open_database(bogus)
    try:
        notes_by_id, hash_to_id = load_notes(db.con)
    finally:
        db.close()
    assert notes_by_id == {}
    assert hash_to_id == {}


def test_load_notes_ignores_blank_text() -> None:
    """Empty / whitespace-only notes are skipped (no note emitted)."""
    db = open_database(SAMPLE_TREE)
    try:
        notes_by_id, _ = load_notes(db.con)
    finally:
        db.close()

    # No note in the dict should have empty or whitespace-only text.
    for nid, note in notes_by_id.items():
        assert note.text.strip(), (
            f"note {nid} has blank text: {note.text!r}"
        )