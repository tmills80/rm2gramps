"""EventTable row → Gramps <event> element.

Pure-function renderer: takes a populated :class:`EventRecord` and
returns the XML string for one <event> element. No sqlite3 or
ElementTree dependency at this layer — the caller (the top-level
writer) embeds the returned string in the <events> block.

Date handling: RM stores dates as raw text (``"12 JUN 1840"``) plus a
sortable ``SortDate`` integer (e.g. ``18400612``). We trust SortDate
and emit ISO ``YYYY-MM-DD`` in the <dateval>. When SortDate is zero
(or None), we omit the <dateval> entirely; the raw text is dropped
(unparseable fuzzy dates like ``"BEF 1840"`` are not handled in v1
— see ``tools/rm2gramps/plans/rm2gramps.md`` § "Risks").

Place handling: PlaceID=0 means "no place recorded" and we omit the
<place> child. Real place linkage uses the Gramps handle derived by
:func:`rm2gramps.handles.place_handle`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import event_handle, format_display_id, place_handle
from .xmlutil import xml_escape


@dataclass(frozen=True)
class EventRecord:
    """The columns of an EventTable row that the renderer reads.

    Full row population (UTCModDate, IsPrivate, Status, etc.) is
    intentionally out of scope for v1 — those flow through when we
    wire up a real DB query in a later task.
    """

    event_id: int
    event_type: int
    event_type_name: str
    date: str
    sort_date: int | None
    place_id: int
    is_primary: bool
    description: str


def _iso_from_sort_date(sort_date: int | None) -> str | None:
    """Convert a SortDate int (YYYYMMDD) to ISO YYYY-MM-DD, or None."""
    if not sort_date:
        return None
    s = str(int(sort_date))
    if len(s) != 8:
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def render_event_xml(rec: EventRecord, *, change: int) -> str:
    """Render one EventRecord as a Gramps <event> XML string.

    Parameters
    ----------
    rec
        The EventTable row, projected to the columns this module reads.
    change
        Unix-seconds timestamp for the ``change`` attribute (when the
        record was last touched). Caller supplies this so test
        fixtures stay deterministic.
    """
    parts: list[str] = [
        f'<event handle="{event_handle(rec.event_id)}" '
        f'change="{int(change)}" '
        f'id="{format_display_id(rec.event_id, "E")}">'
    ]
    parts.append(f"<type>{xml_escape(rec.event_type_name)}</type>")

    iso = _iso_from_sort_date(rec.sort_date)
    if iso is not None:
        parts.append(f'<dateval val="{iso}"/>')

    if rec.place_id:
        parts.append(f'<place hlink="{place_handle(rec.place_id)}"/>')

    if rec.description:
        parts.append(f"<description>{xml_escape(rec.description)}</description>")

    parts.append("</event>")
    return "".join(parts)