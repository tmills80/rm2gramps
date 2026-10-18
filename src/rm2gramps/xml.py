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
    places: Sequence[str],
) -> bytes:
    """Render the full Gramps XML document as UTF-8 bytes.

    Parameters
    ----------
    header_date
        ISO date (``YYYY-MM-DD``) for ``<created date=\"…\">``.
    version
        Free-form version string for ``<created version=\"…\">``.
    events, people, families, places
        Tuples of pre-rendered element strings (one per object) as
        produced by ``events.render_event_xml`` / ``people.
        render_person_xml`` / ``families.render_family_xml`` /
        ``places.render_place_xml``.
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

    sections: list[tuple[str, Sequence[str]]] = [
        ("events", events),
        ("people", people),
        ("families", families),
        ("places", places),
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