"""Top-level writer that produces a Gramps XML ``.gramps`` payload.

``write_database`` takes pre-rendered per-object strings (each
renderer — events, people, families, places — produces one string
per object) and stitches them into the document skeleton:

    <?xml ... ?>
    <!DOCTYPE database ...>
    <database xmlns="http://gramps-project.org/xml/1.7.2/">
      <header>…</header>
      <events>…</events>
      <people>…</people>
      <families>…</families>
      <places>…</places>
    </database>

Section ordering matches Gramps' own export convention (and the
plan). The writer is pure: takes tuples in, returns bytes out.
File IO (writing to disk, gzip wrapping) lives in ``cli/export.py``
which calls this function.

Bytes vs str: the output is ``bytes`` so the caller doesn't need
to know the encoding (UTF-8, no BOM). The XML declaration
``<?xml version="1.0" encoding="UTF-8"?>`` is emitted explicitly so
Gramps and parsers know the encoding even if the file is later
post-processed.
"""

from __future__ import annotations

from collections.abc import Sequence

_GRAMPS_DTD = (
    '<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.2//EN" '
    '"http://gramps-project.org/xml/1.7.2/grampsxml.dtd">'
)
_GRAMPS_NS = "http://gramps-project.org/xml/1.7.2/"


def write_database(
    *,
    header_date: str,
    version: str,
    events: Sequence[str],
    people: Sequence[str],
    families: Sequence[str],
    sources: Sequence[str] = (),
    citations: Sequence[str] = (),
    places: Sequence[str],
    notes: Sequence[str] = (),
) -> bytes:
    """Render the full Gramps XML document as UTF-8 bytes.

    Parameters
    ----------
    header_date
        ISO date (``YYYY-MM-DD``) for ``<created date=\"…\">``.
    version
        Free-form version string for ``<created version=\"…\">``.
    events, people, families, sources, citations, places, notes
        Tuples of pre-rendered element strings (one per object) as
        produced by the v1 renderers (``events.render_event_xml``
        etc.), v2.1 (``sources.render_source_xml``,
        ``citations.render_citation_xml``), and v2.2
        (``notes.render_note_xml``).
    """
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        _GRAMPS_DTD + "\n",
        f'<database xmlns="{_GRAMPS_NS}">\n',
        "  <header>\n",
        f'    <created date="{header_date}" version="{version}"/>\n',
        "    <researcher/>\n",
        "  </header>\n",
    ]

    # Section order matches Gramps' own export convention (verified
    # against ``example.gramps``): events → people → families →
    # sources → citations → places → notes. Notes are last
    # because they're leaf objects referenced from many places
    # via <noteref>; the export reads top-down and leaf objects go
    # at the bottom.
    sections: list[tuple[str, Sequence[str]]] = [
        ("events", events),
        ("people", people),
        ("families", families),
        ("sources", sources),
        ("citations", citations),
        ("places", places),
        ("notes", notes),
    ]
    for name, items in sections:
        parts.append(f"  <{name}>\n")
        for item in items:
            # The renderers return single-line strings; we indent
            # them for human-readable output that matches Gramps'
            # own convention.
            parts.append(f"    {item}\n")
        parts.append(f"  </{name}>\n")

    parts.append("</database>\n")
    return "".join(parts).encode("utf-8")