"""Tests for rm2gramps.citationrefs — string-level citationref injection.

Pure string transformer; tested with synthetic XML strings. No
sqlite3, no fixtures.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from rm2gramps.citationrefs import inject_citationrefs


GRAMPS_NS = "http://gramps-project.org/xml/1.7.2/"


def test_empty_citation_ids_returns_unchanged() -> None:
    """No citation IDs → XML is returned verbatim."""
    xml = '<person handle="_g_abc" change="0" id="I0001"/>'
    assert inject_citationrefs(xml, ()) == xml


def test_single_citation_ref_inserted_before_close() -> None:
    """One citation ref lands just before the </person> closing tag."""
    xml = '<person handle="_g_abc" change="0" id="I0001"><gender>M</gender></person>'
    out = inject_citationrefs(xml, (42,))
    assert out == (
        '<person handle="_g_abc" change="0" id="I0001"><gender>M</gender>'
        '<citationref hlink="_g_c42"/></person>'
    )


def test_multiple_citation_refs_preserve_order() -> None:
    """Citation refs appear in the order passed; Gramps convention
    is to render refs in CitationLinkTable.SortOrder which the
    walker already sorts."""
    xml = '<event handle="_g_e1" change="0" id="E0001"><type>Birth</type></event>'
    out = inject_citationrefs(xml, (10, 11, 12))
    assert (
        '<event handle="_g_e1" change="0" id="E0001"><type>Birth</type>'
        '<citationref hlink="_g_c10"/>'
        '<citationref hlink="_g_c11"/>'
        '<citationref hlink="_g_c12"/>'
        '</event>'
    ) == out


def test_output_xml_parses_with_xml_etree() -> None:
    """The injection produces well-formed XML that ElementTree
    parses cleanly with the Gramps namespace."""
    xml = (
        '<family handle="_g_f1" change="0" id="F0001">'
        '<rel type="Married"/>'
        '</family>'
    )
    out = inject_citationrefs(xml, (5, 6))
    # Wrap in a root so ET can parse a single element.
    root = ET.fromstring(f'<root xmlns="{GRAMPS_NS}">{out}</root>')
    fam = root.find(f"{{{GRAMPS_NS}}}family")
    assert fam is not None
    refs = fam.findall(f"{{{GRAMPS_NS}}}citationref")
    assert len(refs) == 2
    assert refs[0].get("hlink") == "_g_c5"
    assert refs[1].get("hlink") == "_g_c6"


def test_injection_after_existing_children() -> None:
    """citationrefs go after existing children (eventref, childof,
    parentin, attribute) but before the closing tag."""
    xml = (
        '<person handle="_g_abc" change="0" id="I0001">'
        '<gender>M</gender>'
        '<eventref hlink="_g_e1" role="Primary"/>'
        '<childof hlink="_g_f1"/>'
        '<attribute type="_UID" value="abc"/>'
        '</person>'
    )
    out = inject_citationrefs(xml, (42,))
    assert out == (
        '<person handle="_g_abc" change="0" id="I0001">'
        '<gender>M</gender>'
        '<eventref hlink="_g_e1" role="Primary"/>'
        '<childof hlink="_g_f1"/>'
        '<attribute type="_UID" value="abc"/>'
        '<citationref hlink="_g_c42"/>'
        '</person>'
    )


def test_no_closing_tag_returns_unchanged() -> None:
    """Defensive: malformed input (no </tag>) returns unchanged."""
    xml = '<person handle="_g_abc" change="0" id="I0001"'
    assert inject_citationrefs(xml, (42,)) == xml