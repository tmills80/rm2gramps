"""SourceTable row → Gramps <source> element.

Pure-function renderer. Takes a :class:`SourceRecord` and returns
the XML string for one <source> element.

Gramps source fields: <stitle> (required), <sauthor> (optional),
<sformat> (default \"book\"), <srepositorylink> (deferred to v2.2
when Repositories land). Private sources get a <priv> wrapper in
Gramps; v2.1 deliberately omits it (documented limitation —
researcher marks private after import).

``change`` is always emitted, including ``change=\"0\"`` for
determinism, mirroring places.py / events.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import format_display_id, source_handle
from .xmlutil import xml_escape


@dataclass(frozen=True)
class SourceRecord:
    """One SourceTable row projected for rendering.

    Full row population (``Fields`` BLOB, ``TemplateID``,
    ``UTCModDate``, etc.) is out of scope for v2.1 — see
    ``tools/rm2gramps/plans/v2.1-citations-and-sources.md`` §
    "Architecture" for what gets surfaced.
    """

    source_id: int
    name: str
    is_private: bool
    author: str = ""
    ref_number: str = ""


def render_source_xml(rec: SourceRecord, *, change: int) -> str:
    """Render one SourceRecord as a Gramps <source> XML string.

    Parameters
    ----------
    rec
        The SourceTable row projected to ``source_id`` + ``name`` +
        ``is_private`` + ``author``.
    change
        Unix-seconds timestamp for the ``change`` attribute.
    """
    handle = source_handle(rec.source_id)
    display = format_display_id(rec.source_id, "S")
    parts = [
        f'<source handle="{handle}" change="{int(change)}" '
        f'id="{display}">'
    ]
    if rec.name:
        parts.append(f"<stitle>{xml_escape(rec.name)}</stitle>")
    if rec.author:
        parts.append(f"<sauthor>{xml_escape(rec.author)}</sauthor>")
    # sformat: hard-coded to "book" — Gramps default. SourceTemplates
    # deferred (no direct Gramps equivalent).
    parts.append("<sformat>book</sformat>")
    parts.append("</source>")
    return "".join(parts)