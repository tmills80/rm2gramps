"""Tests for rm2gramps.media — MultimediaTable row → <object> element.

T23 cases from ``plans/v2.2-notes-media-repositories.md``
§ T23:

- minimum: MediaID + MediaFile + MediaPath + MediaType=1 (image) →
  <object handle=… id=…><file src=\"…\" mime=\"image/jpeg\"/><description>…</description></object>
- web URL: ``URL=\"https://…\"`` with empty MediaPath → <file src=URL mime=…>
- MediaType=2 → mime=\"application/pdf\"; 3=audio/mpeg; 4=video/mp4
- unknown MediaType → application/octet-stream fallback
- empty path AND empty URL → wrapper only, no <file> child
- XML escape
- change=0

Thumbnail BLOBs are intentionally dropped (Decision 6 in v2.2 plan)
— re-extracted by Gramps on import from the file path.
"""

from __future__ import annotations

from rm2gramps.media import MediaRecord, render_media_xml


def test_media_minimum() -> None:
    """Canonical populated media → minimum <object>."""
    rec = MediaRecord(
        media_id=1,
        media_file="scan.jpg",
        media_path="/Users/x/RM/scan.jpg",
        url="",
        media_type=1,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert xml == (
        '<object handle="_g_o1" change="1700000000" id="O0001">'
        '<file src="/Users/x/RM/scan.jpg" mime="image/jpeg" '
        'description="scan.jpg"/>'
        "</object>"
    )


def test_media_description_is_a_file_attribute_not_a_child() -> None:
    """The label rides on <file description="…">, not a <description> child.

    `<!ATTLIST file (src CDATA #REQUIRED mime CDATA #REQUIRED checksum
    CDATA #IMPLIED description CDATA #REQUIRED)>` makes description a
    #REQUIRED *attribute*, and `<!ELEMENT object (file, attribute*,
    noteref*, date?, citationref*, tagref*)>` has no `description`
    child at all.
    """
    rec = MediaRecord(
        media_id=1,
        media_file="scan.jpg",
        media_path="/x/scan.jpg",
        url="",
        media_type=1,
        description="Label",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert "<description>" not in xml
    assert 'description="Label"' in xml


def test_media_with_web_url_uses_url_as_src() -> None:
    """When URL is non-empty, <file src> uses the URL."""
    rec = MediaRecord(
        media_id=2,
        media_file="",
        media_path="",
        url="https://example.org/scan.jpg",
        media_type=1,
        description="Web-hosted scan",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert (
        '<file src="https://example.org/scan.jpg" mime="image/jpeg" '
        'description="Web-hosted scan"/>'
    ) in xml


def test_media_document_type_pdf() -> None:
    """MediaType=2 → mime=application/pdf."""
    rec = MediaRecord(
        media_id=3,
        media_file="doc.pdf",
        media_path="/x/doc.pdf",
        url="",
        media_type=2,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert 'mime="application/pdf"' in xml


def test_media_audio_type() -> None:
    """MediaType=3 → mime=audio/mpeg."""
    rec = MediaRecord(
        media_id=4,
        media_file="voice.mp3",
        media_path="/x/voice.mp3",
        url="",
        media_type=3,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert 'mime="audio/mpeg"' in xml


def test_media_video_type() -> None:
    """MediaType=4 → mime=video/mp4."""
    rec = MediaRecord(
        media_id=5,
        media_file="clip.mp4",
        media_path="/x/clip.mp4",
        url="",
        media_type=4,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert 'mime="video/mp4"' in xml


def test_media_unknown_type_falls_back_to_octet_stream() -> None:
    """MediaType not in the map → mime=application/octet-stream."""
    rec = MediaRecord(
        media_id=6,
        media_file="blob.bin",
        media_path="/x/blob.bin",
        url="",
        media_type=999,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert 'mime="application/octet-stream"' in xml


def test_media_empty_path_and_url_emits_nothing() -> None:
    """No MediaPath AND no URL → no <object> at all.

    `<!ELEMENT object (file, attribute*, noteref*, …)>` makes `<file>`
    mandatory, and `<file>` requires a `src`. An <object> with no
    <file> is schema-invalid, so the renderer emits nothing and the
    writer's <objref> injection keys off the objects that exist. v2.2
    emitted a wrapper-only <object> for this case; that was invalid.
    """
    rec = MediaRecord(
        media_id=7,
        media_file="orphan.jpg",
        media_path="",
        url="",
        media_type=1,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert xml == ""


def test_media_xml_special_chars_in_description_escaped() -> None:
    """Escape applies to the <file description="…"> attribute."""
    rec = MediaRecord(
        media_id=8,
        media_file="x.jpg",
        media_path="/x/x.jpg",
        url="",
        media_type=1,
        description='Headstone of <Thomas> "Mills" & family',
    )
    xml = render_media_xml(rec, change=1700000000)
    assert (
        'description="Headstone of &lt;Thomas&gt; '
        '&quot;Mills&quot; &amp; family"'
    ) in xml


def test_media_change_zero_emitted_verbatim() -> None:
    """change=\"0\" is valid; always emit it."""
    rec = MediaRecord(
        media_id=9,
        media_file="x.jpg",
        media_path="/x/x.jpg",
        url="",
        media_type=1,
        description="",
    )
    xml = render_media_xml(rec, change=0)
    assert 'change="0"' in xml


def test_media_description_attribute_is_always_present() -> None:
    """Both description and MediaFile empty → description="" on <file>.

    `<file>`'s `description` is #REQUIRED, so an empty label is emitted
    as an empty attribute rather than omitted.
    """
    rec = MediaRecord(
        media_id=10,
        media_file="",
        media_path="/x/scan.jpg",
        url="",
        media_type=1,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert 'description=""' in xml
    assert "<description" not in xml