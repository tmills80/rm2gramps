"""PersonTable + NameTable rows → Gramps <person> element.

Pure-function renderer. Takes a :class:`PersonRecord` plus the
per-person data the writer assembles (event refs, parent families,
families-as-parent, alt names) and returns one <person> XML string.

Gender mapping: RM ``Sex`` is 0/1/2 (unknown/male/female); Gramps
``<gender>`` is U/M/F. Straight map.

Alt names: ``NameTable.NameType`` values 0 (Birth Name) / 1 (Married
Name) / 2 (Alias) / 3 (Immigrant) / 4 (Maiden) etc. The first row
(NameType=0) is always the primary name and renders as
``<name type="Birth Name">``; alt rows are mapped via
:data:`_NAME_TYPE_MAP`.

Family links:
- ``<childof hlink="..."/>`` — one per family where this Person is
  a child (ChildTable → FamilyTable.FatherID/MotherID walk). The
  writer passes a tuple of family IDs.
- ``<parentin hlink="..."/>`` — one per family where this Person is
  a parent (FamilyTable.FatherID == person OR MotherID == person).
  Writer passes a tuple of family IDs.

Event refs: tuple of ``(event_id, is_primary)`` pairs; the writer
sorts by SortDate. ``is_primary`` mirrors EventTable.IsPrimary and
drives the ``role=\"Primary\"`` attribute on the <eventref>.

``_UID`` attribute on each person holds the RM UniqueID so a
round-trip from Gramps back into rm2gramps can resolve a person to
the same RM record.
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import (
    event_handle,
    family_handle,
    format_display_id,
    person_handle,
)
from .xmlutil import xml_escape


# RM NameType int → Gramps <name type="..."> string.
# Source: RM's NameTable spec; values RM ships today include 0
# (birth/primary), 1 (married), 2 (alias), 3 (immigrant), 4 (maiden).
# Anything outside the map falls back to "Also Known As".
_NAME_TYPE_MAP: dict[int, str] = {
    0: "Birth Name",
    1: "Married Name",
    2: "Also Known As",
    3: "Also Known As",
    4: "Maiden Name",
}


# RM Sex int → Gramps <gender> single letter.
_SEX_MAP: dict[int, str] = {
    0: "U",   # unknown
    1: "M",   # male
    2: "F",   # female
}


@dataclass(frozen=True)
class NameRecord:
    """One NameTable row projected for rendering.

    ``name_type`` drives the ``<name type=\"…\">`` attribute when
    this is an alt name; for the primary name it should always be 0
    and the renderer hard-codes ``Birth Name`` for that case.
    """

    surname: str
    given: str
    prefix: str
    suffix: str
    name_type: int = 0
    is_primary: bool = False


@dataclass(frozen=True)
class PersonRecord:
    """One PersonTable row plus the per-person data the renderer reads."""

    person_id: int
    unique_id: str
    sex: int
    primary_name: NameRecord
    alt_names: tuple[NameRecord, ...]
    event_refs: tuple[tuple[int, bool], ...]   # (event_id, is_primary)
    parent_families: tuple[int, ...]            # family IDs where this person is a child
    child_families: tuple[int, ...]             # family IDs where this person is a parent


def _render_name(name: NameRecord, *, is_primary: bool) -> str:
    """Render one <name type=\"…\">…</name> block."""
    if is_primary:
        type_str = "Birth Name"
    else:
        type_str = _NAME_TYPE_MAP.get(name.name_type, "Also Known As")
    parts = [f'<name type="{type_str}">']
    if name.given:
        parts.append(f"<first>{xml_escape(name.given)}</first>")
    if name.surname:
        parts.append(f"<surname>{xml_escape(name.surname)}</surname>")
    parts.append("</name>")
    return "".join(parts)


def render_person_xml(rec: PersonRecord, *, change: int) -> str:
    """Render one PersonRecord as a Gramps <person> XML string.

    Parameters
    ----------
    rec
        The PersonTable row + name data + family / event links.
    change
        Unix-seconds timestamp for the ``change`` attribute.
    """
    gender = _SEX_MAP.get(rec.sex, "U")

    parts: list[str] = [
        f'<person handle="{person_handle(rec.unique_id)}" '
        f'change="{int(change)}" '
        f'id="{format_display_id(rec.person_id, "I")}">'
        f"<gender>{gender}</gender>"
    ]

    # primary name first, then alts
    parts.append(_render_name(rec.primary_name, is_primary=True))
    for alt in rec.alt_names:
        parts.append(_render_name(alt, is_primary=False))

    for ev_id, is_primary in rec.event_refs:
        hlink = event_handle(ev_id)
        if is_primary:
            parts.append(f'<eventref hlink="{hlink}" role="Primary"/>')
        else:
            parts.append(f'<eventref hlink="{hlink}"/>')

    for fid in rec.parent_families:
        parts.append(f'<childof hlink="{family_handle(fid)}"/>')
    for fid in rec.child_families:
        parts.append(f'<parentin hlink="{family_handle(fid)}"/>')

    # _UID attribute carries the RM UniqueID verbatim so a round-trip
    # from Gramps back into rm2gramps can resolve a person to the
    # same RM record.
    parts.append(f'<attribute type="_UID" value="{xml_escape(rec.unique_id)}"/>')

    parts.append("</person>")
    return "".join(parts)