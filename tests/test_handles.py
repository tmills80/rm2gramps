"""Tests for rm2gramps.handles — handle and display-id derivation.

These are the first tests in the suite (T2). They are minimal and
deliberately fail until `src/rm2gramps/handles.py` is written.
"""

from rm2gramps.handles import (
    event_handle,
    family_handle,
    format_display_id,
    person_handle,
    place_handle,
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