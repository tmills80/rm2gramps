"""Tests for rm2gramps.events — EventTable row → <event> element.

T4 covers five cases from ``plans/rm2gramps.md`` § T4:

- birth event minimum (the canonical happy path)
- unknown fact type renders as ``Unknown(N)``
- event with no PlaceID omits the <place> child
- event with no date (SortDate=0) omits the <dateval>
- SortDate integer converts to ISO ``dateval val="YYYY-MM-DD"``

The events module accepts an :class:`EventRecord` dataclass (so tests
don't need a live sqlite3 connection) and returns a string of XML
suitable for embedding in the top-level <events> block. The actual
<event> wrapper attributes (handle, change, id) come from
:mod:`rm2gramps.handles`.
"""

from __future__ import annotations

from rm2gramps.events import EventRecord, render_event_xml


def test_birth_event_minimum() -> None:
    """The canonical Birth event round-trips into a Gramps <event>."""
    rec = EventRecord(
        event_id=5,
        event_type=1,
        event_type_name="Birth",
        date="12 JUN 1840",
        sort_date=18400612,
        place_id=3,
        is_primary=True,
        description="",
    )
    xml = render_event_xml(rec, change=1700000000)
    assert xml == (
        '<event handle="_g_e5" change="1700000000" id="E0005">'
        '<type>Birth</type>'
        '<dateval val="1840-06-12"/>'
        '<place hlink="_g_p3"/>'
        '</event>'
    )


def test_unknown_fact_type_renders_as_unknown() -> None:
    """An unknown EventType int renders as <type>Unknown(N)</type>."""
    rec = EventRecord(
        event_id=10,
        event_type=9999,
        event_type_name="Unknown(9999)",
        date="",
        sort_date=None,
        place_id=0,
        is_primary=False,
        description="",
    )
    xml = render_event_xml(rec, change=1700000000)
    assert "<type>Unknown(9999)</type>" in xml
    assert "<dateval" not in xml
    assert "<place" not in xml


def test_event_without_place_omits_place_ref() -> None:
    """PlaceID=0 → no <place> child in the output."""
    rec = EventRecord(
        event_id=2,
        event_type=2,
        event_type_name="Death",
        date="1 JAN 1900",
        sort_date=19000101,
        place_id=0,
        is_primary=False,
        description="",
    )
    xml = render_event_xml(rec, change=1700000000)
    assert "<place" not in xml


def test_event_without_date_omits_dateval() -> None:
    """SortDate=None (or 0) → no <dateval> child in the output."""
    rec = EventRecord(
        event_id=3,
        event_type=18,
        event_type_name="Census",
        date="",
        sort_date=None,
        place_id=4,
        is_primary=False,
        description="",
    )
    xml = render_event_xml(rec, change=1700000000)
    assert "<dateval" not in xml


def test_iso_date_from_sort_date() -> None:
    """SortDate YYYYMMDD → dateval val=\"YYYY-MM-DD\"."""
    rec = EventRecord(
        event_id=4,
        event_type=1,
        event_type_name="Birth",
        date="12 JUN 1840",
        sort_date=18400612,
        place_id=0,
        is_primary=False,
        description="",
    )
    xml = render_event_xml(rec, change=1700000000)
    assert 'dateval val="1840-06-12"' in xml


def test_description_emitted_when_set() -> None:
    """A non-empty description renders as a <description> child."""
    rec = EventRecord(
        event_id=6,
        event_type=26,
        event_type_name="Occupation",
        date="1939",
        sort_date=19390101,
        place_id=5,
        is_primary=False,
        description="Engineers Gauge Maker",
    )
    xml = render_event_xml(rec, change=1700000000)
    assert "<description>Engineers Gauge Maker</description>" in xml


def test_sort_date_zero_treated_as_no_date() -> None:
    """SortDate=0 is equivalent to None for omission purposes."""
    rec = EventRecord(
        event_id=7,
        event_type=18,
        event_type_name="Census",
        date="1939",
        sort_date=0,
        place_id=0,
        is_primary=False,
        description="",
    )
    xml = render_event_xml(rec, change=1700000000)
    assert "<dateval" not in xml