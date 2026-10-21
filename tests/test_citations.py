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
        "<confidence>2</confidence>"
        '<sourceref hlink="_g_s5"/>'
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


def test_citation_with_actual_text_is_not_rendered() -> None:
    """Non-empty ActualText is NOT emitted — <citation> has no <text>.

    v2.1 put the transcription in `<text>`, but the DTD declares
    `<!ELEMENT citation ((date)?, page?, confidence, noteref*, objref*,
    srcattribute*, sourceref, tagref*)>` — `text` is not a legal child.
    `<text>` exists only inside `<note>`, which is where Gramps models
    a transcription. The writer warns with the count so the loss is
    never silent (AGENTS.md § "No silent failure").
    """
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
    assert "<text>" not in xml
    assert "Thomas Mills" not in xml


def test_citation_with_short_footnote_is_not_rendered() -> None:
    """Non-empty ShortFootnote is NOT emitted either — same reason.

    There is no legal citation child for it; v2.1 emitted `<text>`,
    which the schema does not permit.
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
    assert "<text>" not in xml
    assert "GRO Index" not in xml


def test_citation_prefers_page_when_both_texts_present() -> None:
    """Page still renders when transcriptions are present but dropped."""
    rec = CitationRecord(
        citation_id=45,
        source_id=5,
        page="p. 211",
        actual_text="Full transcription.",
        short_footnote="Short footnote.",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    assert "<page>p. 211</page>" in xml
    assert "transcription" not in xml
    assert "footnote" not in xml


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
    """Escaping applies to <page> and to attribute values elsewhere."""
    rec = CitationRecord(
        citation_id=47,
        source_id=5,
        page='p. <24> & "note"',
        actual_text="",
        short_footnote="",
        footnote="",
        bibliography="",
    )
    xml = render_citation_xml(rec, change=1700000000)
    # ampersand escaped first so we don't double-escape the & in &lt;
    assert (
        "<page>p. &lt;24&gt; &amp; &quot;note&quot;</page>"
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