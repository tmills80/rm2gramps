"""AddressTable row → Gramps <repository> element.

Pure-function renderer. Takes a :class:`RepositoryRecord` and
returns the XML string for one <repository> element.

Decision 3 in the v2.2 plan: any AddressTable row linked to an
exported citation via AddressLinkTable counts as a repository,
regardless of AddressType. RM's AddressType is ignored by v2.2.

Gramps <repository> element shape:
- <rname>…</rname> — the repository's name (from AddressTable.Name)
- <raddr><street/><city/><county/><postal/><country/></raddr> —
  postal address block. Empty fields are omitted.
- <rurl>…</rurl> — repository URL (from AddressTable.URL)
- <email>…</email> — repository email (from AddressTable.Email)
- <rphone>…</rphone> — repository phone (from AddressTable.Phone1)

Gramps element-name quirks worth knowing:
- \"state\" in RM maps to Gramps' <county> (UK-centric naming).
- \"zip\" in RM maps to Gramps' <postal>.
- repository phone uses <rphone>, not <phone> (Gramps uses
  <phone> for the researcher block).
"""

from __future__ import annotations

from dataclasses import dataclass

from .handles import format_display_id, repository_handle
from .xmlutil import xml_escape


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
    parts = [
        f'<repository handle="{handle}" change="{int(change)}" '
        f'id="{display}">'
    ]

    if rec.name:
        parts.append(f"<rname>{xml_escape(rec.name)}</rname>")

    # raddr block — only emit when at least one field is filled.
    # Gramps' controlled vocabulary: street / city / county / postal
    # / country. State in RM maps to <county>; zip maps to <postal>.
    addr_fields: list[tuple[str, str]] = [
        ("street", rec.street1),
        ("city", rec.city),
        ("county", rec.state),
        ("postal", rec.zip_code),
        ("country", rec.country),
    ]
    addr_block = "".join(
        f"<{tag}>{xml_escape(value)}</{tag}>"
        for tag, value in addr_fields
        if value
    )
    if addr_block:
        parts.append(f"<raddr>{addr_block}</raddr>")

    if rec.url:
        parts.append(f"<rurl>{xml_escape(rec.url)}</rurl>")
    if rec.email:
        parts.append(f"<email>{xml_escape(rec.email)}</email>")
    if rec.phone:
        parts.append(f"<rphone>{xml_escape(rec.phone)}</rphone>")

    parts.append("</repository>")
    return "".join(parts)