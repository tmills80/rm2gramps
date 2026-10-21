"""Tests for rm2gramps.repositories — AddressTable row → <repository> element.

T24 cases from ``tools/rm2gramps/plans/v2.2-notes-media-repositories.md``
§ T24:

- minimum: AddressID + Name → <repository handle=… id=…><rname>…</rname></repository>
- full address: Street1 + City → <raddr><street>…</street><city>…</city></raddr>
- with rurl + email → <rurl>…</rurl> + <email>…</email>
- empty name → wrapper with handle+id, no <rname>
- XML escape
- change=0

Decision 3 in v2.2 plan: any AddressTable row linked to an
exported citation via AddressLinkTable counts as a repository,
regardless of AddressType. RM's AddressType is ignored by v2.2.
"""

from __future__ import annotations

from rm2gramps.repositories import (
    RepositoryRecord,
    render_repository_xml,
)


def test_repository_minimum() -> None:
    """Canonical populated repository → minimum <repository>."""
    rec = RepositoryRecord(
        address_id=1,
        name="Staines St Mary Parish",
        street1="",
        city="",
        state="",
        zip_code="",
        country="",
        phone="",
        email="",
        url="",
    )
    xml = render_repository_xml(rec, change=1700000000)
    assert xml == (
        '<repository handle="_g_r1" change="1700000000" id="R0001">'
        "<rname>Staines St Mary Parish</rname>"
        "<type>Library</type>"
        "</repository>"
    )


def test_repository_with_full_address_emits_address() -> None:
    """Non-empty Street1 + City → <address> with <street> and <city>.

    `<!ELEMENT address ((date)?, street?, locality?, city?, county?,
    state?, country?, postal?, phone?, noteref*, citationref*)>` —
    the DTD has no `raddr` element; the postal block is an <address>
    child, and child order follows the declared sequence.
    """
    rec = RepositoryRecord(
        address_id=2,
        name="Reading Room",
        street1="10 High Street",
        city="Reading",
        state="Berkshire",
        zip_code="RG1 1AA",
        country="UK",
        phone="",
        email="",
        url="",
    )
    xml = render_repository_xml(rec, change=1700000000)
    assert "<address>" in xml
    assert "<street>10 High Street</street>" in xml
    assert "<city>Reading</city>" in xml
    # The DTD lists `state` as its own particle, so RM's State maps to
    # <state> — the earlier mapping to <county> was wrong.
    assert "<state>Berkshire</state>" in xml
    assert "<county>" not in xml
    assert "<postal>RG1 1AA</postal>" in xml
    assert "<country>UK</country>" in xml
    assert "</address>" in xml
    # Declared order is street, city, county, state, country, postal,
    # phone — country must precede postal here.
    assert xml.index("<country>") < xml.index("<postal>")
    assert "<raddr>" not in xml


def test_repository_type_is_required_after_rname() -> None:
    """`<repository>` requires (rname, type, …) — type is never omitted."""
    rec = RepositoryRecord(address_id=10, name="AAAAAA")
    xml = render_repository_xml(rec, change=1700000000)
    assert xml.index("<rname>") < xml.index("<type>")
    assert "<type>Library</type>" in xml


def test_repository_type_is_web_site_when_a_url_is_present() -> None:
    """A URL-bearing repository is a "Web site"; both are Gramps values."""
    rec = RepositoryRecord(address_id=11, name="AAAAAA", url="https://x.invalid/")
    assert "<type>Web site</type>" in render_repository_xml(rec, change=1)


def test_repository_with_url_and_email() -> None:
    """Non-empty URL → <url href="…">; email has no home and is dropped.

    `<!ATTLIST url (…, href CDATA #REQUIRED, …)>`. There is no `rurl`,
    no `rphone`, and no top-level `<email>` in the schema — `resemail`
    belongs to the `<researcher>` header block, not to a repository.
    """
    rec = RepositoryRecord(
        address_id=3,
        name="British Library",
        street1="",
        city="",
        state="",
        zip_code="",
        country="",
        phone="",
        email="info@bl.uk",
        url="https://www.bl.uk",
    )
    xml = render_repository_xml(rec, change=1700000000)
    assert 'href="https://www.bl.uk"' in xml
    assert "<rurl>" not in xml
    # Email is not rendered into an invented element.
    assert "info@bl.uk" not in xml
    assert "<email>" not in xml


def test_repository_with_phone() -> None:
    """Non-empty phone → <phone> inside the <address> block."""
    rec = RepositoryRecord(
        address_id=4,
        name="Society of Genealogists",
        street1="",
        city="",
        state="",
        zip_code="",
        country="",
        phone="+44 20 7202 5400",
        email="",
        url="",
    )
    xml = render_repository_xml(rec, change=1700000000)
    assert "<phone>+44 20 7202 5400</phone>" in xml
    assert "<rphone>" not in xml


def test_repository_empty_name_still_emits_handle() -> None:
    """Empty Name → placeholder <rname>, since rname is #REQUIRED."""
    rec = RepositoryRecord(
        address_id=5,
        name="",
        street1="",
        city="",
        state="",
        zip_code="",
        country="",
        phone="",
        email="",
        url="",
    )
    xml = render_repository_xml(rec, change=1700000000)
    assert 'handle="_g_r5"' in xml
    assert 'id="R0005"' in xml
    assert "<rname>Unnamed repository</rname>" in xml


def test_repository_partial_address_emits_address_with_filled_fields() -> None:
    """Some address fields filled, others empty → only the filled ones."""
    rec = RepositoryRecord(
        address_id=6,
        name="Local Library",
        street1="5 Church Lane",
        city="",
        state="",
        zip_code="",
        country="",
        phone="",
        email="",
        url="",
    )
    xml = render_repository_xml(rec, change=1700000000)
    assert "<address>" in xml
    assert "<street>5 Church Lane</street>" in xml
    assert "<city" not in xml  # empty → omitted
    assert "</address>" in xml


def test_repository_xml_special_chars_escaped() -> None:
    """Escape applies to <rname>, <street>, etc."""
    rec = RepositoryRecord(
        address_id=7,
        name='St. Mary & St. John <parish> "church"',
        street1="Church Lane & <north>",
        city="",
        state="",
        zip_code="",
        country="",
        phone="",
        email="",
        url="",
    )
    xml = render_repository_xml(rec, change=1700000000)
    assert (
        "<rname>St. Mary &amp; St. John &lt;parish&gt; "
        "&quot;church&quot;</rname>"
    ) in xml
    assert "<street>Church Lane &amp; &lt;north&gt;</street>" in xml


def test_repository_change_zero_emitted_verbatim() -> None:
    """change=\"0\" is valid; always emit it."""
    rec = RepositoryRecord(
        address_id=8,
        name="x",
        street1="",
        city="",
        state="",
        zip_code="",
        country="",
        phone="",
        email="",
        url="",
    )
    xml = render_repository_xml(rec, change=0)
    assert 'change="0"' in xml