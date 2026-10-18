"""Tests for rm2gramps.places — PlaceTable row → <placeobj> element.

T5 cases from ``tools/rm2gramps/plans/rm2gramps.md`` § T5:

- minimum: PlaceID + Name → <placeobj> with <ptitle> + <pname>
- empty name: PlaceID set, Name="" → <placeobj> with id but no
  <ptitle> or <pname> (researcher fills in Gramps)

Plus the same kind of edge cases the events module has, for parity:
- ``change="0"`` is a valid timestamp and emitted verbatim
- XML-special characters in Name are escaped
"""

from __future__ import annotations

from rm2gramps.places import PlaceRecord, render_place_xml


def test_placeobj_minimum() -> None:
    """The canonical populated place round-trips into a Gramps <placeobj>."""
    rec = PlaceRecord(place_id=5, name="Whipps Cross Hospital")
    xml = render_place_xml(rec, change=1700000000)
    assert xml == (
        '<placeobj handle="_g_p5" change="1700000000" '
        'id="P0005" type="Unknown">'
        "<ptitle>Whipps Cross Hospital</ptitle>"
        '<pname value="Whipps Cross Hospital"/>'
        "</placeobj>"
    )


def test_placeobj_empty_name_keeps_handle_and_id() -> None:
    """Empty Name → placeobj still emitted with handle+id, no <ptitle>/<pname>."""
    rec = PlaceRecord(place_id=42, name="")
    xml = render_place_xml(rec, change=1700000000)
    assert xml == (
        '<placeobj handle="_g_p42" change="1700000000" '
        'id="P0042" type="Unknown">'
        "</placeobj>"
    )
    assert "<ptitle" not in xml
    assert "<pname" not in xml


def test_change_zero_is_emitted_verbatim() -> None:
    """change="0" is valid (means 'never modified'); always emit it."""
    rec = PlaceRecord(place_id=7, name="London")
    xml = render_place_xml(rec, change=0)
    assert 'change="0"' in xml


def test_xml_special_chars_in_name_are_escaped() -> None:
    """The five XML predefined entities must be escaped in <ptitle> and <pname>."""
    rec = PlaceRecord(place_id=9, name='St. Mary & St. John <church> "lower"')
    xml = render_place_xml(rec, change=1700000000)
    # ampersand escaped first (so the & in &lt; etc. doesn't double-escape)
    assert "St. Mary &amp; St. John &lt;church&gt; &quot;lower&quot;" in xml
    assert 'value="St. Mary &amp; St. John &lt;church&gt; &quot;lower&quot;"' in xml