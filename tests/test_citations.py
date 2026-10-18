"""Tests for rm2gramps.citations — CitationTable row → <citation> element.

T13 cases from ``tools/rm2gramps/plans/v2.1-citations-and-sources.md``
§ T13:

- minimum (CitationID + SourceID → sourceref)
- page from RefNumber
- ActualText → <text> block (Gramps convention; long
  transcriptions live in <text>, not <description>)
- ShortFootnote → short footnote block
- missing source (SourceID=0) → no <sourceref> (orphan citation;
  warn-and-skip-log at writer layer, but the renderer omits)
- XML escape
- change=0
"""

from __future__ import annotations

from rm2gramps.citations import CitationRecord, render_citation_xml


def test_citation_minimum() -> None:
    """CitationID + SourceID → <sourceref> only."""
    rec = CitationRecord(
        citation_id=42,
        source_id=5,
        page="",
        actual_text="",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert xml == (
        '<citation handle="_g_c42" change="1700000000" id="C0042">'
        '<sourceref hlink="_g_s5"/>'
        "<confidence>2</confidence>"
        "</citation>"
    )


def test_citation_with_page_from_ref_number() -> None:
    """Non-empty page renders as <page> child."""
    rec = CitationRecord(
        citation_id=43,
        source_id=5,
        page="p. 24",
        actual_text="",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert "<page>p. 24</page>" in xml


def test_citation_with_actual_text() -> None:
    """Non-empty ActualText → <text> block. Gramps convention for
    long transcriptions (vs short <description> for snippets)."""
    rec = CitationRecord(
        citation_id=44,
        source_id=5,
        page="",
        actual_text="Thomas Mills, son of John, baptised 12 JUN 1840.",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert (
        "<text>Thomas Mills, son of John, baptised 12 JUN 1840.</text>"
    ) in xml


def test_citation_with_short_footnote() -> None:
    """Non-empty ShortFootnote renders as a <text> block (v2.1).

    Gramps 1.7.2 has no separate 'short footnote' element on
    citations; we emit ShortFootnote as <text> only when
    ActualText is empty (otherwise <text> would carry the
    transcription and the short footnote would be lost). v2.2
    will lift short_footnote into a proper <noteref> once notes
    land.
    """
    rec = CitationRecord(
        citation_id=45,
        source_id=5,
        page="",
        actual_text="",
        short_footnote="GRO Index, vol. XVI, p. 211",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert "<text>GRO Index, vol. XVI, p. 211</text>" in xml


def test_citation_short_footnote_skipped_when_actual_text_set() -> None:
    """ShortFootnote is dropped when ActualText is also set.

    Avoids double-emitting <text> — the more substantive
    ActualText wins. v2.2 will lift short_footnote into its own
    element.
    """
    rec = CitationRecord(
        citation_id=45,
        source_id=5,
        page="",
        actual_text="Full transcription wins.",
        short_footnote="Short footnote should be dropped.",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert "<text>Full transcription wins.</text>" in xml
    assert "Short footnote should be dropped" not in xml


def test_citation_missing_source_emits_no_sourceref() -> None:
    """SourceID=0 → no <sourceref>; the writer logs the orphan."""
    rec = CitationRecord(
        citation_id=46,
        source_id=0,
        page="",
        actual_text="",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert "<sourceref" not in xml
    # But the wrapper + handle + id still emit (so citationrefs
    # to it from owners still resolve to a defined object).
    assert 'handle="_g_c46"' in xml
    assert 'id="C0046"' in xml


def test_citation_xml_special_chars_escaped() -> None:
    """Escaping applies to <text> and <page> and short_footnote body."""
    rec = CitationRecord(
        citation_id=47,
        source_id=5,
        page='p. <24> & "note"',
        actual_text="Müller & Søn <test> 'apos'",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    # ampersand escaped first so we don't double-escape the & in &lt;
    assert (
        "<page>p. &lt;24&gt; &amp; &quot;note&quot;</page>"
    ) in xml
    assert (
        "<text>Müller &amp; Søn &lt;test&gt; &apos;apos&apos;</text>"
    ) in xml


def test_citation_change_zero_emitted_verbatim() -> None:
    """change=\"0\" is valid; always emit it."""
    rec = CitationRecord(
        citation_id=48,
        source_id=5,
        page="",
        actual_text="",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=0)
    assert 'change="0"' in xml


def test_citation_confidence_is_hard_coded() -> None:
    """<confidence>2</confidence> is hard-coded for v2.1.

    RM's CitationLinkTable.Quality is text not int; no direct
    Gramps-confidence equivalent. v2.1 always emits 2 (normal);
    researcher adjusts in Gramps. Documented limitation.
    """
    rec = CitationRecord(
        citation_id=49,
        source_id=5,
        page="",
        actual_text="",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert "<confidence>2</confidence>" in xml