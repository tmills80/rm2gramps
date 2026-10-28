"""PlaceTable row → Gramps <placeobj> element.

Pure-function renderer: takes a :class:`PlaceRecord` and returns the
XML string for one <placeobj>. Deduplication is the writer's job;
this module renders whatever rows the caller passes in.

Empty Name: we still emit the <placeobj> wrapper (with handle and
id) so that ``<place hlink="..."/>`` references elsewhere resolve,
but omit <ptitle> / <pname>. Gramps flags the empty place as
needing attention.

``change`` attribute: always emitted, including ``change="0"`` for
places with no recorded modification timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import format_display_id, place_handle
from .xmlutil import xml_escape


@dataclass(frozen=True)
class PlaceRecord:
    """The columns of a PlaceTable row that the renderer reads.

    Full row population (PlaceType, MasterID, lat/long, etc.) is
    intentionally out of scope for v1 — see
    ``plans/rm2gramps.md`` § "Slice decision".
    """

    place_id: int
    name: str


def render_place_xml(rec: PlaceRecord, *, change: int) -> str:
    """Render one PlaceRecord as a Gramps <placeobj> XML string.

    Parameters
    ----------
    rec
        The PlaceTable row projected to ``place_id`` + ``name``.
    change
        Unix-seconds timestamp for the ``change`` attribute. The
        caller supplies this so test fixtures stay deterministic.
    """
    handle = place_handle(rec.place_id)
    display = format_display_id(rec.place_id, "P")
    parts = [
        f'<placeobj handle="{handle}" change="{int(change)}" '
        f'id="{display}" type="Unknown">'
    ]
    if rec.name:
        escaped = xml_escape(rec.name)
        parts.append(f"<ptitle>{escaped}</ptitle>")
        parts.append(f'<pname value="{escaped}"/>')
    parts.append("</placeobj>")
    return "".join(parts)