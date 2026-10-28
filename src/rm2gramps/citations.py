"""CitationTable row → Gramps <citation> element.

Pure-function renderer. Takes a :class:`CitationRecord` and returns
the XML string for one <citation> element.

Gramps 1.7.2 citation shape (per the DTD):
- <page> — from RefNumber when set
- <confidence>2</confidence> — hard-coded (RM has no equivalent)
- <sourceref hlink="…"> — parent source (mandatory; we omit
  only when SourceID=0 and log a warning at the writer layer)
- <noteref> / <objref> — injected later by the writer

There is deliberately **no transcription child**. v2.1 put
``ActualText`` in ``<text>``, but the DTD declares
``<!ELEMENT citation ((daterange|datespan|dateval|datestr)?, page?,
confidence, noteref*, objref*, srcattribute*, sourceref, tagref*)>`` —
``text`` is not among them. ``<text>`` exists in the schema only
inside ``<note>`` (``<!ELEMENT note (text, style*, tagref*)>``), and a
real Gramps export never emits one on a citation. Gramps' own model
is that a transcription is a *note* attached to the citation, which
is where this belongs.

So ``actual_text`` / ``short_footnote`` are not rendered *here*. Where
they go instead:

* ``actual_text`` — the researcher's verbatim transcription of this
  citation — is exported as a ``<note>`` of Gramps type "Source text",
  attached to the citation with a ``<noteref>``. That is where Gramps
  models a transcription, and the writer's note loader takes citation
  transcriptions as inputs.
* ``short_footnote`` / ``footnote`` / ``bibliography`` — RootsMagic's
  *rendered* citation string, the output of applying the source
  template — are not source text and are not exported. Gramps renders
  its own from the citation's own fields. The writer counts the
  citations that carried one and warns once per export, naming the
  count, so nothing is dropped silently.

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
    ``plans/v2.1-citations-and-sources.md`` §
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
    if rec.page:
        parts.append(f"<page>{xml_escape(rec.page)}</page>")
    parts.append("<confidence>2</confidence>")
    if rec.source_id:
        parts.append(f'<sourceref hlink="{source_handle(rec.source_id)}"/>')
    # No <text>: a citation transcription is not a legal child here.
    # See the module docstring — the writer warns with the count.
    parts.append("</citation>")
    return "".join(parts)