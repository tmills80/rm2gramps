"""Stable handle and display-id derivation for Gramps XML output.

Gramps references objects via string **handles** and short **ids**.
We derive both deterministically from RM identifiers so two exports
of the same database produce byte-equal XML (modulo gzip header).

Handle scheme:
- Person: ``"_g_" + lowercased UniqueID``  (RM UUID, e.g. "B4D8A126...")
- Event:  ``"_g_e" + str(EventID)``
- Family: ``"_g_f" + str(FamilyID)``
- Place:  ``"_g_p" + str(PlaceID)``
- Note:   ``"_g_n" + 12 hex of the note's content key``

Display id scheme: zero-padded 4-digit decimal prefixed by letter
(``"I0001"``, ``"E0123"``). Mirrors Gramps' own export format.
"""

from __future__ import annotations

#: Number of hex characters of a note's content key that go into its
#: handle. 12 hex characters is 48 bits — ample for the note counts a
#: single tree carries, and short enough to read in a diff.
NOTE_HANDLE_HEX = 12


def person_handle(unique_id: str) -> str:
    """Derive a Gramps handle from a PersonTable.UniqueID."""
    return "_g_" + unique_id.lower()


def event_handle(event_id: int) -> str:
    """Derive a Gramps handle from an EventTable.EventID."""
    return f"_g_e{event_id}"


def family_handle(family_id: int) -> str:
    """Derive a Gramps handle from a FamilyTable.FamilyID."""
    return f"_g_f{family_id}"


def place_handle(place_id: int) -> str:
    """Derive a Gramps handle from a PlaceTable.PlaceID."""
    return f"_g_p{place_id}"


def source_handle(source_id: int) -> str:
    """Derive a Gramps handle from a SourceTable.SourceID. (v2.1)"""
    return f"_g_s{source_id}"


def citation_handle(citation_id: int) -> str:
    """Derive a Gramps handle from a CitationTable.CitationID. (v2.1)"""
    return f"_g_c{citation_id}"


def note_handle(note_key: str) -> str:
    """Derive a Gramps handle from a note's content key. (v3.1)

    The key is the sha256 of ``f"{note_type}\\0{text}"`` — the same
    key the inline-note dedup uses. Deriving the handle from the
    content rather than from the note's position in the export means
    a note keeps its identity when the export is re-sorted, narrowed
    to a subset, or gains a new note kind before it.
    """
    return "_g_n" + note_key[:NOTE_HANDLE_HEX]


def media_handle(media_id: int) -> str:
    """Derive a Gramps handle from a MultimediaTable.MediaID. (v2.2)"""
    return f"_g_o{media_id}"


def repository_handle(address_id: int) -> str:
    """Derive a Gramps handle from an AddressTable.AddressID. (v2.2)"""
    return f"_g_r{address_id}"


def format_display_id(numeric_id: int, prefix: str) -> str:
    """Format a Gramps display id like ``I0001`` / ``E0123``."""
    return f"{prefix}{numeric_id:04d}"