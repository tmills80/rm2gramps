"""FamilyTable row → Gramps <family> element.

Pure-function renderer. Takes a :class:`FamilyRecord` plus the
per-family children and family-attached event ids (assembled by the
writer from a live sqlite3 query) and returns the XML string for one
<family> element.

Relationship type: ``<rel type="Married"/>`` is emitted only when
both a father and a mother are present. Single-parent and no-parent
families emit ``<rel type="Unknown"/>`` — RM has no equivalent
field, and the researcher can override in Gramps.

Children: the caller's :class:`ChildRef` list is rendered in order
(the writer is responsible for sorting by ``ChildTable.ChildOrder``
when it queries). Each childref handle is derived from the child's
RM UniqueID (not the ChildID — ChildID is a junction-table id).

Family events: ``OwnerType=1`` events attached to a family render as
``<eventref role="Family">`` (distinct from the ``Primary`` role
used for events on persons).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChildRef:
    """One row of ``ChildTable`` projected for rendering.

    ``child_uid`` is the linked PersonTable.UniqueID — the childref
    handle is derived from this, not from ``child_id`` (which is the
    ``ChildTable.RecID`` for that junction row).
    """

    child_id: int
    child_uid: str
    child_order: int


@dataclass(frozen=True)
class FamilyRecord:
    """One FamilyTable row plus the children + events the renderer needs.

    ``father_uid`` / ``mother_uid`` are the parent PersonTable
    UniqueIDs. ``father_id`` / ``mother_id`` are the integer
    PersonIDs (kept for the writer's audit / debugging, not used by
    the renderer). Empty UniqueID string means "no parent recorded".
    """

    family_id: int
    father_uid: str
    mother_uid: str
    father_id: int
    mother_id: int
    children: tuple[ChildRef, ...]
    family_event_ids: tuple[int, ...]


def render_family_xml(rec: FamilyRecord, *, change: int) -> str:
    """Render one FamilyRecord as a Gramps <family> XML string.

    Parameters
    ----------
    rec
        The FamilyTable row + children + family-event ids.
    change
        Unix-seconds timestamp for the ``change`` attribute.
    """
    from .handles import (
        event_handle,
        family_handle,
        format_display_id,
        person_handle,
    )

    parts: list[str] = [
        f'<family handle="{family_handle(rec.family_id)}" '
        f'change="{int(change)}" '
        f'id="{format_display_id(rec.family_id, "F")}">'
    ]

    # Relationship: Married iff both parents present, else Unknown.
    rel_type = "Married" if rec.father_uid and rec.mother_uid else "Unknown"
    parts.append(f'<rel type="{rel_type}"/>')

    if rec.father_uid:
        parts.append(f'<father hlink="{person_handle(rec.father_uid)}"/>')
    if rec.mother_uid:
        parts.append(f'<mother hlink="{person_handle(rec.mother_uid)}"/>')

    for child in rec.children:
        parts.append(f'<childref hlink="{person_handle(child.child_uid)}"/>')

    for ev_id in rec.family_event_ids:
        parts.append(f'<eventref hlink="{event_handle(ev_id)}" role="Family"/>')

    parts.append("</family>")
    return "".join(parts)