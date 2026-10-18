"""Minimal XML text escape helpers shared across rm2gramps renderers.

Only the five XML predefined entities are handled — sufficient for
genealogical text (names, places, occupation descriptions) which
doesn't contain control characters. Sourced from
``tools/rm2gramps/src/rm2gramps/events.py`` where it originated; lifted
to a module of its own once ``places.py`` also needed it.
"""

from __future__ import annotations


def xml_escape(s: str) -> str:
    """Escape the five XML predefined entities.

    Ampersand must be replaced first so we don't double-escape the
    ``&`` in ``&lt;`` etc.
    """
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )