"""Child-element ordering to satisfy the Gramps DTD content models.

The DTD gives each element an *ordered* child sequence, and the order
differs between element types::

    <!ELEMENT person  (gender, name*, eventref*, lds_ord*, objref*,
                       address*, attribute*, url*, childof*, parentin*,
                       personref*, noteref*, citationref*, tagref*)>
    <!ELEMENT event   (type?, date?, place?, cause?, description?,
                       attribute*, noteref*, citationref*, objref*, tagref*)>

``<person>`` wants ``objref`` *before* ``noteref``; ``<event>`` wants it
*after* ``citationref``. rm2gramps builds elements by rendering, then
appending cross-references before the closing tag — a strategy that
only ever produces "append at the end", which cannot satisfy both.

So the writer normalises: every rendered element string passes through
:func:`reorder_children`, which sorts each element's direct children
into the DTD's declared order. Children the table doesn't mention keep
their relative order and sink to the end, so a newly added element
degrades to "out of order" (visible in the schema test) rather than
silently vanishing.

Pure string transformation — no sqlite3, no ElementTree round-trip, so
the exact formatting the renderers produced (self-closing style,
attribute order) is preserved byte-for-byte.
"""

from __future__ import annotations

import re


# The Gramps 1.7.2 DTD's declared child sequence, copied verbatim per
# element type, with the parenthesised date choice expanded into its
# four alternatives. `test_schema.py::test_child_order_table_matches_the_dtd`
# pins this table against the vendored DTD so it cannot drift.
CHILD_ORDER: dict[str, tuple[str, ...]] = {
    "person": (
        "gender", "name", "eventref", "lds_ord", "objref", "address",
        "attribute", "url", "childof", "parentin", "personref",
        "noteref", "citationref", "tagref",
    ),
    "family": (
        "rel", "father", "mother", "eventref", "lds_ord", "objref",
        "childref", "attribute", "noteref", "citationref", "tagref",
    ),
    "event": (
        "type", "daterange", "datespan", "dateval", "datestr", "place",
        "cause", "description", "attribute", "noteref", "citationref",
        "objref", "tagref",
    ),
    "source": (
        "stitle", "sauthor", "spubinfo", "sabbrev", "noteref", "objref",
        "srcattribute", "reporef", "tagref",
    ),
    "citation": (
        "daterange", "datespan", "dateval", "datestr", "page",
        "confidence", "noteref", "objref", "srcattribute",
        "sourceref", "tagref",
    ),
    "placeobj": (
        "ptitle", "code", "pname", "coord", "placeref", "location",
        "objref", "url", "noteref", "citationref", "tagref",
    ),
    "repository": ("rname", "type", "address", "url", "noteref", "tagref"),
    "object": (
        "file", "attribute", "noteref", "daterange", "datespan",
        "dateval", "datestr", "citationref", "tagref",
    ),
    "note": ("text", "style", "tagref"),
}

_OPEN_TAG = re.compile(r"^<([A-Za-z_][\w.:-]*)")


def _scan_element(inner: str, index: int) -> tuple[str, int]:
    """Return ``(chunk, index_after)`` for the child starting at ``index``.

    ``index`` must point at a ``<``. Walks forward over the whole
    element — opening tag, any text, any nested elements, closing tag —
    so a child with text content (``<type>Birth</type>``) or nested
    children (``<name><first>…</first></name>``) stays one chunk.

    Assumes well-formed input: renderers emit valid XML, and the
    document is parsed before this ever runs.
    """
    start = index
    depth = 0
    length = len(inner)
    while index < length:
        lt = inner.find("<", index)
        if lt == -1:
            return inner[start:], length
        gt = inner.find(">", lt)
        if gt == -1:
            return inner[start:], length
        tag_body = inner[lt + 1 : gt]
        if tag_body.startswith("/"):
            # Closing tag.
            depth -= 1
            if depth == 0:
                return inner[start : gt + 1], gt + 1
        elif tag_body.endswith("/"):
            # Self-closing tag.
            if depth == 0:
                return inner[start : gt + 1], gt + 1
        else:
            depth += 1
        index = gt + 1
    return inner[start:], length


def reorder_children(xml: str) -> str:
    """Sort one rendered element's direct children into DTD order.

    Parameters
    ----------
    xml
        A single rendered element, e.g. ``'<person handle="…">…</person>'``.

    Returns
    -------
    str
        The same element with its children reordered. Returned
        unchanged when the element has no known order, has no
        children, or has no closing tag.
    """
    open_match = _OPEN_TAG.match(xml)
    if open_match is None:
        return xml
    name = open_match.group(1)
    order = CHILD_ORDER.get(name)
    if order is None:
        return xml
    # A self-closing element has nothing to reorder.
    head_end = xml.find(">")
    if head_end == -1 or xml[head_end - 1] == "/":
        return xml
    close = xml.rfind(f"</{name}")
    if close == -1:
        return xml
    inner = xml[head_end + 1 : close]

    # Collect each direct child as a chunk, skipping bare whitespace
    # between them (renderers emit no interior whitespace, but a
    # hand-written test string may).
    children: list[str] = []
    index = 0
    length = len(inner)
    while index < length:
        if inner[index].isspace():
            index += 1
            continue
        if inner[index] != "<":
            # Bare text at this level — not produced by the renderers;
            # keep it as a chunk so nothing is silently dropped.
            nxt = index
            while nxt < length and inner[nxt] != "<":
                nxt += 1
            children.append(inner[index:nxt])
            index = nxt
            continue
        chunk, index = _scan_element(inner, index)
        children.append(chunk)
    if len(children) < 2:
        return xml

    rank = {child: position for position, child in enumerate(order)}

    def key(chunk: str) -> tuple[int, int]:
        match = _OPEN_TAG.match(chunk.lstrip())
        if match is None:
            return (len(order) + 1, 0)
        return (rank.get(match.group(1), len(order)), 0)

    # Stable sort keeps same-name children (name*, eventref*, …) in
    # their original relative order, which carries sort-date meaning.
    ordered = sorted(children, key=key)
    return xml[: head_end + 1] + "".join(ordered) + xml[close:]
