"""CitationLinkTable walker.

Pure SQL walker: opens ``CitationLinkTable`` and groups rows by
``OwnerType`` (Person / Family / Source) and ``OwnerID`` so the
caller can attach ``<citationref>`` elements to each exported
owner.

Unknown OwnerType values (RM uses 7 and 19 — internal extensions;
the schema doc does not enumerate every bucket) trigger a single
warning per unknown type and are skipped. Events are not walked
here; if event→citation linkage is needed, the writer does a
direct JOIN (``tools/rm2gramps/writer.py`` T16).

``person_ids`` filter: when the caller passes a tuple of PersonIDs,
the result is narrowed to citations referencing those persons
directly. Family / Source / Event narrowing is the caller's job
(families/events are pulled from the person graph in the writer).

Schema reference: ``tools/rmread/docs/rm11-schema.md`` §
"Citation, source, multimedia, address, URL" (specifically the
``CitationLinkTable`` distribution in ``SampleTree.rmtree``).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from typing import TypedDict


_log = logging.getLogger(__name__)


# CitationLinkTable OwnerType → owner kind.
#
# RM uses ONE global OwnerType enum across every *LinkTable. Verified
# against SampleTree.rmtree (RM 11.0) by testing which candidate owner
# table contains all of each bucket's OwnerIDs:
#
#     0 = Person   1 = Family   2 = Event   3 = Source   4 = Citation
#
# The decisive case is OwnerType=2: SampleTree has 488 distinct
# OwnerIDs in that bucket, and PersonTable (429), FamilyTable (142),
# SourceTable (204) and CitationTable (438) are each too small to
# hold that many distinct ids. EventTable (870) is the only table they
# can reference. This assumes RM maintains referential integrity on
# OwnerID, which the rest of the schema does.
#
# This map previously read 2 = "Source". That put 488 event-owned
# citations into the Source bucket and narrowed the export against
# the 86 of them whose ids happened to collide with real SourceIDs.
#
# OwnerTypes 7 and 19 also appear in SampleTree. They are outside
# this enum and are not interpreted — they warn and are skipped.
_OWNER_TYPE_TO_KEY: dict[int, str] = {
    0: "Person",
    1: "Family",
    2: "Event",
    3: "Source",
    4: "Citation",
}


class CitationLinks(TypedDict):
    """Output of :func:`walk_citation_links`."""

    Person: dict[int, tuple[int, ...]]
    Family: dict[int, tuple[int, ...]]
    Event: dict[int, tuple[int, ...]]
    Source: dict[int, tuple[int, ...]]
    Citation: dict[int, tuple[int, ...]]


def walk_citation_links(
    con: sqlite3.Connection,
    *,
    person_ids: Iterable[int] | None = None,
    family_ids: Iterable[int] | None = None,
) -> CitationLinks:
    """Walk CitationLinkTable and return owner-id → citation-id tuples.

    Parameters
    ----------
    con
        Open ``sqlite3.Connection`` to the .rmtree database.
    person_ids
        Optional PersonID subset. When supplied, ``Person`` rows
        are filtered to those whose ``OwnerID`` is in the set
        (``CitationLinkTable.OwnerID`` for OwnerType=0 is a
        PersonID).

    family_ids
        Optional FamilyID subset, applied to the ``Family`` bucket
        the same way. A ``person_ids`` export must pass this: the
        Family bucket is not reachable from the Person bucket, so
        without it every citation attached to any family in the tree
        leaks into the subset export.

    Returns
    -------
    CitationLinks
        ``{'Person': {pid: (citation_id, ...), ...}, 'Family': ...,
        'Source': ...}``. Only the three known owner types appear
        in the dict; unknown OwnerType values are logged and
        dropped.
    """
    # Initialise the known buckets as empty dicts.
    out: CitationLinks = {
        "Person": {}, "Family": {}, "Event": {},
        "Source": {}, "Citation": {},
    }

    sql = """
        SELECT CitationID, OwnerType, OwnerID
        FROM CitationLinkTable
        ORDER BY OwnerType, OwnerID, SortOrder, CitationID
    """
    rows = con.execute(sql).fetchall()

    # Per-bucket allow-list. None means "no filter for this bucket".
    # Only Person and Family are filtered: an Event / Source /
    # Citation bucket is reached through its own owner, not through
    # the person graph.
    bucket_filters: dict[str, set[int] | None] = {
        "Person": None if person_ids is None else set(person_ids),
        "Family": None if family_ids is None else set(family_ids),
        "Event": None,
        "Source": None,
        "Citation": None,
    }

    seen_unknown: set[int] = set()
    skipped_count = 0
    for r in rows:
        otype = r["OwnerType"]
        bucket = _OWNER_TYPE_TO_KEY.get(otype)
        if bucket is None:
            if otype not in seen_unknown:
                _log.warning(
                    "unknown citation OwnerType=%d (%d rows skipped so far); "
                    "see tools/rmread/docs/rm11-schema.md § 'CitationLinkTable'",
                    otype, skipped_count,
                )
                seen_unknown.add(otype)
            skipped_count += 1
            continue

        oid = r["OwnerID"]
        cid = r["CitationID"]

        allowed = bucket_filters[bucket]
        if allowed is not None and oid not in allowed:
            continue

        # Append to per-owner citation-id tuple (preserving SortOrder).
        existing = out[bucket].get(oid, ())
        out[bucket][oid] = existing + (cid,)

    return out