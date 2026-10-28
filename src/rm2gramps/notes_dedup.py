"""Inline-note loader + dedup.

Walks every inline note column on Person / Event / Family / Source
/ Place / Citation, dedups by (type, text), returns
``(notes_by_id, key_to_id)``.

RM has no separate NoteTable — notes are stored inline on each
owner. This module is the writer-side dedup that turns that inline
representation into a synthesised ``NoteRecord`` list.

Why the key is (type, text) and not text alone: the type is part of
a note's identity. "Only father" exists in SampleTree as both a
``Citation`` and a ``Source text``; collapsing them would give one of
the two the wrong Gramps type.

The key function itself lives in :mod:`rm2gramps.notes` — the
renderer — because it also derives the note's *handle*. One key, one
derivation, no drift.

Why sha256: stable, collision-resistant for text under ~100KB.
The Plan-locked caveat applies — two byte-identical notes of the
same type collapse to one <note>. Researcher can split in Gramps.

Schema reference: ``rmread/docs/rm11-schema.md`` §"Notes
inline on every owner table".
"""

from __future__ import annotations

import sqlite3

from .handles import note_handle
from .notes import NoteRecord, note_key

#: RM note-bearing column → Gramps note type name.
#:
#: The type names are Gramps' own English strings, spelled exactly as
#: ``gramps/gen/lib/notetype.py`` spells them. Gramps' importer
#: matches the ``type`` attribute case-sensitively against its map of
#: those names, so a name that is not in the map imports as a
#: *custom* type instead — which is what v2.2's ``type="general"``
#: produced, since "general" is not a Gramps type name ("General" is).
#:
#: ``ActualText`` is the researcher's verbatim transcription: of the
#: source for ``SourceTable``, of the specific citation for
#: ``CitationTable``. Gramps' own type for both is "Source text".
GRAMPS_NOTE_TYPES: dict[str, str] = {
    "PersonTable.Note": "Person Note",
    "EventTable.Note": "Event Note",
    "FamilyTable.Note": "Family Note",
    "PlaceTable.Note": "Place Note",
    "SourceTable.Comments": "Source Note",
    "SourceTable.ActualText": "Source text",
    "CitationTable.Comments": "Citation",
    "CitationTable.ActualText": "Source text",
}

def _collect_table_notes(
    con: sqlite3.Connection,
    table: str,
    note_column: str,
    owner_column: str | None,
    id_filter: set[int] | None = None,
) -> list[tuple[int, str]]:
    """Return ``[(owner_id, note_text), ...]`` for a single owner table.

    ``owner_column`` is the column whose value identifies the owner
    (PersonID, EventID, …). It's not used by the dedup but stays in
    the return tuple so the caller can attach <noteref> children
    later. Some tables have no owner column (e.g. Person is the
    owner itself); pass ``None`` for those.

    ``id_filter`` (when supplied) restricts the SELECT to owner
    ids in the filter set — used for export-scope narrowing so
    notes from non-exported owners don't appear in the output.
    """
    if owner_column is None:
        # No owner-id column — emit rows in rowid order with
        # synthetic numbering (rare case).
        if id_filter is not None and not id_filter:
            return []
        sql = f"SELECT {note_column} FROM {table}"
        rows = con.execute(sql).fetchall()
        return [(i, r[0]) for i, r in enumerate(rows, start=1) if r[0]]
    if id_filter is not None:
        if not id_filter:
            return []
        placeholders = ",".join("?" for _ in id_filter)
        sql = (
            f"SELECT {owner_column}, {note_column} FROM {table} "
            f"WHERE {owner_column} IN ({placeholders})"
        )
        rows = con.execute(sql, list(id_filter)).fetchall()
    else:
        sql = f"SELECT {owner_column}, {note_column} FROM {table}"
        rows = con.execute(sql).fetchall()
    return [
        (r[0], r[1]) for r in rows
        if r[1] and r[1].strip()
    ]


def load_notes(
    con: sqlite3.Connection,
    *,
    people_ids: set[int] | None = None,
    event_ids: set[int] | None = None,
    family_ids: set[int] | None = None,
    source_ids: set[int] | None = None,
    place_ids: set[int] | None = None,
    citation_ids: set[int] | None = None,
) -> tuple[dict[int, NoteRecord], dict[str, int]]:
    """Collect inline notes from every owner table, dedup by (type, text).

    Owner-id-set arguments scope which rows are read from each
    table. Pass ``None`` (the default) for "all rows in this
    table"; pass an explicit set to restrict. The default keeps
    full-DB export simple; explicit sets are required when the
    export is scope-restricted (e.g. ``--person-ids``) — without
    them, the dedup would emit notes whose owners aren't in the
    export and the resulting ``<note>`` elements would be
    dangling (nothing references them).

    Returns
    -------
    notes_by_id
        Map of synthesised note_id (1..N) → NoteRecord. ``note_id``
        is assigned in first-seen order of unique notes.
    key_to_id
        Map of note key → note_id. Lets callers attach
        ``<noteref>`` children by keying the owner's note text the
        same way and finding the resulting id.

    Notes
    -----
    Empty / whitespace-only inline notes are silently skipped.
    Multiple identical notes across owners collapse to one
    ``<note>`` (Plan-locked Decision 1 / Risk 4).
    """
    notes_by_id: dict[int, NoteRecord] = {}
    key_to_id: dict[str, int] = {}
    handle_to_key: dict[str, str] = {}
    next_id = 1

    # Each entry: (table, note_column, owner_column, owner_id_filter)
    sources: list[tuple[str, str, str | None, set[int] | None]] = [
        ("PersonTable", "Note", "PersonID", people_ids),
        ("EventTable", "Note", "EventID", event_ids),
        ("FamilyTable", "Note", "FamilyID", family_ids),
        ("SourceTable", "Comments", "SourceID", source_ids),
        ("PlaceTable", "Note", "PlaceID", place_ids),
        ("CitationTable", "Comments", "CitationID", citation_ids),
        # Transcriptions: the researcher's verbatim text of the
        # source and of the specific citation.
        ("SourceTable", "ActualText", "SourceID", source_ids),
        ("CitationTable", "ActualText", "CitationID", citation_ids),
    ]

    for table, note_col, owner_col, id_filter in sources:
        # If a filter is supplied and empty, skip this table
        # entirely — the owner-id set in the export is empty,
        # so no notes from this table can be referenced.
        if id_filter is not None and not id_filter:
            continue
        # Defend against unusual schemas where a table might not
        # exist (synthetic DBs).
        try:
            entries = _collect_table_notes(
                con, table, note_col, owner_col, id_filter,
            )
        except sqlite3.OperationalError:
            continue

        note_type = GRAMPS_NOTE_TYPES[f"{table}.{note_col}"]
        for owner_id, text in entries:
            stripped = text.strip()
            if not stripped:
                continue
            key = note_key(note_type, stripped)
            # The handle is derived from the key, truncated to 48 bits.
            # Two distinct notes must never land on the same handle —
            # Gramps would merge them on import. Astronomically
            # unlikely, but "no silent failure" cuts both ways: if it
            # happens, say so rather than emit a corrupt export.
            handle = note_handle(key)
            if handle in handle_to_key and handle_to_key[handle] != key:
                raise ValueError(
                    f"note handle collision: two distinct notes derive the "
                    f"handle {handle!r} (keys "
                    f"{handle_to_key[handle][:12]}… and {key[:12]}…)"
                )
            handle_to_key[handle] = key
            if key not in key_to_id:
                key_to_id[key] = next_id
                notes_by_id[next_id] = NoteRecord(
                    note_id=next_id, text=stripped, note_type=note_type,
                )
                next_id += 1
            # We don't currently expose owner → note_id maps; the
            # cross-reference injection (T27) handles owner-side
            # resolution by re-keying the owner's note text.

    return notes_by_id, key_to_id


def note_handles_for_texts(
    texts: list[str],
    key_to_id: dict[str, int],
    *,
    note_type: str,
) -> list[str]:
    """Resolve owner note texts to their Gramps handles.

    Used by the writer when attaching <noteref> children to an
    owner element. For each non-empty text, key it the same way
    as :func:`load_notes` and derive the handle from that key.
    Texts whose key isn't in the map (because they weren't loaded
    for some reason) are skipped — defensive against the writer's
    export scope having changed between loading and rendering.

    Parameters
    ----------
    texts
        Note text strings from a single owner (e.g. one Person's
        ``Note`` column plus any per-name notes).
    key_to_id
        The key → id map from :func:`load_notes`. Used only to check
        that the note was loaded; the handle comes from the key.
    note_type
        The Gramps type name for these texts. Part of the key, so
        it must match what ``load_notes`` used.

    Returns
    -------
    list[str]
        Note handles, one per unique note text. Duplicates within
        ``texts`` produce duplicate handles in the output (Gramps
        handles multiple noterefs to the same note fine; we
        don't dedup here because the writer is responsible for
        not calling this with overlapping texts).
    """
    out: list[str] = []
    for text in texts:
        if not text or not text.strip():
            continue
        key = note_key(note_type, text.strip())
        if key in key_to_id:
            out.append(note_handle(key))
    return out
