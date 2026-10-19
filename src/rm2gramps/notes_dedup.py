"""Inline-note loader + sha256 dedup.

Walks every inline ``Note TEXT`` column on Person / Event /
Family / Source / Place / Citation, dedups by sha256 of the
text, returns ``(notes_by_id, hash_to_id)``.

RM has no separate NoteTable — notes are stored inline on each
owner. This module is the writer-side dedup that turns that
inline representation into a synthesised ``NoteRecord`` list.

Why sha256: stable, collision-resistant for text under ~100KB.
The Plan-locked caveat applies — two byte-identical notes
collapse to one <note>. Researcher can split in Gramps.

Schema reference: ``tools/rmread/docs/rm11-schema.md`` §"Notes
inline on every owner table".
"""

from __future__ import annotations

import hashlib
import sqlite3

from .notes import NoteRecord


def _hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


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
    """Collect inline notes from every owner table, dedup by sha256.

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
        is assigned in first-seen order of unique text values.
    hash_to_id
        Map of sha256(text) → note_id. Lets callers attach
        ``<noteref>`` children by hashing the owner's note text
        the same way and finding the resulting id.

    Notes
    -----
    Empty / whitespace-only inline notes are silently skipped.
    Multiple identical notes across owners collapse to one
    ``<note>`` (Plan-locked Decision 1 / Risk 4).
    """
    notes_by_id: dict[int, NoteRecord] = {}
    hash_to_id: dict[str, int] = {}
    next_id = 1

    # Each entry: (table, note_column, owner_column, owner_id_filter)
    sources: list[tuple[str, str, str | None, set[int] | None]] = [
        ("PersonTable", "Note", "PersonID", people_ids),
        ("EventTable", "Note", "EventID", event_ids),
        ("FamilyTable", "Note", "FamilyID", family_ids),
        ("SourceTable", "Comments", "SourceID", source_ids),
        ("PlaceTable", "Note", "PlaceID", place_ids),
        ("CitationTable", "Comments", "CitationID", citation_ids),
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

        for owner_id, text in entries:
            stripped = text.strip()
            if not stripped:
                continue
            h = _hash_text(stripped)
            if h not in hash_to_id:
                hash_to_id[h] = next_id
                notes_by_id[next_id] = NoteRecord(
                    note_id=next_id, text=stripped,
                )
                next_id += 1
            # We don't currently expose owner → note_id maps; the
            # cross-reference injection (T27) handles owner-side
            # resolution by re-hashing the owner's note text.

    return notes_by_id, hash_to_id


def note_ids_for_texts(
    texts: list[str],
    hash_to_id: dict[str, int],
) -> list[int]:
    """Resolve owner note texts to synthesised note_ids.

    Used by the writer when attaching <noteref> children to an
    owner element. For each non-empty text, hash it the same way
    as :func:`load_notes` and look up the resulting id in
    ``hash_to_id``. Texts whose hash isn't in the map (because
    they weren't loaded for some reason) are skipped — defensive
    against the writer's export scope having changed between
    loading and rendering.

    Parameters
    ----------
    texts
        Note text strings from a single owner (e.g. one Person's
        ``Note`` column plus any per-name notes).
    hash_to_id
        The hash → id map from :func:`load_notes`.

    Returns
    -------
    list[int]
        Note_ids, one per unique note text. Duplicates within
        ``texts`` produce duplicate ids in the output (Gramps
        handles multiple noterefs to the same note fine; we
        don't dedup here because the writer is responsible for
        not calling this with overlapping texts).
    """
    out: list[int] = []
    for text in texts:
        if not text or not text.strip():
            continue
        h = _hash_text(text.strip())
        nid = hash_to_id.get(h)
        if nid is not None:
            out.append(nid)
    return out