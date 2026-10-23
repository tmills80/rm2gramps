"""Writer-level tests for v3 notes: types, transcriptions, styling.

These run against the real SampleTree.rmtree, because the point of
the v3 work is what happens to *real* RootsMagic data: notes carry a
Gramps type, transcriptions survive as notes, and markup becomes
style ranges rather than literal text.
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rm2gramps.writer import export_database
from ._fixture import sample_tree_path

SAMPLE_TREE = sample_tree_path()

GRAMPS_NS = "http://gramps-project.org/xml/1.7.2/"

pytestmark = pytest.mark.skipif(
    SAMPLE_TREE is None,
    reason=(
        "the RootsMagic sample database is not available; set RM_SAMPLE_TREE "
        "to its path to run these tests"
    ),
)


@pytest.fixture(scope="module")
def exported() -> bytes:
    return export_database(SAMPLE_TREE, change_ts=1700000000)


@pytest.fixture(scope="module")
def root(exported: bytes) -> ET.Element:
    return ET.fromstring(exported)


def _notes(root: ET.Element) -> list[ET.Element]:
    return root.findall(f"{{{GRAMPS_NS}}}notes/{{{GRAMPS_NS}}}note")


def test_every_note_carries_a_gramps_type_name(root: ET.Element) -> None:
    """No custom types.

    Gramps matches the type attribute case-sensitively against its
    own English type names; anything else imports as a custom type.
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
    bad = {
        n.get("type") for n in _notes(root)
        if n.get("type") not in known
    }
    assert not bad, f"notes carry non-Gramps type names: {sorted(bad)}"


def test_no_note_is_still_typed_general(root: ET.Element) -> None:
    """The v2.2 bug: every note was type="general", a custom type."""
    offenders = [n.get("id") for n in _notes(root) if n.get("type") == "general"]
    assert not offenders, f"notes still typed 'general': {offenders[:5]}"


def test_source_transcriptions_are_exported_as_source_text_notes(
    root: ET.Element,
) -> None:
    """SourceTable.ActualText is the researcher's transcription.

    It was dropped in v2.2. Gramps' own tree carries these as
    "Source text" notes on the source.
    """
    source_texts = [
        n for n in _notes(root) if n.get("type") == "Source text"
    ]
    assert source_texts, "no 'Source text' notes exported"


def test_citation_transcriptions_reach_the_citation(
    root: ET.Element,
) -> None:
    """A citation's ActualText must be a note the citation references."""
    citations = root.findall(f"{{{GRAMPS_NS}}}citations/{{{GRAMPS_NS}}}citation")
    assert citations, "no citations exported"
    note_handles = {n.get("handle") for n in _notes(root)}
    with_noteref = [
        c for c in citations
        if any(
            nref.get("hlink") in note_handles
            for nref in c.findall(f"{{{GRAMPS_NS}}}noteref")
        )
    ]
    assert with_noteref, "no citation references any note"


def test_every_noteref_resolves_to_an_emitted_note(root: ET.Element) -> None:
    """A dangling noteref breaks Gramps' import invariants."""
    note_handles = {n.get("handle") for n in _notes(root)}
    dangling: list[str] = []
    for owner in root.iter():
        for nref in owner.findall(f"{{{GRAMPS_NS}}}noteref"):
            if nref.get("hlink") not in note_handles:
                dangling.append(f"{owner.tag} -> {nref.get('hlink')}")
    assert not dangling, f"dangling noterefs: {dangling[:5]}"


def test_every_note_is_referenced_by_something(root: ET.Element) -> None:
    """No orphan notes: a note nothing references is dead weight."""
    note_handles = {n.get("handle") for n in _notes(root)}
    referenced = {
        nref.get("hlink")
        for nref in root.iter(f"{{{GRAMPS_NS}}}noteref")
    }
    orphans = note_handles - referenced
    assert not orphans, f"notes nothing references: {sorted(orphans)[:5]}"


def test_markup_becomes_style_ranges_not_literal_text(
    root: ET.Element,
) -> None:
    """RootsMagic's <b> / <i> must not survive as literal text."""
    for note in _notes(root):
        text_el = note.find(f"{{{GRAMPS_NS}}}text")
        assert text_el is not None
        text = text_el.text or ""
        assert "<b>" not in text, f"literal <b> left in note {note.get('id')}"
        assert "</b>" not in text
        assert "<i>" not in text


def test_style_ranges_stay_inside_their_note_text(root: ET.Element) -> None:
    """A range past the end of the text is a broken note."""
    for note in _notes(root):
        text_el = note.find(f"{{{GRAMPS_NS}}}text")
        length = len(text_el.text or "") if text_el is not None else 0
        for style in note.findall(f"{{{GRAMPS_NS}}}style"):
            ranges = style.findall(f"{{{GRAMPS_NS}}}range")
            assert ranges, f"style without a range in note {note.get('id')}"
            for r in ranges:
                start = int(r.get("start"))
                end = int(r.get("end"))
                assert 0 <= start <= end <= length, (
                    f"note {note.get('id')} range {start}..{end} outside "
                    f"text length {length}"
                )


def test_text_is_not_crlf(root: ET.Element) -> None:
    """XML line-end normalisation: the parser turns CRLF into LF.

    A CRLF in the exported text would mean the note's bytes and the
    ranges over them disagree with what Gramps stores.
    """
    for note in _notes(root):
        text_el = note.find(f"{{{GRAMPS_NS}}}text")
        text = text_el.text or "" if text_el is not None else ""
        assert "\r" not in text, f"CR in note {note.get('id')}"
