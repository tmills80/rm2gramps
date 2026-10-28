"""Tests for rm2gramps.notes — synthesised note → <note> element.

T22 cases from ``plans/v2.2-notes-media-repositories.md``
§ T22:

- minimum: non-empty text → <note handle=… id=… type=…><text>…</text></note>
- empty text → returns the empty string \"\" (caller skips emission)
- XML special chars in text escaped
- change=0 emitted verbatim
- type attribute set when provided (defaults to \"general\")
"""

from __future__ import annotations

from rm2gramps.handles import note_handle
from rm2gramps.notes import NoteRecord, note_key, render_note_xml


def test_note_minimum() -> None:
    """Single non-empty text → minimum <note>."""
    rec = NoteRecord(note_id=1, text="Free-form research note.", note_type="general")
    xml = render_note_xml(rec, change=1700000000)
    handle = note_handle(note_key("general", "Free-form research note."))
    assert xml == (
        f'<note handle="{handle}" change="1700000000" id="N0001" '
        'type="general">'
        "<text>Free-form research note.</text>"
        "</note>"
    )


def test_note_empty_text_returns_empty_string() -> None:
    """Empty text → empty string; caller decides to skip."""
    rec = NoteRecord(note_id=2, text="", note_type="general")
    assert render_note_xml(rec, change=1700000000) == ""


def test_note_xml_special_chars_escaped() -> None:
    """<, >, &, \", ' are escaped inside <text>."""
    rec = NoteRecord(
        note_id=3,
        text='St Mary <parish> "lower" & church — Müller\'s note',
        note_type="general",
    )
    xml = render_note_xml(rec, change=1700000000)
    assert (
        "<text>St Mary &lt;parish&gt; &quot;lower&quot; "
        "&amp; church — Müller&apos;s note</text>"
    ) in xml


def test_note_change_zero_emitted_verbatim() -> None:
    """change=\"0\" is valid; always emit it."""
    rec = NoteRecord(note_id=4, text="x", note_type="general")
    xml = render_note_xml(rec, change=0)
    assert 'change="0"' in xml


def test_note_with_research_type_attribute() -> None:
    """``type=\"research\"`` (or any other Gramps type) is emitted as-is."""
    rec = NoteRecord(note_id=5, text="Working hypothesis.", note_type="research")
    xml = render_note_xml(rec, change=1700000000)
    assert 'type="research"' in xml
    assert "<text>Working hypothesis.</text>" in xml


def test_note_idempotent_for_same_text() -> None:
    """Two records with the same text render identically aside from handle/id."""
    import re

    rec_a = NoteRecord(note_id=10, text="Same text", note_type="general")
    rec_b = NoteRecord(note_id=11, text="Same text", note_type="general")
    a = render_note_xml(rec_a, change=1)
    b = render_note_xml(rec_b, change=1)

    # Strip the per-record handle / id so we can compare the rest.
    a_norm = re.sub(r'handle="_g_n[0-9a-f]+"', 'handle="X"', a)
    a_norm = re.sub(r'id="N\d+"', 'id="X"', a_norm)
    b_norm = re.sub(r'handle="_g_n[0-9a-f]+"', 'handle="X"', b)
    b_norm = re.sub(r'id="N\d+"', 'id="X"', b_norm)
    assert a_norm == b_norm