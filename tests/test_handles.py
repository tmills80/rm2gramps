"""Tests for rm2gramps.handles — handle and display-id derivation.

These are the first tests in the suite (T2). They are minimal and
deliberately fail until `src/rm2gramps/handles.py` is written.
"""

from rm2gramps.handles import (
    citation_handle,
    event_handle,
    family_handle,
    format_display_id,
    person_handle,
    place_handle,
    source_handle,
)


def test_person_handle_from_uuid() -> None:
    assert person_handle("ABC123") == "_g_abc123"


def test_event_handle_from_id() -> None:
    assert event_handle(123) == "_g_e123"


def test_family_handle_from_id() -> None:
    assert family_handle(7) == "_g_f7"


def test_place_handle_from_id() -> None:
    assert place_handle(45) == "_g_p45"


def test_display_id_format() -> None:
    assert format_display_id(1, "I") == "I0001"
    assert format_display_id(123, "E") == "E0123"
    assert format_display_id(10000, "F") == "F10000"


def test_source_handle_from_id() -> None:
    assert source_handle(5) == "_g_s5"


def test_citation_handle_from_id() -> None:
    assert citation_handle(42) == "_g_c42"


def test_display_id_format_s_and_c() -> None:
    assert format_display_id(1, "S") == "S0001"
    assert format_display_id(42, "C") == "C0042"