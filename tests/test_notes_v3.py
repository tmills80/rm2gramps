"""Tests for rm2gramps v3 — typed notes, transcriptions, styling.

Three defects in v2.2's notes, one file:

* every note was written ``type="general"``, which is not a Gramps
  type name — Gramps' importer matches the ``type`` attribute
  case-sensitively against Gramps' own English type names, so
  ``"general"`` lands as a *custom* type called "general";
* source and citation transcriptions (``ActualText``) were dropped;
* RootsMagic's ``<b>`` / ``<i>`` markup was escaped into the note
  text as literal markup.
"""

from __future__ import annotations

import re

from rm2gramps.notes import NoteRecord, render_note_xml
from rm2gramps.notes_dedup import GRAMPS_NOTE_TYPES, note_key


def _note_xml(text: str, note_type: str) -> str:
    return render_note_xml(NoteRecord(note_id=1, text=text, note_type=note_type),
                            change=1700000000)


# --- typing -------------------------------------------------------------

def test_person_note_carries_the_gramps_person_note_type() -> None:
    assert 'type="Person Note"' in _note_xml("x", "Person Note")


def test_every_gramps_note_type_is_one_gramps_actually_knows() -> None:
    """The type strings must be Gramps' own, not invented.

    Gramps' importer looks the ``type`` attribute up in a map keyed on
    the English type names from ``gramps/gen/lib/notetype.py``. A name
    that is not in that map imports as a custom type, silently.
    """
    known = {
        "General", "Research", "Transcript", "Source text", "Citation",
        "Report", "Html code", "To Do", "Link", "Analysis",
        "Person Note", "Name Note", "Attribute Note", "Address Note",
        "Association Note", "LDS Note", "Family Note", "Event Note",
        "Event Reference Note", "Source Note", "Source Reference Note",
        "Place Note", "Repository Note", "Repository Reference Note",
        "Media Note", "Media Reference Note", "Child Reference Note",
    }
    for column, note_type in GRAMPS_NOTE_TYPES.items():
        assert note_type in known, (
            f"{column} maps to {note_type!r}, which is not a Gramps note "
            f"type name -- it would import as a custom type"
        )


def test_each_rm_note_column_maps_to_a_gramps_type() -> None:
    assert GRAMPS_NOTE_TYPES["PersonTable.Note"] == "Person Note"
    assert GRAMPS_NOTE_TYPES["EventTable.Note"] == "Event Note"
    assert GRAMPS_NOTE_TYPES["FamilyTable.Note"] == "Family Note"
    assert GRAMPS_NOTE_TYPES["PlaceTable.Note"] == "Place Note"
    assert GRAMPS_NOTE_TYPES["SourceTable.Comments"] == "Source Note"
    assert GRAMPS_NOTE_TYPES["SourceTable.ActualText"] == "Source text"
    assert GRAMPS_NOTE_TYPES["CitationTable.Comments"] == "Citation"
    assert GRAMPS_NOTE_TYPES["CitationTable.ActualText"] == "Source text"


# --- dedup key ----------------------------------------------------------

def test_same_text_under_different_types_is_a_different_note() -> None:
    """Type is part of a note's identity.

    "Only father" exists in SampleTree as both a ``Citation`` and a
    ``Source text``. Collapsing them would give one of the two the
    wrong Gramps type.
    """
    assert note_key("Citation", "Only father") != note_key(
        "Source text", "Only father"
    )


def test_same_type_and_text_is_the_same_note() -> None:
    assert note_key("Citation", "Only father") == note_key(
        "Citation", "Only father"
    )


# --- styling ------------------------------------------------------------

def test_bold_markup_becomes_a_style_with_a_range() -> None:
    xml = _note_xml("<b>Surname</b> District Page", "Source text")
    # The text carries no literal markup...
    assert "<b>" not in xml
    assert "&lt;b&gt;" not in xml
    # ...and the style says where the bold run is.
    assert '<style name="bold" value="True">' in xml
    assert '<range start="0" end="7"/>' in xml


def test_style_comes_after_the_text_in_dtd_order() -> None:
    """The DTD declares ``note`` as ``(text, style*, tagref*)``."""
    xml = _note_xml("<b>Surname</b>", "Source text")
    assert xml.index("<text>") < xml.index("<style")


def test_each_style_gets_one_style_element() -> None:
    """Gramps' importer appends each <range> to the *last* <style>.

    So all of a style's ranges must sit under one <style> element, or
    the ranges land on the wrong style.
    """
    xml = _note_xml("<b>aaa</b> <b>bbb</b>", "Source text")
    assert xml.count('<style name="bold"') == 1
    # ...with both ranges under it.
    assert xml.count("<range ") == 2


def test_italic_markup_becomes_an_italic_style() -> None:
    xml = _note_xml("<i>plain</i> text", "Source text")
    assert "<i>" not in xml
    assert '&lt;i&gt;' not in xml
    assert '<style name="italic" value="True">' in xml
    assert '<range start="0" end="5"/>' in xml


def test_unknown_tag_survives_as_literal_text() -> None:
    """RootsMagic stores note text raw, so "<" may be the researcher's.

    Dropping an unknown tag would silently delete transcription text.
    """
    xml = _note_xml("by me <assistant curate>", "Source text")
    assert "&lt;assistant curate&gt;" in xml


def test_crlf_is_normalised_and_ranges_measure_the_normalised_text() -> None:
    """XML line-end normalisation is mandatory.

    Gramps stores what the parser hands it, and the parser turns CRLF
    into LF. A range measured against raw CRLF text would be off by
    one after the first line break.
    """
    xml = _note_xml("one\r\ntwo <b>x</b>", "Source text")
    assert "\r" not in xml
    assert "<text>one\ntwo x</text>" in xml
    # "x" is at index 8 of the normalised text.
    assert '<range start="8" end="9"/>' in xml


def test_range_never_exceeds_the_text_length() -> None:
    xml = _note_xml("one\r\ntwo <b>x</b>", "Source text")
    text = re.search(r"<text>(.*?)</text>", xml, re.S).group(1)
    for start, end in re.findall(r'<range start="(\d+)" end="(\d+)"/>', xml):
        assert int(end) <= len(text), (
            f"range {start}..{end} exceeds text length {len(text)}"
        )
