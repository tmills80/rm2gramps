"""Tests for rm2gramps.sources — SourceTable row → <source> element.

T12 cases from ``tools/rm2gramps/plans/v2.1-citations-and-sources.md``
§ T12:

- minimum (Name + IsPrivate=0)
- IsPrivate=1 — no XML change in v2.1 (Gramps <priv> wrapper
  intentionally omitted; documented limitation, not a bug)
- empty Name → <source> wrapper with handle+id, no <stitle>
- XML special chars in Name escaped
- change=0 emitted verbatim
"""

from __future__ import annotations

from rm2gramps.sources import SourceRecord, render_source_xml


def test_source_minimum() -> None:
    """Canonical populated source round-trips into a Gramps <source>."""
    rec = SourceRecord(
        source_id=5,
        name="GRO Index",
        is_private=False,
        author="",
        ref_number="",
    )
    xml = render_source_xml(rec, change=1700000000)
    assert xml == (
        '<source handle="_g_s5" change="1700000000" id="S0005">'
        "<stitle>GRO Index</stitle>"
        "<sformat>book</sformat>"
        "</source>"
    )


def test_source_private_emits_no_priv_wrapper() -> None:
    """IsPrivate=True → no XML difference in v2.1.

    Gramps' <priv> wrapper is omitted for v2.1 simplicity; the
    researcher can mark sources private in Gramps after import.
    Documented limitation — see v2.1 plan § "Risks".
    """
    base = dict(source_id=6, name="Private Source",
                author="", ref_number="")
    rec_priv = SourceRecord(**base, is_private=True)
    rec_pub = SourceRecord(**base, is_private=False)
    assert render_source_xml(rec_priv, change=1) == render_source_xml(
        rec_pub, change=1
    )


def test_source_empty_name_keeps_handle_and_id() -> None:
    """Empty Name → <source> wrapper with handle+id, no <stitle>."""
    rec = SourceRecord(
        source_id=8,
        name="",
        is_private=False,
        author="",
        ref_number="",
    )
    xml = render_source_xml(rec, change=1700000000)
    assert xml == (
        '<source handle="_g_s8" change="1700000000" id="S0008">'
        "<sformat>book</sformat>"
        "</source>"
    )
    assert "<stitle" not in xml


def test_source_xml_special_chars_in_name_are_escaped() -> None:
    """The five XML predefined entities must be escaped in <stitle>."""
    rec = SourceRecord(
        source_id=9,
        name='Parish Register "All Saints" <1840> & co.',
        is_private=False,
        author="",
        ref_number="",
    )
    xml = render_source_xml(rec, change=1700000000)
    assert (
        "<stitle>Parish Register &quot;All Saints&quot; "
        "&lt;1840&gt; &amp; co.</stitle>"
    ) in xml


def test_source_change_zero_emitted_verbatim() -> None:
    """change=\"0\" is valid; always emit it."""
    rec = SourceRecord(
        source_id=10,
        name="X",
        is_private=False,
        author="",
        ref_number="",
    )
    xml = render_source_xml(rec, change=0)
    assert 'change="0"' in xml


def test_source_author_emitted_when_set() -> None:
    """Non-empty author renders as <sauthor> child."""
    rec = SourceRecord(
        source_id=11,
        name="Index",
        is_private=False,
        author="Staines St Mary",
        ref_number="",
    )
    xml = render_source_xml(rec, change=1700000000)
    assert "<sauthor>Staines St Mary</sauthor>" in xml


def test_source_ref_number_emitted_when_set() -> None:
    """Non-empty RefNumber renders as <srepositorylink>... no —

    Actually for v2.1 we don't emit RefNumber on the <source>
    itself; that's a citation-level field (<page>). This is the
    negative-space assertion: <srefnumber> must NOT appear in
    v2.1 output even when RefNumber is non-empty.
    """
    rec = SourceRecord(
        source_id=12,
        name="Index",
        is_private=False,
        author="",
        ref_number="p. 24",
    )
    xml = render_source_xml(rec, change=1700000000)
    assert "<srefnumber" not in xml
    assert "p. 24" not in xml