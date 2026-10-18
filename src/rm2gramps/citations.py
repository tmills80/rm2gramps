"""CitationTable row → Gramps <citation> element.

Pure-function renderer. Takes a :class:`CitationRecord` and returns
the XML string for one <citation> element.

Gramps 1.7.2 citation shape:
- <sourceref hlink=\"...\"> — parent source (mandatory; we omit
  only when SourceID=0 and log a warning at the writer layer)
- <confidence>2</confidence> — hard-coded (RM has no equivalent)
- <page> — from RefNumber when set
- <text> — long transcription (ActualText) and / or pre-rendered
  ShortFootnote. Both go here in v2.1; v2 could split into
  <text> (ActualText) + <noteref hlink> (ShortFootnote once
  notes land) if Gramps conventions demand it.

SourceFields BLOB and CitationFields BLOB are ignored (RM
internal serialisation, not portable to Gramps XML).
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import citation_handle, format_display_id, source_handle
from .xmlutil import xml_escape


@dataclass(frozen=True)
class CitationRecord:
    """One CitationTable row projected for rendering.

    Full row population (``Comments``, ``Fields`` BLOB,
    ``UTCModDate``, etc.) is out of scope for v2.1 — see
    ``tools/rm2gramps/plans/v2.1-citations-and-sources.md`` §
    "Architecture".
    """

    citation_id: int
    source_id: int
    page: str = ""
    actual_text: str = ""
    short_footnote: str = ""
    footnote: str = ""
    bibliography: str = ""


def render_citation_xml(rec: CitationRecord, *, change: int) -> str:
    """Render one CitationRecord as a Gramps <citation> XML string.

    Parameters
    ----------
    rec
        The CitationTable row projected to ``citation_id`` +
        ``source_id`` + page / text / footnote strings.
    change
        Unix-seconds timestamp for the ``change`` attribute.
    """
    parts: list[str] = [
        f'<citation handle="{citation_handle(rec.citation_id)}" '
        f'change="{int(change)}" '
        f'id="{format_display_id(rec.citation_id, "C")}">'
    ]
    if rec.source_id:
        parts.append(f'<sourceref hlink="{source_handle(rec.source_id)}"/>')
    parts.append("<confidence>2</confidence>")
    if rec.page:
        parts.append(f"<page>{xml_escape(rec.page)}</page>")
    if rec.actual_text:
        parts.append(f"<text>{xml_escape(rec.actual_text)}</text>")
    elif rec.short_footnote:
        # Short_footnote falls back into <text> only when actual_text
        # is absent — both going into <text> would double-emit the
        # element. v2.2 (notes) will lift short_footnote into a
        # proper <noteref>.
        parts.append(f"<text>{xml_escape(rec.short_footnote)}</text>")
    parts.append("</citation>")
    return "".join(parts)