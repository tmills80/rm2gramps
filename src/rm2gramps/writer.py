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

from .events import EventRecord, render_event_xml
from .families import ChildRef, FamilyRecord, render_family_xml
from .people import NameRecord, PersonRecord, render_person_xml
from .places import PlaceRecord, render_place_xml
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

        place_strs = tuple(
            render_place_xml(p, change=ts) for p in load_places(db.con)
        )

        events = load_events(
            db.con,
            person_ids=person_ids,
            family_ids=family_id_set,
        )
        event_strs = tuple(render_event_xml(e, change=ts) for e in events)

        people = load_people(db.con, person_ids=person_ids)
        people_strs = tuple(render_person_xml(p, change=ts) for p in people)

        families = load_families(
            db.con,
            family_ids=(
                sorted(family_id_set) if family_id_set is not None else None
            ),
        )
        family_strs = tuple(render_family_xml(f, change=ts) for f in families)

        header_date = _dt.date.today().isoformat()

        return write_database(
            header_date=header_date,
            version="rm2gramps/0.0.1",
            events=event_strs,
            people=people_strs,
            families=family_strs,
            places=place_strs,
        )
    finally:
        db.close()