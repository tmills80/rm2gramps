"""String-level <citationref> injection into rendered owner elements.

Pure string transformation. Anchors on the closing tag of the
element, so it works regardless of which other children the
element already has (eventref, childof, parentin, attribute, …).

Kept separate from writer.py because the function is pure and
unit-testable without a live database. The plan-locked architecture
for v2.1 is: renderers stay pure; this module owns the
post-render augmentation.

Empty citation_ids → XML unchanged.
"""

from __future__ import annotations

from .handles import citation_handle


def inject_citationrefs(xml: str, citation_ids: tuple[int, ...]) -> str:
    """Insert <citationref> children just before an element's closing tag.

    Parameters
    ----------
    xml
        The rendered element XML (e.g. one <person> string).
    citation_ids
        Tuple of CitationIDs to attach as <citationref hlink="..."/>.
        Empty tuple returns ``xml`` unchanged.

    Returns
    -------
    str
        The XML with citationref children inserted just before the
        element's closing tag. If the input has no closing tag
        (malformed), returns it unchanged.
    """
    if not citation_ids:
        return xml
    refs = "".join(
        f'<citationref hlink="{citation_handle(cid)}"/>'
        for cid in citation_ids
    )
    # The element's closing tag is the last "</" — top-level
    # element types (person / family / source / event) have no
    # nested same-name children, so rfind("</") lands on the
    # right spot. Any "<" in element text content would be
    # escaped to "&lt;" already, so this is safe.
    close_idx = xml.rfind("</")
    if close_idx == -1:
        return xml
    return xml[:close_idx] + refs + xml[close_idx:]