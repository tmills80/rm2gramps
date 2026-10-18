"""Stable handle and display-id derivation for Gramps XML output.

Gramps references objects via string **handles** and short **ids**.
We derive both deterministically from RM identifiers so two exports
of the same database produce byte-equal XML (modulo gzip header).

Handle scheme:
- Person: ``"_g_" + lowercased UniqueID``  (RM UUID, e.g. "B4D8A126...")
- Event:  ``"_g_e" + str(EventID)``
- Family: ``"_g_f" + str(FamilyID)``
- Place:  ``"_g_p" + str(PlaceID)``

Display id scheme: zero-padded 4-digit decimal prefixed by letter
(``"I0001"``, ``"E0123"``). Mirrors Gramps' own export format.
"""

from __future__ import annotations


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


def format_display_id(numeric_id: int, prefix: str) -> str:
    """Format a Gramps display id like ``I0001`` / ``E0123``."""
    return f"{prefix}{numeric_id:04d}"