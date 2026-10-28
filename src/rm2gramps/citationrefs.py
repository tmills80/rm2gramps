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


def inject_refs(
    xml: str,
    tag: str,
    hlink_values: tuple[str, ...],
) -> str:
    """Insert <{tag} hlink="…"/> children before the element's closing tag.

    General form of :func:`inject_citationrefs` — accepts any
    child element name and any hlink values (full handles, not
    integer ids). Use this for cross-references where the
    renderer doesn't have a `_handle()` helper — for
    citationrefs specifically, prefer :func:`inject_citationrefs`
    which composes the handle from a CitationID.

    ``tag`` and ``hlink_values`` are positional rather than
    keyword-only so call sites can read as
    ``inject_refs(xml, "noteref", handles)``.

    Parameters
    ----------
    xml
        The rendered element XML.
    tag
        The child element name to inject (e.g. ``"noteref"``,
        ``"objref"``, ``"reporef"``).
    hlink_values
        Tuple of full Gramps handles (e.g. ``"_g_nab12cd34ef56"``,
        ``"_g_o2"``, ``"_g_r3"``). Empty tuple returns ``xml``
        unchanged.

    Returns
    -------
    str
        The XML with ``<{tag} hlink="…"/>`` children inserted
        just before the element's closing tag.
    """
    if not hlink_values:
        return xml
    refs = "".join(
        f'<{tag} hlink="{h}"/>' for h in hlink_values
    )
    close_idx = xml.rfind("</")
    if close_idx == -1:
        return xml
    return xml[:close_idx] + refs + xml[close_idx:]