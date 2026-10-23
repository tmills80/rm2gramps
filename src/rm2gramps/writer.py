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
import sys
from collections.abc import Sequence
from pathlib import Path

from rmread import open_database as _rmread_open

from .citations import CitationRecord, render_citation_xml
from rmread.linktables import (
    address_owner_map,
    media_owner_map,
    walk_citation_links,
)
from .citationrefs import inject_citationrefs as _inject_citationrefs

# Read as `_attach(xml, "noteref", handles)` at the call sites below.
# _inject_refs takes keyword args for tag and hlink_values; the local
# alias keeps those call sites to one positional line each.
from .citationrefs import inject_refs as _attach
from .events import EventRecord, render_event_xml
from .families import ChildRef, FamilyRecord, render_family_xml
from .handles import (
    citation_handle,
    media_handle,
    note_handle,
    repository_handle,
    source_handle,
)
from .media import MediaRecord, render_media_xml
from .notes import render_note_xml
from .notes_dedup import (
    GRAMPS_NOTE_TYPES,
    load_notes,
    note_ids_for_texts,
)
from .people import NameRecord, PersonRecord, render_person_xml
from .places import PlaceRecord, render_place_xml
from .repositories import RepositoryRecord, render_repository_xml
from .schema_order import reorder_children
from .sources import SourceRecord, render_source_xml
from .xml import write_database


# RM change attribute: Unix-seconds timestamp at write time. Using
# "now" is what Gramps itself does. Note that "computed once per export
# call" is NOT what makes two exports byte-equal — two calls a minute
# apart differ. export_database takes change_ts for callers that need
# reproducibility; pass a fixed value and the output is deterministic
# across any interval.
def _now_ts() -> int:
    return int(_dt.datetime.now(_dt.timezone.utc).timestamp())


# --- places ---------------------------------------------------------------


def load_places(
    con: sqlite3.Connection,
    *,
    keep_ids: set[int] | None = None,
) -> list[PlaceRecord]:
    """Return distinct places, ordered by PlaceID for determinism.

    ``keep_ids`` narrows to the given PlaceIDs. Pass ``None`` for the
    full table. A place exists in the export only to satisfy an
    ``<place hlink>`` on an exported event, so narrowing to the
    referenced ids keeps the subset export from carrying the whole
    PlaceTable.
    """
    if keep_ids is not None and not keep_ids:
        return []
    if keep_ids is None:
        rows = con.execute(
            """
            SELECT PlaceID, Name
            FROM PlaceTable
            ORDER BY PlaceID
            """
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in keep_ids)
        rows = con.execute(
            f"""
            SELECT PlaceID, Name
            FROM PlaceTable
            WHERE PlaceID IN ({placeholders})
            ORDER BY PlaceID
            """,
            list(keep_ids),
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

    Every per-person lookup (primary name, alt names, event refs,
    parent families, child families) is batched into one query scoped
    to the whole export rather than run once per person. Five queries
    per person meant 2146 statements for SampleTree's 429 people.
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

    pids = [r["PersonID"] for r in person_rows]
    if not pids:
        return []

    scope = ",".join("?" for _ in pids)
    names_by_pid = _load_names_for_people(con, pids, scope)
    event_refs_by_pid = _load_event_refs_for_people(con, pids, scope)
    parent_fams_by_pid = _load_parent_families_for_people(con, pids, scope)
    child_fams_by_pid = _load_child_families_for_people(con, pids, scope)

    out: list[PersonRecord] = []
    for pr in person_rows:
        pid = pr["PersonID"]
        primary, alts = names_by_pid.get(pid, (None, ()))
        if primary is None:
            # Person exists but has no NameType=0 row (rare in RM, but
            # imported/unreconciled records do it). Render an empty
            # name so <name> still emits and the handle resolves.
            primary = NameRecord(
                surname="", given="", prefix="", suffix="",
                name_type=0, is_primary=True,
            )
        out.append(PersonRecord(
            person_id=pid,
            unique_id=pr["UniqueID"] or "",
            sex=pr["Sex"] or 0,
            primary_name=primary,
            alt_names=alts,
            event_refs=event_refs_by_pid.get(pid, ()),
            parent_families=parent_fams_by_pid.get(pid, ()),
            child_families=child_fams_by_pid.get(pid, ()),
        ))
    return out


def _load_names_for_people(
    con: sqlite3.Connection,
    pids: Sequence[int],
    scope: str,
) -> dict[int, tuple[NameRecord | None, tuple[NameRecord, ...]]]:
    """One query for every person's names.

    Returns ``{PersonID: (primary, alt_names)}``. The primary is the
    NameType=0 row; everything else is an alt name. A person with no
    NameType=0 row gets ``None`` as the primary so the caller can
    substitute an empty NameRecord.
    """
    rows = con.execute(
        f"""
        SELECT OwnerID, Surname, Given, Prefix, Suffix, NameType, IsPrimary
        FROM NameTable
        WHERE OwnerID IN ({scope})
        ORDER BY OwnerID, NameType, SortDate
        """,
        list(pids),
    ).fetchall()

    prim: dict[int, NameRecord] = {}
    alts: dict[int, list[NameRecord]] = {}
    for r in rows:
        rec = NameRecord(
            surname=r["Surname"] or "",
            given=r["Given"] or "",
            prefix=r["Prefix"] or "",
            suffix=r["Suffix"] or "",
            name_type=r["NameType"] or 0,
            is_primary=bool(r["IsPrimary"]),
        )
        pid = r["OwnerID"]
        if rec.name_type == 0:
            prim.setdefault(pid, rec)
        else:
            alts.setdefault(pid, []).append(rec)
    return {
        pid: (prim.get(pid), tuple(alts.get(pid, ())))
        for pid in {r["OwnerID"] for r in rows}
    }


def _load_event_refs_for_people(
    con: sqlite3.Connection,
    pids: Sequence[int],
    scope: str,
) -> dict[int, tuple[tuple[int, bool], ...]]:
    """One query for every person's Person-owned event refs."""
    rows = con.execute(
        f"""
        SELECT OwnerID, EventID, IsPrimary
        FROM EventTable
        WHERE OwnerType = 0 AND OwnerID IN ({scope})
        ORDER BY OwnerID, SortDate, EventType, EventID
        """,
        list(pids),
    ).fetchall()
    by_pid: dict[int, list[tuple[int, bool]]] = {}
    for r in rows:
        by_pid.setdefault(r["OwnerID"], []).append(
            (r["EventID"], bool(r["IsPrimary"]))
        )
    return {pid: tuple(v) for pid, v in by_pid.items()}


def _load_parent_families_for_people(
    con: sqlite3.Connection,
    pids: Sequence[int],
    scope: str,
) -> dict[int, tuple[int, ...]]:
    """One query: families where each person is Father or Mother."""
    rows = con.execute(
        f"""
        SELECT FatherID, MotherID, FamilyID
        FROM FamilyTable
        WHERE FatherID IN ({scope}) OR MotherID IN ({scope})
        ORDER BY FamilyID
        """,
        [*pids, *pids],
    ).fetchall()
    by_pid: dict[int, set[int]] = {}
    for r in rows:
        for pid in (r["FatherID"], r["MotherID"]):
            if pid:
                by_pid.setdefault(pid, set()).add(r["FamilyID"])
    return {pid: tuple(sorted(v)) for pid, v in by_pid.items()}


def _load_child_families_for_people(
    con: sqlite3.Connection,
    pids: Sequence[int],
    scope: str,
) -> dict[int, tuple[int, ...]]:
    """One query: families where each person appears as a child."""
    rows = con.execute(
        f"""
        SELECT ChildID, FamilyID
        FROM ChildTable
        WHERE ChildID IN ({scope})
        ORDER BY FamilyID
        """,
        list(pids),
    ).fetchall()
    by_pid: dict[int, set[int]] = {}
    for r in rows:
        if r["ChildID"]:
            by_pid.setdefault(r["ChildID"], set()).add(r["FamilyID"])
    return {pid: tuple(sorted(v)) for pid, v in by_pid.items()}


# --- top-level ------------------------------------------------------------


# --- sources / citations ---------------------------------------------------


def load_sources(
    con: sqlite3.Connection,
    *,
    keep_ids: set[int] | None = None,
) -> list[SourceRecord]:
    """Return SourceTable rows, ordered by SourceID.

    ``keep_ids`` narrows to the given SourceIDs; ``None`` returns the
    whole table. Callers pass the sources that an exported citation
    actually parents under, so a subset export does not carry every
    source in the tree.
    """
    if keep_ids is not None and not keep_ids:
        return []
    if keep_ids is None:
        rows = con.execute(
            """
            SELECT SourceID, Name, IsPrivate, ActualText, RefNumber
            FROM SourceTable
            ORDER BY SourceID
            """
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in keep_ids)
        rows = con.execute(
            f"""
            SELECT SourceID, Name, IsPrivate, ActualText, RefNumber
            FROM SourceTable
            WHERE SourceID IN ({placeholders})
            ORDER BY SourceID
            """,
            list(keep_ids),
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
    keep_ids: set[int] | None = None,
) -> list[CitationRecord]:
    """Return CitationTable rows whose SourceID is in ``referenced_source_ids``.

    Citation narrowing: only citations whose parent source is being
    exported are returned. No dangling citations. When
    ``referenced_source_ids`` is empty (no owners), nothing is
    returned.

    ``keep_ids`` further narrows to specific CitationIDs. Source-level
    narrowing alone is too coarse on a subset export: every citation
    under a surviving source is a sibling of the one you asked for,
    and nothing may reference it. Pass the exact citation ids the
    walker found to emit only those.
    """
    if not referenced_source_ids:
        return []
    if keep_ids is not None and not keep_ids:
        return []
    placeholders = ",".join("?" for _ in referenced_source_ids)
    if keep_ids is None:
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
    else:
        cite_placeholders = ",".join("?" for _ in keep_ids)
        rows = con.execute(
            f"""
            SELECT CitationID, SourceID, RefNumber, ActualText,
                   ShortFootnote, Footnote, Bibliography
            FROM CitationTable
            WHERE SourceID IN ({placeholders})
              AND CitationID IN ({cite_placeholders})
            ORDER BY CitationID
            """,
            [*referenced_source_ids, *keep_ids],
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

        events = load_events(
            db.con,
            person_ids=person_ids,
            family_ids=family_id_set,
        )

        # Places are loaded after events because the scope is derived
        # from them: a place is in the export only if an exported
        # event references it. Loading before events would mean
        # emitting the whole PlaceTable on every subset export.
        referenced_place_ids = {e.place_id for e in events if e.place_id}
        places = load_places(
            db.con,
            keep_ids=None if person_ids is None else referenced_place_ids,
        )
        place_strs_pre: tuple[str, ...] = tuple(
            render_place_xml(p, change=ts) for p in places
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
        #
        # Walker reads CitationLinkTable and groups by owner type.
        # A person_ids export filters both the Person bucket (by the
        # requested people) and the Family bucket (by the families
        # those people belong to). The Source bucket is filtered
        # below, once the citations it owns are known.
        person_subset = (
            set(person_ids) if person_ids is not None else None
        )
        citation_links = walk_citation_links(
            db.con,
            person_ids=person_subset,
            family_ids=family_id_set,
        )

        # v2.1 citation narrowing: collect every citation ID referenced
        # by an owner we are actually exporting, then ask the DB which
        # sources those citations parent under.
        #
        # On a subset export the Source and Citation buckets are
        # deliberately excluded. A citation owned by a Source is
        # reachable only from that source, not from any person — so
        # honouring it would drag in every citation of every source in
        # the tree for a two-person export.
        #
        # Citation ids referenced by an owner we are actually
        # exporting. On a subset export, only the Person and Family
        # buckets are filtered — an Event-owned citation is reached
        # through its own event, which is itself in scope via the
        # person's facts.
        buckets = ["Person", "Family", "Event", "Source", "Citation"]
        if person_ids is not None:
            # On a subset export only Person, Family and the events
            # that belong to them are in scope. An event-owned
            # citation is only reachable if its event is exported.
            exported_event_ids = {e.event_id for e in events}
            all_citation_ids: set[int] = set()
            for bucket in ("Person", "Family"):
                for cid_tuple in citation_links[bucket].values():
                    all_citation_ids.update(cid_tuple)
            for ev_id, cid_tuple in citation_links["Event"].items():
                if ev_id in exported_event_ids:
                    all_citation_ids.update(cid_tuple)
        else:
            all_citation_ids = set()
            for bucket in buckets:
                for cid_tuple in citation_links[bucket].values():
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
            keep_ids=None if person_ids is None else all_citation_ids,
        )
        citation_strs: list[str] = [
            render_citation_xml(c, change=ts) for c in citations
        ]
        # No silent failure: AGENTS.md requires surfacing what was not
        # exported.
        #
        # The transcription (ActualText) is exported — as a "Source
        # text" note on the citation, which is where Gramps models a
        # transcription. What has no home is RM's *rendered* citation
        # string: ShortFootnote, Footnote and Bibliography are the
        # output of applying the source template, not source text, and
        # Gramps renders its own from the citation's fields.
        unrendered = sum(
            1
            for c in citations
            if c.short_footnote or c.footnote or c.bibliography
        )
        if unrendered:
            print(
                f"# note: {unrendered} citation(s) carry a rendered "
                f"citation string (ShortFootnote/Footnote/Bibliography); "
                f"those are RootsMagic's own rendering of the source "
                f"template, not source text, so they were not exported. "
                f"Gramps renders its own from the citation's fields. See "
                f"src/rm2gramps/citations.py module docstring.",
                file=sys.stderr,
            )

        # Sources load after citations, narrowed to the ones an
        # exported citation actually parents under. Emitting the whole
        # SourceTable on a subset export ships ~200 sources the
        # researcher did not ask for, and each one is a
        # <citationref> target nothing points at.
        sources = load_sources(
            db.con,
            keep_ids=None if person_ids is None else referenced_source_ids,
        )
        source_strs_pre: list[str] = [
            render_source_xml(s, change=ts) for s in sources
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
        # Events own the single largest citation bucket in RM
        # (CitationLinkTable OwnerType=2 — 604 of 702 rows in
        # SampleTree). Until this injection existed, every one of
        # those citations was emitted with no <citationref> pointing
        # at it.
        event_strs = [
            _inject_citationrefs(xml, citation_links["Event"].get(e.event_id, ()))
            for xml, e in zip(event_strs, events)
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

        # Build (OwnerType, OwnerID) tuples for media narrowing.
        # RM's OwnerType enum is shared across every *LinkTable:
        #     0=Person  2=Event  3=Source  4=Citation
        # (Family 1 is intentionally absent — Gramps <family> can
        # carry media but SampleTree has no MediaLink rows with
        # OwnerType=1.)
        media_owner_ids: set[tuple[int, int]] = set()
        for p in people:
            media_owner_ids.add((0, p.person_id))
        for e in events:
            media_owner_ids.add((2, e.event_id))
        for s in sources:
            media_owner_ids.add((3, s.source_id))
        for c in citations:
            media_owner_ids.add((4, c.citation_id))

        # v2.2: load media + repositories.
        media_records = load_media(db.con, linked_to_owner_ids=media_owner_ids)
        # Repositories are kept only when at least one of their
        # AddressTable addresses is linked to an exported source.
        # AddressLinkTable.OwnerType=3 OwnerIDs are SourceIDs, not
        # CitationIDs (OwnerType 3 = Source in the global enum).
        keep_source_ids = (
            set(s.source_id for s in sources)
            if person_ids is not None else None
        )
        repository_records = load_repositories(
            db.con,
            linked_to_source_ids=keep_source_ids or None,
        )

        # Build owner → media_id map for mediaref injection.
        media_by_owner = media_owner_map(db.con)

        # Build source → repository_id map for reporef injection.
        # AddressLinkTable OwnerType=3 references SourceIDs.
        repo_by_source = address_owner_map(db.con)

        def _noteref_for_owner(
            owner_type: str,
            owner_id: int,
        ) -> tuple[str, ...]:
            entries = note_texts_by_owner.get(owner_type, {}).get(owner_id, [])
            nids: list[int] = []
            for note_type, text in entries:
                nids.extend(
                    note_ids_for_texts(
                        [text], hash_to_id, note_type=note_type,
                    )
                )
            return tuple(note_handle(nid) for nid in nids)

        def _objref_for_owner(
            owner_type: int,
            owner_id: int,
        ) -> tuple[str, ...]:
            mids = media_by_owner.get((owner_type, owner_id), [])
            return tuple(media_handle(mid) for mid in mids)

        def _reporef_for_source(
            source_id: int,
        ) -> tuple[str, ...]:
            aids = repo_by_source.get(source_id, [])
            return tuple(repository_handle(aid) for aid in aids)

        # Apply <noteref> + <mediaref> + <reporef> injection across
        # owner types. <noteref> → 6 owner types. <mediaref> →
        # Person / Source / Citation / Event. <reporef> → Source.
        #
        # These chain from the *already-injected* lists, not from the
        # *_pre originals. Seeding from *_pre would discard every
        # <citationref> injected above — a person whose only
        # cross-reference is a citation would come out referencing
        # nothing.
        people_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Person", p.person_id))
            for xml, p in zip(people_strs, people)
        ]
        family_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Family", f.family_id))
            for xml, f in zip(family_strs, families)
        ]
        source_strs = [
            _attach(xml, "noteref", _noteref_for_owner("Source", s.source_id))
            for xml, s in zip(source_strs, sources)
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

        # <objref> on Person (0), Source (2), Citation (3), Event (4).
        #
        # The element is <objref>, not <mediaref>: the DTD declares no
        # `mediaref`, and each owner's content model lists `objref*`
        # in the slot a media reference belongs in. Order matters —
        # inject_refs appends before the closing tag, so the DTD's
        # declared child sequence (e.g. for <source>: stitle, sauthor,
        # spubinfo, sabbrev, noteref*, objref*, srcattribute*,
        # reporef*, tagref*) is satisfied by the order below.
        people_strs = [
            _attach(
                xml, "objref",
                _objref_for_owner(0, p.person_id),
            )
            for xml, p in zip(people_strs, people)
        ]
        source_strs = [
            _attach(
                xml, "objref",
                _objref_for_owner(2, s.source_id),
            )
            for xml, s in zip(source_strs, sources)
        ]
        citation_strs = [
            _attach(
                xml, "objref",
                _objref_for_owner(3, c.citation_id),
            )
            for xml, c in zip(citation_strs, citations)
        ]
        event_strs = [
            _attach(
                xml, "objref",
                _objref_for_owner(4, e.event_id),
            )
            for xml, e in zip(event_strs, events)
        ]

        # <reporef> on Citation only.
        source_strs = [
            _attach(
                xml, "reporef",
                _reporef_for_source(s.source_id),
            )
            for xml, s in zip(source_strs, sources)
        ]

        # render_media_xml returns "" for rows with no usable file
        # path (an <object> requires a <file> child, and <file>
        # requires a src). Filter those out so they don't land in the
        # <objects> section as blank lines.
        #
        # Every element passes through reorder_children last: the
        # injection passes above append cross-references before the
        # closing tag, which cannot satisfy the DTD's per-element
        # child order (e.g. <person> wants objref before noteref while
        # <event> wants it after).
        return write_database(
            header_date=header_date,
            version="rm2gramps/0.0.1",
            events=tuple(reorder_children(x) for x in event_strs),
            people=tuple(reorder_children(x) for x in people_strs),
            families=tuple(reorder_children(x) for x in family_strs),
            sources=tuple(reorder_children(x) for x in source_strs),
            citations=tuple(reorder_children(x) for x in citation_strs),
            places=tuple(reorder_children(x) for x in place_strs),
            notes=tuple(reorder_children(x) for x in note_strs),
            repositories=tuple(
                reorder_children(render_repository_xml(r, change=ts))
                for r in repository_records
            ),
            media=tuple(
                xml for xml in (
                    reorder_children(render_media_xml(m, change=ts))
                    for m in media_records
                ) if xml
            ),
        )
    finally:
        db.close()


# --- repositories / media -------------------------------------------------


def load_repositories(
    con: sqlite3.Connection,
    *,
    linked_to_source_ids: set[int] | None = None,
) -> list[RepositoryRecord]:
    """Return AddressTable rows whose AddressID is linked to a Source we exported.

    ``linked_to_source_ids`` narrows to the given SourceIDs; ``None``
    returns every address linked to any source. Callers pass the
    set of SourceIDs that survived subset narrowing.

    Decision 3 in the v2.2 plan: any address linked to an exported
    source counts as a repository, regardless of AddressType. The
    walk is ``AddressLinkTable.OwnerType=3`` (Source in the global
    enum) to find the addresses.
    """
    if linked_to_source_ids is not None and not linked_to_source_ids:
        return []
    if linked_to_source_ids is None:
        rows = con.execute(
            """
            SELECT DISTINCT a.AddressID, a.Name, a.Street1, a.City,
                   a.State, a.Zip, a.Country, a.Phone1, a.Email, a.URL
            FROM AddressTable a
            JOIN AddressLinkTable al ON al.AddressID = a.AddressID
            WHERE al.OwnerType = 3
            ORDER BY a.AddressID
            """
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in linked_to_source_ids)
        rows = con.execute(
            f"""
            SELECT DISTINCT a.AddressID, a.Name, a.Street1, a.City,
                   a.State, a.Zip, a.Country, a.Phone1, a.Email, a.URL
            FROM AddressTable a
            JOIN AddressLinkTable al ON al.AddressID = a.AddressID
            WHERE al.OwnerType = 3
              AND al.OwnerID IN ({placeholders})
            ORDER BY a.AddressID
            """,
            list(linked_to_source_ids),
        ).fetchall()
    return [
        RepositoryRecord(
            address_id=r["AddressID"],
            name=r["Name"] or "",
            street1=r["Street1"] or "",
            city=r["City"] or "",
            state=r["State"] or "",
            zip_code=r["Zip"] or "",
            country=r["Country"] or "",
            phone=r["Phone1"] or "",
            email=r["Email"] or "",
            url=r["URL"] or "",
        )
        for r in rows
    ]


def load_media(
    con: sqlite3.Connection,
    *,
    linked_to_owner_ids: set[tuple[int, int]],
) -> list[MediaRecord]:
    """Return MultimediaTable rows whose MediaID is linked to an exported owner.

    Decision 2 in the v2.2 plan: media is narrowed to items
    referenced by exported owners. ``linked_to_owner_ids`` is a
    set of ``(OwnerType, OwnerID)`` tuples — typically built
    from the Person / Source / Citation / Event ids in the
    export scope. ``MediaLinkTable`` OwnerType values match
    those: 0=Person, 1=Family, 2=Source, 3=Citation, 4=Event
    (verified against ``example.gramps`` distribution and the
    SampleTree schema doc).

    Empty set → empty list.
    """
    if not linked_to_owner_ids:
        return []
    # We need a (OwnerType, OwnerID) IN-clause. SQLite supports
    # row-value comparison for this, but to keep it simple we
    # OR together per-type filters.
    placeholders_per_pair = ",".join("(?,?)" for _ in linked_to_owner_ids)
    flat: list = []
    for otype, oid in linked_to_owner_ids:
        flat.extend([otype, oid])
    rows = con.execute(
        f"""
        SELECT DISTINCT m.MediaID, m.MediaFile, m.MediaPath, m.URL,
               m.MediaType, m.Description
        FROM MultimediaTable m
        JOIN MediaLinkTable ml ON ml.MediaID = m.MediaID
        WHERE (ml.OwnerType, ml.OwnerID) IN ({placeholders_per_pair})
        ORDER BY m.MediaID
        """,
        flat,
    ).fetchall()
    return [
        MediaRecord(
            media_id=r["MediaID"],
            media_file=r["MediaFile"] or "",
            media_path=r["MediaPath"] or "",
            url=r["URL"] or "",
            media_type=r["MediaType"] or 0,
            description=r["Description"] or "",
        )
        for r in rows
    ]


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
    """Bulk-fetch ``{owner_id: [(note_type, note_text)]}`` per owner.

    Batched SELECTs; the result maps ``owner_type_key`` (e.g.
    ``"Person"``) → ``{owner_id: [(note_type, text), ...]}``. Missing
    owners get no entry in their type's dict (caller treats that as
    "no notes").

    The type travels with the text because it is part of the note's
    identity: the dedup key is (type, text), so resolving an owner's
    note needs both.
    """
    out: dict[str, dict[int, list[tuple[str, str]]]] = {
        "Person": {}, "Event": {}, "Family": {}, "Source": {},
        "Citation": {}, "Place": {},
    }

    def _bulk(table: str, id_col: str, note_col: str,
              ids: set[int], key: str) -> None:
        if not ids:
            return
        note_type = GRAMPS_NOTE_TYPES[f"{table}.{note_col}"]
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
            out[key].setdefault(r[id_col], []).append((note_type, text))

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
    # Transcriptions. `ActualText` is the researcher's verbatim text
    # of the source and of the specific citation — the material the
    # whole point of a citation is. v2.2 dropped it; Gramps carries
    # it as a "Source text" note on the owner.
    _bulk("SourceTable", "SourceID", "ActualText", source_ids, "Source")
    _bulk("CitationTable", "CitationID", "ActualText",
           citation_ids, "Citation")
    return out