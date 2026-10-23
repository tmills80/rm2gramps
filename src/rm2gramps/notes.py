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
inline-note-dedup logic (T25) calls this once per unique note and
discards the result if it's empty.

Note *types* are Gramps' own English type names, spelled exactly as
``gramps/gen/lib/notetype.py`` spells them — Gramps' importer matches
the ``type`` attribute case-sensitively, so a name that is not in its
map imports as a *custom* type instead. ``notes_dedup.GRAMPS_NOTE_TYPES``
maps each RM column to its type.

Note *styling* comes from RootsMagic's ``<b>`` / ``<i>`` markup, via
the shared dialect in ``rmread.rmtext``. A styled note is a
``<text>`` child plus one ``<style>`` child per style, each holding
that style's ranges. The ranges are half-open over the text Gramps
will hold, which is the LF-normalised text: XML line-end
normalisation is mandatory, so a range measured against raw CRLF
would be off by one after the first line break.
"""

from __future__ import annotations

from dataclasses import dataclass

from rmread.rmtext import Span, plain_text

from .handles import format_display_id, note_handle
from .xmlutil import xml_escape

#: Gramps style names this renderer emits, mapped to the value
#: attribute Gramps' own exporter writes for them. Gramps'
#: ``StyledTextTagType.STYLE_TYPE`` gives BOLD and ITALIC a bool
#: value, and its exporter writes the value only when it is truthy —
#: so a bold style is ``value="True"``.
_STYLE_VALUES = {
    "bold": "True",
    "italic": "True",
}


@dataclass(frozen=True)
class NoteRecord:
    """One synthesised note.

    ``note_id`` is a writer-assigned integer (1..N in first-seen
    order of unique notes). ``note_type`` is a Gramps type name from
    ``notes_dedup.GRAMPS_NOTE_TYPES``' vocabulary. ``text`` is the
    raw RootsMagic text; the markup in it is resolved here.
    """

    note_id: int
    text: str
    note_type: str = "General"
    spans: tuple[Span, ...] = ()


def _style_elements(spans: tuple[Span, ...]) -> list[str]:
    """Render one ``<style>`` element per style, in first-seen order.

    Gramps' importer appends every ``<range>`` it reads to the *last*
    ``<style>`` element it has seen, so all of a style's ranges must
    sit under a single ``<style>`` element or they land on the wrong
    style. The DTD also requires at least one range per style.
    """
    grouped: dict[str, list[Span]] = {}
    for span in spans:
        grouped.setdefault(span.style, []).append(span)

    out: list[str] = []
    for style, style_spans in grouped.items():
        value = _STYLE_VALUES.get(style, style_spans[0].value)
        if not value:
            # A style with no value has nothing to say; Gramps' own
            # exporter omits the attribute, and an empty value
            # attribute is worse than none.
            value = None
        parts = [f'<style name="{xml_escape(style)}"']
        if value is not None:
            parts.append(f' value="{xml_escape(value)}"')
        parts.append(">")
        for span in style_spans:
            parts.append(
                f'<range start="{span.start}" end="{span.end}"/>'
            )
        parts.append("</style>")
        out.append("".join(parts))
    return out


def render_note_xml(rec: NoteRecord, *, change: int) -> str:
    """Render one NoteRecord as a Gramps <note> XML string.

    Returns the empty string if ``rec.text`` is empty (caller
    treats this as "skip emission").

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

    resolved = plain_text(rec.text)
    text = resolved.text
    spans = rec.spans or tuple(resolved.spans)

    parts = [
        f'<note handle="{handle}" change="{int(change)}" '
        f'id="{display}" type="{xml_escape(rec.note_type)}">',
        f"<text>{xml_escape(text)}</text>",
    ]
    parts.extend(_style_elements(spans))
    parts.append("</note>")
    return "".join(parts)
