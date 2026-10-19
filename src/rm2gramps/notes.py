"""Inline-note text → Gramps <note> element.

Pure-function renderer. Takes a :class:`NoteRecord` and returns the
XML string for one <note> element, or the empty string if the
text is empty (the caller skips emission in that case).

The ``NoteRecord`` is synthesised by the writer from inline RM
``Note TEXT`` columns on Person / Event / Family / Source / Place
/ Citation. RM has no separate NoteTable — see
``tools/rm2gramps/plans/v2.2-notes-media-repositories.md`` §
"Decision 1" for why.

Empty text returns the empty string. The writer's
inline-note-dedup logic (T25) calls this once per unique
sha256(text) hash and discards the result if it's empty.

Notes always emit ``type=\"…\"`` with a default of \"general\".
Gramps' controlled vocabulary includes general, research, source,
transcriptoria, etc.; v2.2 trusts whatever the writer passes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import format_display_id, note_handle
from .xmlutil import xml_escape


@dataclass(frozen=True)
class NoteRecord:
    """One synthesised note.

    ``note_id`` is a writer-assigned integer (1..N in first-seen
    order of unique ``text`` values). ``note_type`` is a Gramps
    controlled-vocabulary string; default \"general\" works for the
    vast majority of inline RM notes.
    """

    note_id: int
    text: str
    note_type: str = "general"


def render_note_xml(rec: NoteRecord, *, change: int) -> str:
    """Render one NoteRecord as a Gramps <note> XML string.

    Returns the empty string if ``rec.text`` is empty (caller
    treats this as \"skip emission\").

    Parameters
    ----------
    rec
        The synthesised note.
    change
        Unix-seconds timestamp for the ``change`` attribute.
    """
    if not rec.text:
        return ""
    handle = note_handle(rec.note_id)
    display = format_display_id(rec.note_id, "N")
    parts = [
        f'<note handle="{handle}" change="{int(change)}" '
        f'id="{display}" type="{xml_escape(rec.note_type)}">'
        f"<text>{xml_escape(rec.text)}</text>"
        "</note>"
    ]
    return "".join(parts)