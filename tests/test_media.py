"""Tests for rm2gramps.media — MultimediaTable row → <object> element.

T23 cases from ``tools/rm2gramps/plans/v2.2-notes-media-repositories.md``
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
        '<file src="/Users/x/RM/scan.jpg" mime="image/jpeg"/>'
        '<description>scan.jpg</description>'
        "</object>"
    )


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
    assert '<file src="https://example.org/scan.jpg" mime="image/jpeg"/>' in xml
    # MediaFile is empty so the description is the user-supplied one.
    assert "<description>Web-hosted scan</description>" in xml


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


def test_media_empty_path_and_url_emits_wrapper_only() -> None:
    """No MediaPath AND no URL → no <file> child; wrapper still emitted."""
    rec = MediaRecord(
        media_id=7,
        media_file="orphan.jpg",
        media_path="",
        url="",
        media_type=1,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert "<file" not in xml
    assert 'id="O0007"' in xml
    assert 'handle="_g_o7"' in xml


def test_media_xml_special_chars_in_description_escaped() -> None:
    """Escape applies to <description>."""
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
        "<description>Headstone of &lt;Thomas&gt; "
        "&quot;Mills&quot; &amp; family</description>"
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


def test_media_no_description_emitted_when_empty() -> None:
    """Both description and MediaFile empty → no <description> child."""
    rec = MediaRecord(
        media_id=10,
        media_file="",
        media_path="/x/scan.jpg",
        url="",
        media_type=1,
        description="",
    )
    xml = render_media_xml(rec, change=1700000000)
    assert "<description" not in xml