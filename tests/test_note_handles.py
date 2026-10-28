"""Content-derived note handles (v3.1).

A note's handle must be a property of the note's *content*, not of
its position in the export. Under the v2.2/v3 scheme the handle was
``_g_n<note_id>``, assigned in first-seen order: adding a note kind
renumbered every note after it, and a subset export numbered its
notes differently from a full one. A researcher diffing two exports
could not tell whether a note changed or merely moved.

The handle is now ``_g_n`` + the first 12 hex characters of the
sha256 of ``f"{note_type}\\0{text}"`` — the same key the dedup uses.

These tests cover the derivation (unit) and the property that
matters in practice (integration, against the real SampleTree):
the same note carries the same handle in a full export and in a
subset export.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from rm2gramps.handles import note_handle
from rm2gramps.notes import NoteRecord, note_key, render_note_xml
from rm2gramps.writer import export_database
from ._fixture import sample_tree_path

SAMPLE_TREE = sample_tree_path()

GRAMPS_NS = "http://gramps-project.org/xml/1.7.2/"

#: A note handle: "_g_n" + 12 lowercase hex characters.
NOTE_HANDLE_RE = re.compile(r"^_g_n[0-9a-f]{12}$")


# --------------------------------------------------------------------------
# Unit: the derivation itself
# --------------------------------------------------------------------------


def test_note_handle_is_twelve_hex_of_the_content_key() -> None:
    """The handle is the content key, truncated — nothing else."""
    key = note_key("Person Note", "A research note.")
    assert note_handle(key) == "_g_n" + key[:12]
    assert NOTE_HANDLE_RE.match(note_handle(key))


def test_same_text_under_two_types_gets_two_handles() -> None:
    """Type is part of the note's identity, so it is part of the handle."""
    as_citation = note_handle(note_key("Citation", "Only father"))
    as_source_text = note_handle(note_key("Source text", "Only father"))
    assert as_citation != as_source_text


def test_different_text_gets_different_handles() -> None:
    assert note_handle(note_key("General", "One")) != note_handle(
        note_key("General", "Two")
    )


def test_same_text_gets_the_same_handle() -> None:
    assert note_handle(note_key("General", "One")) == note_handle(
        note_key("General", "One")
    )


def test_rendered_handle_follows_the_text_not_the_note_id() -> None:
    """Two records with identical content render identical handles.

    The display id still differs (``N0001`` vs ``N0042``) — nothing
    references it — but the handle is the same, so a note that moves
    in the export keeps its identity.
    """
    first = render_note_xml(
        NoteRecord(note_id=1, text="Same text", note_type="General"), change=1
    )
    later = render_note_xml(
        NoteRecord(note_id=42, text="Same text", note_type="General"), change=1
    )
    handle_re = re.compile(r'handle="(_g_n[0-9a-f]{12})"')
    first_handle = handle_re.search(first)
    later_handle = handle_re.search(later)
    assert first_handle is not None and later_handle is not None
    assert first_handle.group(1) == later_handle.group(1)
    # The display ids still differ — they are labels, not identity.
    assert 'id="N0001"' in first
    assert 'id="N0042"' in later


# --------------------------------------------------------------------------
# Integration: the real sample tree
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    SAMPLE_TREE is None,
    reason=(
        "the RootsMagic sample database is not available; set RM_SAMPLE_TREE "
        "to its path to run these tests"
    ),
)
def test_exported_note_handles_are_content_derived() -> None:
    """Every exported note handle matches the content-derived shape."""
    root = ET.fromstring(export_database(SAMPLE_TREE, change_ts=1700000000))
    notes = root.findall(f"{{{GRAMPS_NS}}}notes/{{{GRAMPS_NS}}}note")
    assert notes, "no notes exported"
    bad = [
        n.get("handle") for n in notes
        if not NOTE_HANDLE_RE.match(n.get("handle") or "")
    ]
    assert not bad, f"handles are not content-derived: {bad[:5]}"


@pytest.mark.skipif(
    SAMPLE_TREE is None,
    reason=(
        "the RootsMagic sample database is not available; set RM_SAMPLE_TREE "
        "to its path to run these tests"
    ),
)
def test_note_handles_are_unique() -> None:
    """Two notes must never share a handle."""
    root = ET.fromstring(export_database(SAMPLE_TREE, change_ts=1700000000))
    handles = [
        n.get("handle")
        for n in root.findall(f"{{{GRAMPS_NS}}}notes/{{{GRAMPS_NS}}}note")
    ]
    assert len(handles) == len(set(handles)), (
        "duplicate note handles in the export"
    )


@pytest.mark.skipif(
    SAMPLE_TREE is None,
    reason=(
        "the RootsMagic sample database is not available; set RM_SAMPLE_TREE "
        "to its path to run these tests"
    ),
)
def test_a_note_keeps_its_handle_across_a_subset_export() -> None:
    """The headline property: subset export, same handle.

    Under the old scheme a subset export renumbered its notes from
    1, so the same note carried a different handle in the two exports
    and the two files could not be diffed against each other.
    """
    def note_map(person_ids: list[int] | None) -> dict[tuple[str, str], str]:
        root = ET.fromstring(
            export_database(
                SAMPLE_TREE,
                person_ids=person_ids,
                change_ts=1700000000,
            )
        )
        out: dict[tuple[str, str], str] = {}
        for note in root.findall(f"{{{GRAMPS_NS}}}notes/{{{GRAMPS_NS}}}note"):
            text_el = note.find(f"{{{GRAMPS_NS}}}text")
            out[(note.get("type") or "", text_el.text or "")] = (
                note.get("handle") or ""
            )
        return out

    full = note_map(None)
    subset = note_map([1, 2, 3])

    assert subset, "the subset export produced no notes"
    for key, handle in subset.items():
        assert key in full, (
            f"note {handle} in the subset export is absent from the full "
            f"export"
        )
        assert full[key] == handle, (
            f"note {handle} has a different handle in the full export "
            f"({full[key]}) — handles are not stable across exports"
        )
