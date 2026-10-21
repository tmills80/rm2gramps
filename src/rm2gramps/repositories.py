"""AddressTable row → Gramps <repository> element.

Pure-function renderer. Takes a :class:`RepositoryRecord` and
returns the XML string for one <repository> element.

Decision 3 in the v2.2 plan: any AddressTable row linked to an
exported citation via AddressLinkTable counts as a repository,
regardless of AddressType. RM's AddressType is ignored by v2.2.

Gramps <repository> element shape, per the 1.7.2 DTD::

    <!ELEMENT repository (rname, type, address*, url*, noteref*, tagref*)>
    <!ELEMENT address ((daterange|datespan|dateval|datestr)?, street?,
                       locality?, city?, county?, state?, country?,
                       postal?, phone?, noteref*, citationref*)>
    <!ATTLIST url (priv (0|1) #IMPLIED type CDATA #IMPLIED
                   href CDATA #REQUIRED description CDATA #IMPLIED)>

Three corrections this encodes, each verified against the DTD
rather than assumed:

- There is no ``<raddr>``, ``<rurl>``, ``<rphone>`` or top-level
  ``<email>`` element anywhere in the schema. The postal block is an
  ``<address>`` child; phone is a ``<phone>`` child *of that
  address*; the web address is a ``<url>`` child carrying the link in
  its ``href`` attribute. The email field has no home in a
  ``<repository>`` — the DTD's ``<resemail>`` belongs to the
  ``<researcher>`` header block, not to repositories — so it is
  dropped rather than invented into an invalid shape.
- ``<type>`` is **required** and follows ``<rname>``. RM's
  AddressTable has no repository-kind column, so v2.2 infers it:
  a row with a URL is a ``Web site``, otherwise the Gramps default
  ``Library``. Both values are ones Gramps' own exports use.
- "state" in RM maps to Gramps ``<state>``, not ``<county>``. The
  earlier code mapped state→county on a "UK-centric naming"
  assumption; the DTD lists ``state`` as its own particle, and a real
  Gramps export uses ``<state>`` for a UK address. Postal codes go to
  ``<postal>``.

Child order inside ``<address>`` follows the DTD's declared
sequence (street, locality, city, county, state, country, postal,
phone) — a strict parser rejects them out of order.

The writer's ``<reporef>`` injection keys off the handle this
returns, so the display-id scheme is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import format_display_id, repository_handle
from .xmlutil import xml_escape


def _repository_type(*, has_url: bool) -> str:
    """Gramps <type> for this repository.

    RM's AddressTable carries no repository-kind column. A row that
    has a URL is a web presence; anything else is a physical holding
    institution, which is Gramps' own default (``Library``). Both
    values appear in Gramps' own exports.
    """
    return "Web site" if has_url else "Library"


@dataclass(frozen=True)
class RepositoryRecord:
    """One AddressTable row projected for repository rendering."""

    address_id: int
    name: str
    street1: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = ""
    phone: str = ""
    email: str = ""
    url: str = ""


def render_repository_xml(rec: RepositoryRecord, *, change: int) -> str:
    """Render one RepositoryRecord as a Gramps <repository> XML string.

    Parameters
    ----------
    rec
        The AddressTable row projected to ``address_id`` + ``name``
        + address fields + ``phone`` + ``email`` + ``url``.
    change
        Unix-seconds timestamp for the ``change`` attribute.
    """
    handle = repository_handle(rec.address_id)
    display = format_display_id(rec.address_id, "R")

    # rname and type are both required by the DTD, and rname must come
    # first. An unnamed row still needs an <rname> for the document to
    # be schema-valid, so fall back to a placeholder.
    name = rec.name or "Unnamed repository"
    parts = [
        f'<repository handle="{handle}" change="{int(change)}" '
        f'id="{display}">',
        f"<rname>{xml_escape(name)}</rname>",
        f"<type>{_repository_type(has_url=bool(rec.url))}</type>",
    ]

    # <address> — only emitted when at least one field is filled.
    addr_fields: list[tuple[str, str]] = [
        ("street", rec.street1),
        ("city", rec.city),
        ("state", rec.state),
        ("country", rec.country),
        ("postal", rec.zip_code),
        ("phone", rec.phone),
    ]
    addr_block = "".join(
        f"<{tag}>{xml_escape(value)}</{tag}>"
        for tag, value in addr_fields
        if value
    )
    if addr_block:
        parts.append(f"<address>{addr_block}</address>")

    if rec.url:
        parts.append(
            f'<url href="{xml_escape(rec.url)}" type="Web Home" '
            f'description="{xml_escape(name)}"/>'
        )

    parts.append("</repository>")
    return "".join(parts)
