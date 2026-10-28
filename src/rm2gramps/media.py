"""MultimediaTable row → Gramps <object> element.

Pure-function renderer. Takes a :class:`MediaRecord` and returns the
XML string for one <object> element.

Gramps calls media items \"objects\" — hence the wrapper tag and
display-id prefix ``O`` (verified against ``example.gramps``).

MediaType → MIME mapping (Decision 6 in v2.2 plan):
- 1 = image/jpeg
- 2 = application/pdf
- 3 = audio/mpeg
- 4 = video/mp4
- any other int = application/octet-stream

Source priority: if ``URL`` is non-empty, <file src> uses the URL
(the original researcher's machine path is no good in the new
environment). Otherwise <file src> uses ``MediaPath``.

``description`` is an **attribute of ``<file>``, not a child of
``<object>``. The DTD declares
``<!ATTLIST file (src CDATA #REQUIRED mime CDATA #REQUIRED checksum
CDATA #IMPLIED description CDATA #REQUIRED)>`` and
``<!ELEMENT object (file, attribute*, noteref*, date?, citationref*,
tagref*)>`` — there is no ``<description>`` child of ``<object>``,
and ``description`` is ``#REQUIRED`` on ``<file>``. When neither a
URL nor a MediaPath yields a ``<file>``, no ``<object>`` is emitted
at all, because an ``<object>`` cannot be schema-valid without its
mandatory ``<file>`` child; the writer's ``<objref>`` injection
already keys off objects that were emitted.

Thumbnail BLOBs are dropped. Gramps re-extracts thumbnails on
import from the file at <file src>. The original machine paths
will often be invalid post-export and that's a known limitation —
see the v2.2 plan § "Risks".

Description: when ``MediaFile`` is set but ``Description`` is
empty, ``MediaFile`` becomes the description text (it's the best
non-empty label we have). When ``Description`` is set, it wins.
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import format_display_id, media_handle
from .xmlutil import xml_escape


# RM MediaType int → MIME string. The four common values; anything
# else falls back to application/octet-stream.
_MEDIA_TYPE_MIME: dict[int, str] = {
    1: "image/jpeg",
    2: "application/pdf",
    3: "audio/mpeg",
    4: "video/mp4",
}


@dataclass(frozen=True)
class MediaRecord:
    """One MultimediaTable row projected for rendering.

    Full row population (``Thumbnail`` BLOB, ``RefNumber``,
    ``UTCModDate``, etc.) is out of scope for v2.2 — see
    ``plans/v2.2-notes-media-repositories.md`` §
    "Architecture".
    """

    media_id: int
    media_file: str
    media_path: str
    url: str
    media_type: int
    description: str = ""


def render_media_xml(rec: MediaRecord, *, change: int) -> str:
    """Render one MediaRecord as a Gramps <object> XML string.

    Parameters
    ----------
    rec
        The MultimediaTable row projected to ``media_id`` +
        ``media_file`` + ``media_path`` + ``url`` + ``media_type`` +
        ``description``.
    change
        Unix-seconds timestamp for the ``change`` attribute.
    """
    handle = media_handle(rec.media_id)
    display = format_display_id(rec.media_id, "O")

    # Source path: URL wins over MediaPath when both are set.
    src = rec.url or rec.media_path
    if not src:
        # <object> requires a <file> child, and <file> requires a src.
        # Without one there is no schema-valid object to emit; the
        # researcher re-adds the media in Gramps from the RM tree.
        return ""

    # Description: explicit Description wins; fall back to MediaFile.
    # It is a #REQUIRED attribute on <file>, so always emitted.
    desc = rec.description or rec.media_file
    mime = _MEDIA_TYPE_MIME.get(rec.media_type, "application/octet-stream")
    return (
        f'<object handle="{handle}" change="{int(change)}" id="{display}">'
        f'<file src="{xml_escape(src)}" mime="{mime}" '
        f'description="{xml_escape(desc)}"/>'
        f"</object>"
    )