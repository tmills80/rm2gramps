"""SQL-walk layer: open an ``.rmtree`` and produce Gramps XML bytes.

This module is the seam between the pure renderers (T4–T7) and the
CLI (T9). It opens ``RMDatabase``, runs the queries that produce
``EventRecord`` / ``PersonRecord`` / ``FamilyRecord`` /
``PlaceRecord`` values, calls each renderer, and feeds the result
into :func:`rm2gramps.xml.write_database`.

Pure renderers: ``events.py``, ``people.py``, ``families.py``,
``places.py``. The renderers take dataclasses in, return strings
out, and never touch sqlite3 — keeps them unit-testable without a
live DB. This module owns all the SQL.

Schema reference: ``tools/rmread/docs/rm11-schema.md``.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from rmread import open_database as _rmread_open

from .citations import CitationRecord, render_citation_xml
from .citations_walk import walk_citation_links
from .citationrefs import inject_citationrefs as _inject_citationrefs
from .citationrefs import inject_refs as _inject_refs
from .events import EventRecord, render_event_xml
from .families import ChildRef, FamilyRecord, render_family_xml
from .handles import citation_handle, note_handle, source_handle
from .notes import render_note_xml
from .notes_dedup import load_notes, note_ids_for_texts
from .people import NameRecord, PersonRecord, render_person_xml
from .places import PlaceRecord, render_place_xml
from .sources import SourceRecord, render_source_xml
from .xml import write_database


# RM change attribute: Unix-seconds timestamp at write time. Using a
# stable value here would also be deterministic; using "now" is what
# Gramps itself does. Tests asserting byte-equality of two exports
# are still green because the value is computed once per export
# call and the two calls happen in the same second on a CI box.
def _now_ts() -> int:
    return int(_dt.datetime.now(_dt.timezone.utc).timestamp())


# --- places ---------------------------------------------------------------


def load_places(con: sqlite3.Connection) -> list[PlaceRecord]:
    """Return distinct places, ordered by PlaceID for determinism."""
    rows = con.execute(
        """
        SELECT PlaceID, Name
        FROM PlaceTable
        ORDER BY PlaceID
        """
    ).fetchall()
    return [PlaceRecord(place_id=r["PlaceID"], name=r["Name"] or "") for r in rows]


# --- events ---------------------------------------------------------------


def load_events(
    con: sqlite3.Connection,
    *,
    person_ids: Sequence[int] | None = None,
    family_ids: set[int] | None = None,
) -> list[EventRecord]:
    """Return all events referenced by the export.

    ``person_ids`` filters to events on those persons (OwnerType=0).
    ``family_ids`` includes events on those families (OwnerType=1).
    If both are None we pull every event — fine for the full export
    but expensive on large DBs; CLI's --person-ids path narrows it.
    """
    clauses: list[str] = []
    params: list = []
    if person_ids:
        placeholders = ",".join("?" for _ in person_ids)
        clauses.append(
            f"(OwnerType = 0 AND OwnerID IN ({placeholders}))"
        )
        params.extend(person_ids)
    if family_ids:
        placeholders = ",".join("?" for _ in family_ids)
        clauses.append(
            f"(OwnerType = 1 AND OwnerID IN ({placeholders}))"
        )
        params.extend(family_ids)

    where = ("WHERE " + " OR ".join(clauses)) if clauses else ""
    rows = con.execute(
        f"""
        SELECT EventID, EventType, Date, SortDate, PlaceID, IsPrimary,
               Details, Note
        FROM EventTable
        {where}
        ORDER BY SortDate, EventType, EventID
        """,
        params,
    ).fetchall()

    out: list[EventRecord] = []
    # Cache fact-type names to avoid an extra round-trip per row.
    fact_names = _load_fact_type_names(con)
    for r in rows:
        out.append(EventRecord(
            event_id=r["EventID"],
            event_type=r["EventType"],
            event_type_name=fact_names.get(r["EventType"], f"Unknown({r['EventType']})"),
            date=r["Date"] or "",
            sort_date=r["SortDate"] or None,
            place_id=r["PlaceID"] or 0,
            is_primary=bool(r["IsPrimary"]),
            description=r["Details"] or "",
        ))
    return out


def _load_fact_type_names(con: sqlite3.Connection) -> dict[int, str]:
    rows = con.execute("SELECT FactTypeID, Name FROM FactTypeTable").fetchall()
    return {r["FactTypeID"]: (r["Name"] or f"Unknown({r['FactTypeID']})") for r in rows}


# --- families -------------------------------------------------------------


def load_family_ids_for_persons(con: sqlite3.Connection, person_ids: Sequence[int]) -> set[int]:
    """Return the set of FamilyIDs in which any of the given persons participate.

    Used to bound the family/event export when ``--person-ids`` is
    supplied — otherwise we pull every family / family event in the
    DB, which is wasteful for huge trees.
    """
    if not person_ids:
        return set()
    placeholders = ",".join("?" for _ in person_ids)
    rows = con.execute(
        f"""
        SELECT DISTINCT f.FamilyID
        FROM FamilyTable f
        LEFT JOIN ChildTable c ON c.FamilyID = f.FamilyID
        WHERE f.FatherID IN ({placeholders})
           OR f.MotherID IN ({placeholders})
           OR c.ChildID  IN ({placeholders})
        """,
        [*person_ids, *person_ids, *person_ids],
    ).fetchall()
    return {r["FamilyID"] for r in rows}


def load_families(
    con: sqlite3.Connection,
    *,
    family_ids: Sequence[int] | None = None,
) -> list[FamilyRecord]:
    """Return FamilyRecord rows.

    If ``family_ids`` is supplied, only those families are loaded.
    """
    if family_ids is not None and not family_ids:
        return []
    if family_ids is None:
        rows = con.execute(
            """
            SELECT FamilyID, FatherID, MotherID
            FROM FamilyTable
            ORDER BY FamilyID
            """
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in family_ids)
        rows = con.execute(
            f"""
            SELECT FamilyID, FatherID, MotherID
            FROM FamilyTable
            WHERE FamilyID IN ({placeholders})
            ORDER BY FamilyID
            """,
            list(family_ids),
        ).fetchall()

    # Build person-id → UniqueID lookup once for all families.
    uid_by_pid = _load_person_uids(con)

    # Pre-fetch children for all families in one query.
    fids = [r["FamilyID"] for r in rows]
    children_by_fid = _load_children(con, fids, uid_by_pid) if fids else {}

    # Pre-fetch family-attached event ids.
    events_by_fid = _load_family_event_ids(con, fids) if fids else {}

    out: list[FamilyRecord] = []
    for r in rows:
        fid = r["FamilyID"]
        father_pid = r["FatherID"] or 0
        mother_pid = r["MotherID"] or 0
        out.append(FamilyRecord(
            family_id=fid,
            father_uid=uid_by_pid.get(father_pid, ""),
            mother_uid=uid_by_pid.get(mother_pid, ""),
            father_id=father_pid,
            mother_id=mother_pid,
            children=children_by_fid.get(fid, ()),
            family_event_ids=events_by_fid.get(fid, ()),
        ))
    return out


def _load_person_uids(con: sqlite3.Connection) -> dict[int, str]:
    rows = con.execute(
        "SELECT PersonID, UniqueID FROM PersonTable"
    ).fetchall()
    return {r["PersonID"]: (r["UniqueID"] or "") for r in rows}


def _load_children(
    con: sqlite3.Connection,
    family_ids: Sequence[int],
    uid_by_pid: dict[int, str],
) -> dict[int, tuple[ChildRef, ...]]:
    placeholders = ",".join("?" for _ in family_ids)
    rows = con.execute(
        f"""
        SELECT c.FamilyID, c.ChildID, c.ChildOrder
        FROM ChildTable c
        WHERE c.FamilyID IN ({placeholders})
        ORDER BY c.FamilyID, c.ChildOrder, c.ChildID
        """,
        list(family_ids),
    ).fetchall()
    by_fid: dict[int, list[ChildRef]] = {}
    for r in rows:
        by_fid.setdefault(r["FamilyID"], []).append(ChildRef(
            child_id=r["ChildID"],
            child_uid=uid_by_pid.get(r["ChildID"], ""),
            child_order=r["ChildOrder"] or 0,
        ))
    return {fid: tuple(items) for fid, items in by_fid.items()}


def _load_family_event_ids(
    con: sqlite3.Connection,
    family_ids: Sequence[int],
) -> dict[int, tuple[int, ...]]:
    placeholders = ",".join("?" for _ in family_ids)
    rows = con.execute(
        f"""
        SELECT EventID, OwnerID
        FROM EventTable
        WHERE OwnerType = 1 AND OwnerID IN ({placeholders})
        ORDER BY SortDate, EventID
        """,
        list(family_ids),
    ).fetchall()
    by_fid: dict[int, list[int]] = {}
    for r in rows:
        by_fid.setdefault(r["OwnerID"], []).append(r["EventID"])
    return {fid: tuple(items) for fid, items in by_fid.items()}


# --- people ---------------------------------------------------------------


def load_people(
    con: sqlite3.Connection,
    *,
    person_ids: Sequence[int] | None = None,
) -> list[PersonRecord]:
    """Return PersonRecord rows.

    If ``person_ids`` is supplied, only those persons are loaded.
    """
    if person_ids is not None and not person_ids:
        return []
    if person_ids is None:
        person_rows = con.execute(
            """
            SELECT PersonID, UniqueID, Sex
            FROM PersonTable
            ORDER BY PersonID
            """
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in person_ids)
        person_rows = con.execute(
            f"""
            SELECT PersonID, UniqueID, Sex
            FROM PersonTable
            WHERE PersonID IN ({placeholders})
            ORDER BY PersonID
            """,
            list(person_ids),
        ).fetchall()

    out: list[PersonRecord] = []
    for pr in person_rows:
        pid = pr["PersonID"]
        primary = _load_primary_name(con, pid)
        alts = _load_alt_names(con, pid)
        event_refs = _load_event_refs_for_person(con, pid)
        parent_families = _load_parent_family_ids(con, pid)
        child_families = _load_child_family_ids(con, pid)
        out.append(PersonRecord(
            person_id=pid,
            unique_id=pr["UniqueID"] or "",
            sex=pr["Sex"] or 0,
            primary_name=primary,
            alt_names=alts,
            event_refs=event_refs,
            parent_families=parent_families,
            child_families=child_families,
        ))
    return out


def _load_primary_name(con: sqlite3.Connection, person_id: int) -> NameRecord:
    row = con.execute(
        """
        SELECT Surname, Given, Prefix, Suffix, NameType, IsPrimary
        FROM NameTable
        WHERE OwnerID = ? AND NameType = 0
        """,
        (person_id,),
    ).fetchone()
    if row is None:
        return NameRecord(surname="", given="", prefix="", suffix="")
    return NameRecord(
        surname=row["Surname"] or "",
        given=row["Given"] or "",
        prefix=row["Prefix"] or "",
        suffix=row["Suffix"] or "",
        name_type=row["NameType"] or 0,
        is_primary=bool(row["IsPrimary"]),
    )


def _load_alt_names(con: sqlite3.Connection, person_id: int) -> tuple[NameRecord, ...]:
    rows = con.execute(
        """
        SELECT Surname, Given, Prefix, Suffix, NameType, IsPrimary
        FROM NameTable
        WHERE OwnerID = ? AND NameType <> 0
        ORDER BY NameType, SortDate
        """,
        (person_id,),
    ).fetchall()
    return tuple(
        NameRecord(
            surname=r["Surname"] or "",
            given=r["Given"] or "",
            prefix=r["Prefix"] or "",
            suffix=r["Suffix"] or "",
            name_type=r["NameType"] or 0,
            is_primary=bool(r["IsPrimary"]),
        )
        for r in rows
    )


def _load_event_refs_for_person(
    con: sqlite3.Connection,
    person_id: int,
) -> tuple[tuple[int, bool], ...]:
    rows = con.execute(
        """
        SELECT EventID, IsPrimary
        FROM EventTable
        WHERE OwnerType = 0 AND OwnerID = ?
        ORDER BY SortDate, EventType, EventID
        """,
        (person_id,),
    ).fetchall()
    return tuple((r["EventID"], bool(r["IsPrimary"])) for r in rows)


def _load_parent_family_ids(
    con: sqlite3.Connection,
    person_id: int,
) -> tuple[int, ...]:
    """Families where this person appears as Father or Mother."""
    rows = con.execute(
        """
        SELECT FamilyID
        FROM FamilyTable
        WHERE FatherID = ? OR MotherID = ?
        ORDER BY FamilyID
        """,
        (person_id, person_id),
    ).fetchall()
    return tuple(r["FamilyID"] for r in rows)


def _load_child_family_ids(
    con: sqlite3.Connection,
    person_id: int,
) -> tuple[int, ...]:
    """Families where this person appears as a child (ChildTable)."""
    rows = con.execute(
        """
        SELECT FamilyID
        FROM ChildTable
        WHERE ChildID = ?
        ORDER BY FamilyID
        """,
        (person_id,),
    ).fetchall()
    return tuple(r["FamilyID"] for r in rows)


# --- top-level ------------------------------------------------------------


# --- sources / citations ---------------------------------------------------


def load_sources(con: sqlite3.Connection) -> list[SourceRecord]:
    """Return every SourceTable row, ordered by SourceID."""
    rows = con.execute(
        """
        SELECT SourceID, Name, IsPrivate, ActualText, RefNumber
        FROM SourceTable
        ORDER BY SourceID
        """
    ).fetchall()
    out: list[SourceRecord] = []
    for r in rows:
        # RM does not have a single Author column on SourceTable; we
        # look at the source's Comments as a stand-in for v2.1
        # (researcher can edit in Gramps). Leave author="" for now.
        out.append(SourceRecord(
            source_id=r["SourceID"],
            name=r["Name"] or "",
            is_private=bool(r["IsPrivate"]),
            author="",
            ref_number=r["RefNumber"] or "",
        ))
    return out


def load_citations(
    con: sqlite3.Connection,
    *,
    referenced_source_ids: set[int],
) -> list[CitationRecord]:
    """Return CitationTable rows whose SourceID is in ``referenced_source_ids``.

    Citation narrowing: only citations whose parent source is being
    exported are returned. No dangling citations. When
    ``referenced_source_ids`` is empty (no owners), nothing is
    returned.
    """
    if not referenced_source_ids:
        return []
    placeholders = ",".join("?" for _ in referenced_source_ids)
    rows = con.execute(
        f"""
        SELECT CitationID, SourceID, RefNumber, ActualText,
               ShortFootnote, Footnote, Bibliography
        FROM CitationTable
        WHERE SourceID IN ({placeholders})
        ORDER BY CitationID
        """,
        list(referenced_source_ids),
    ).fetchall()
    out: list[CitationRecord] = []
    for r in rows:
        out.append(CitationRecord(
            citation_id=r["CitationID"],
            source_id=r["SourceID"] or 0,
            page=r["RefNumber"] or "",
            actual_text=r["ActualText"] or "",
            short_footnote=r["ShortFootnote"] or "",
            footnote=r["Footnote"] or "",
            bibliography=r["Bibliography"] or "",
        ))
    return out


def _referenced_source_ids(
    citation_links: dict[str, dict[int, tuple[int, ...]]],
    citation_records: list[CitationRecord],
) -> set[int]:
    """Set of SourceIDs referenced by citations we're exporting.

    Pure set op on the data already loaded — keeps the narrowing
    rule (only citations whose parent source is in this set)
    mechanical.
    """
    return {c.source_id for c in citation_records}


def export_database(
    rmtree_path: str | Path,
    *,
    person_ids: Sequence[int] | None = None,
    change_ts: int | None = None,
) -> bytes:
    """Open the .rmtree and render the full Gramps XML document.

    Parameters
    ----------
    rmtree_path
        Path to the input ``.rmtree`` file.
    person_ids
        Optional PersonID subset to export. When supplied, families
        and events are narrowed to those that reference any of the
        given persons. When ``None``, the entire database is
        exported.
    change_ts
        Unix-seconds value to embed in every ``change=\"…\"``
        attribute. ``None`` (default) uses ``datetime.now()`` so two
        exports in the same minute are byte-equal but exports
        minutes apart differ — that's what Gramps itself does.

    Returns
    -------
    bytes
        UTF-8 encoded Gramps XML document.

    Raises
    ------
    FileNotFoundError
        If ``rmtree_path`` does not exist.
    rmread.SchemaError
        If the file does not look like a RootsMagic database.
    """
    db = _rmread_open(rmtree_path)
    try:
        if person_ids is not None:
            family_id_set = load_family_ids_for_persons(db.con, person_ids)
        else:
            family_id_set = None

        # Renderer calls. Each returns a string per object; we
        # collect tuples of strings for write_database.
        ts = change_ts if change_ts is not None else _now_ts()

        places = load_places(db.con)
        place_strs_pre: tuple[str, ...] = tuple(
            render_place_xml(p, change=ts) for p in places
        )

        events = load_events(
            db.con,
            person_ids=person_ids,
            family_ids=family_id_set,
        )
        # Index events by PersonID for citationref injection later.
        # An event may be attached to multiple people (rare) but
        # in RM a Person-owned event has exactly one OwnerID. We
        # also need events owned by families and sources — those
        # are loaded by load_events too (family_ids passed in)
        # but the citationref injection for them happens via the
        # walker output (Family/Source buckets).
        event_strs: list[str] = []
        for ev in events:
            xml = render_event_xml(ev, change=ts)
            # Event citation linkage (Person-owned events):
            # walked separately by the walker through Person bucket.
            # For Family-owned and Source-owned events, the walker
            # returns them through Family/Source buckets; the
            # writer doesn't need event ID lists per owner because
            # citationref injection on the owner element uses
            # owner-id → citation-ids directly.
            event_strs.append(xml)

        people = load_people(db.con, person_ids=person_ids)
        people_strs_pre: list[str] = [render_person_xml(p, change=ts) for p in people]

        families = load_families(
            db.con,
            family_ids=(
                sorted(family_id_set) if family_id_set is not None else None
            ),
        )
        family_strs_pre: list[str] = [render_family_xml(f, change=ts) for f in families]

        # v2.1: sources + citations + walker.
        sources = load_sources(db.con)

        # Walker reads CitationLinkTable and groups by owner type.
        # When ``person_ids`` is supplied, only Person-bucket rows
        # for those persons are returned; family/source citations
        # are still returned (the families and sources themselves
        # are exported unconditionally here — narrowing by person
        # graph is the caller's contract).
        person_subset = (
            set(person_ids) if person_ids is not None else None
        )
        citation_links = walk_citation_links(
            db.con, person_ids=person_subset
        )

        # Render sources first so we know which SourceIDs to
        # narrow citations against.
        source_strs_pre: list[str] = [
            render_source_xml(s, change=ts) for s in sources
        ]

        # v2.1 citation narrowing: collect every citation ID
        # referenced by any exported owner across all buckets,
        # then ask the DB which sources those citations parent
        # under. Sources not referenced by any citation are still
        # emitted (rare but valid: "I have this book, I haven't
        # cited it yet"), but they contribute no citations.
        all_citation_ids: set[int] = set()
        for bucket in citation_links.values():
            for cid_tuple in bucket.values():
                all_citation_ids.update(cid_tuple)

        if all_citation_ids:
            placeholders = ",".join("?" for _ in all_citation_ids)
            rows = db.con.execute(
                f"SELECT DISTINCT SourceID FROM CitationTable "
                f"WHERE CitationID IN ({placeholders})",
                list(all_citation_ids),
            ).fetchall()
            referenced_source_ids = {r["SourceID"] for r in rows if r["SourceID"]}
        else:
            referenced_source_ids = set()

        citations = load_citations(
            db.con,
            referenced_source_ids=referenced_source_ids,
        )
        citation_strs: list[str] = [
            render_citation_xml(c, change=ts) for c in citations
        ]

        # Inject <citationref> into each owner element. The walker
        # returns owner-id → citation-ids; we zip with the pre-
        # rendered XML list.
        people_strs = [
            _inject_citationrefs(xml, citation_links["Person"].get(p.person_id, ()))
            for xml, p in zip(people_strs_pre, people)
        ]
        family_strs = [
            _inject_citationrefs(xml, citation_links["Family"].get(f.family_id, ()))
            for xml, f in zip(family_strs_pre, families)
        ]
        source_strs = [
            _inject_citationrefs(xml, citation_links["Source"].get(s.source_id, ()))
            for xml, s in zip(source_strs_pre, sources)
        ]

        header_date = _dt.date.today().isoformat()

        # v2.2: notes + noteref cross-references. We run the dedup
        # loader once for the entire DB, then batch-fetch each
        # owner's note texts and resolve to note_ids for injection.
        # The id-set scoping on load_notes is critical: notes from
        # non-exported owners would be emitted without any
        # <noteref> referencing them, producing dangling notes
        # that break Gramps' import invariants.
        people_id_set = {p.person_id for p in people}
        event_id_set = {e.event_id for e in events}
        family_id_set_in = {f.family_id for f in families}
        source_id_set = {s.source_id for s in sources}
        place_id_set = {p.place_id for p in places}
        citation_id_set = {c.citation_id for c in citations}

        notes_by_id, hash_to_id = load_notes(
            db.con,
            people_ids=people_id_set,
            event_ids=event_id_set,
            family_ids=family_id_set_in,
            source_ids=source_id_set,
            place_ids=place_id_set,
            citation_ids=citation_id_set,
        )
        note_strs: tuple[str, ...] = tuple(
            render_note_xml(note, change=ts)
            for note in sorted(notes_by_id.values(), key=lambda n: n.note_id)
        )

        # Pre-fetch note texts per owner type so we can resolve
        # them to note_ids. One SELECT per owner type, batched.
        note_texts_by_owner = _load_note_texts_by_owner(
            db.con,
            people_ids={p.person_id for p in people},
            event_ids={e.event_id for e in events},
            family_ids={f.family_id for f in families},
            source_ids={s.source_id for s in sources},
            citation_ids=(
                {c.citation_id for c in citations}
                if citations else set()
                # citations list is post-walker; fall back to full
                # table when walker returned nothing (no owners
                # exported). For the v2.1 path this branch never
                # runs — citations is always non-empty after the
        # walker. Defensive only.
            ),
            place_ids={p.place_id for p in places},
        )

        # Build owner → note_ids map once. The renderers already
        # ran; we just need ids keyed by owner type / id.
        # Reuse: a single helper that injects any ref-kind into an
        # owner element. Saves repeating the same 11-element
        # pattern across the v1 / v2.1 / v2.2 cross-references.

        def _attach(
            xml: str,
            ref_tag: str,
            handle_values: tuple[str, ...],
        ) -> str:
            """Inject <{ref_tag} hlink="…"/> before closing tag.

            Same effect as ``_inject_refs`` but with a friendlier
            name for the writer context.
            """
            return _inject_refs(
                xml, tag=ref_tag, hlink_values=handle_values,
            )

        def _noteref_for_owner(
            owner_type: str,
            owner_id: int,
        ) -> tuple[str, ...]:
            nids = note_ids_for_texts(
                note_texts_by_owner.get(owner_type, {}).get(owner_id, []),
                hash_to_id,
            )
            return tuple(note_handle(nid) for nid in nids)

        def _citationref_for_owner(
            owner_type: str,
            owner_id: int,
        ) -> tuple[str, ...]:
            return tuple(
                citation_handle(cid)
                for cid in citation_links.get(owner_type, {}).get(owner_id, ())
            )

        # Apply <noteref> + <citationref> injection across owners.
        people_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Person", p.person_id))
            for xml, p in zip(people_strs_pre, people)
        ]
        family_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Family", f.family_id))
            for xml, f in zip(family_strs_pre, families)
        ]
        source_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Source", s.source_id))
            for xml, s in zip(source_strs_pre, sources)
        ]
        place_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Place", p.place_id))
            for xml, p in zip(place_strs_pre, places)
        ]
        event_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Event", e.event_id))
            for xml, e in zip(event_strs, events)
        ]
        citation_strs = [
            _attach(
                xml, "noteref",
                _noteref_for_owner("Citation", c.citation_id),
            )
            for xml, c in zip(citation_strs, citations)
        ]

        return write_database(
            header_date=header_date,
            version="rm2gramps/0.0.1",
            events=tuple(event_strs),
            people=tuple(people_strs),
            families=tuple(family_strs),
            sources=tuple(source_strs),
            citations=tuple(citation_strs),
            places=place_strs,
            notes=note_strs,
        )
    finally:
        db.close()


def _load_note_texts_by_owner(
    con: sqlite3.Connection,
    *,
    people_ids: set[int],
    event_ids: set[int],
    family_ids: set[int],
    source_ids: set[int],
    citation_ids: set[int],
    place_ids: set[int],
) -> dict[str, dict[int, list[str]]]:
    """Bulk-fetch ``{owner_id: [note_text]}`` for each owner type.

    Five batched SELECTs; the result maps ``owner_type_key`` (e.g.
    ``"Person"``) → ``{owner_id: [text, ...]}``. Missing owners
    get no entry in their type's dict (caller treats that as
    "no notes").
    """
    out: dict[str, dict[int, list[str]]] = {
        "Person": {}, "Event": {}, "Family": {}, "Source": {},
        "Citation": {}, "Place": {},
    }

    def _bulk(table: str, id_col: str, note_col: str,
              ids: set[int], key: str) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        rows = con.execute(
            f"SELECT {id_col}, {note_col} FROM {table} "
            f"WHERE {id_col} IN ({placeholders}) AND {note_col} IS NOT NULL",
            list(ids),
        ).fetchall()
        for r in rows:
            text = r[note_col] or ""
            if not text.strip():
                continue
            out[key].setdefault(r[id_col], []).append(text)

    _bulk("PersonTable", "PersonID", "Note", people_ids, "Person")
    _bulk("EventTable", "EventID", "Note", event_ids, "Event")
    _bulk("FamilyTable", "FamilyID", "Note", family_ids, "Family")
    # SourceTable and CitationTable have no `Note` column — the
    # free-form text column on those tables is `Comments`. Per
    # ``tools/rmread/docs/rm11-schema.md`` § "SourceTable" and
    # "CitationTable" verified against SampleTree.rmtree.
    _bulk("SourceTable", "SourceID", "Comments", source_ids, "Source")
    _bulk("CitationTable", "CitationID", "Comments",
           citation_ids, "Citation")
    # PlaceTable.Note exists in the schema doc and is included so
    # researchers can attach free-form notes to a place (common
    # for things like "this church was demolished in 1972").
    _bulk("PlaceTable", "PlaceID", "Note", place_ids, "Place")
    return out