"""Schema conformance of rm2gramps output against Gramps' own DTD.

These are the tests that would have caught the v2.2 element-name
defects. Each renderer had internally-consistent output — the test
suite asserted `<mediaref>` resolved against `<media>` and passed —
but the names themselves were invented, so Gramps would reject the
document on import.

The control for "is the checker itself trustworthy" lives in
``test_grampsdtd.py``, which runs the same matcher against a real
Gramps 6.0.8 export. These tests are the regression guard on rm2gramps
output.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rm2gramps.media import MediaRecord, render_media_xml
from rm2gramps.repositories import RepositoryRecord, render_repository_xml
from rm2gramps.sources import SourceRecord, render_source_xml
from rm2gramps.writer import export_database
from rm2gramps.xml import write_database

from .grampsdtd import GrampsDtd
from ._fixture import sample_tree_path

SAMPLE_TREE = sample_tree_path()
GRAMPS_NS = "http://gramps-project.org/xml/1.7.2/"
CHANGE = 1700000000


def _wrap(inner: str, section: str) -> ET.Element:
    """Parse a fragment inside a minimal but *valid* <database>.

    The DTD requires ``<header>`` as the first child of ``<database>``
    and fixes the order of everything after it, so a shell without a
    header would report a spurious content-model error and mask the
    thing under test.
    """
    return ET.fromstring(
        f'<database xmlns="{GRAMPS_NS}">'
        '<header><created date="2026-01-01" version="rm2gramps/0.2.0"/>'
        "<researcher/></header>"
        f"<{section}>{inner}</{section}>"
        "</database>"
    )


@pytest.fixture(scope="module")
def full_export_root() -> ET.Element:
    if SAMPLE_TREE is None:
        pytest.skip(
            "the RootsMagic sample database is not available; set "
            "RM_SAMPLE_TREE to its path to run this test"
        )
    """Full export of SampleTree.rmtree, parsed. Schema gate for the whole file."""
    return ET.fromstring(export_database(SAMPLE_TREE))


# --- section / element names ---------------------------------------



#: Skip a test that needs the sample database when it is absent.
requires_sample_tree = pytest.mark.skipif(
    SAMPLE_TREE is None,
    reason=(
        "the RootsMagic sample database is not available; set RM_SAMPLE_TREE "
        "to its path to run this test"
    ),
)

def test_media_section_is_named_objects(full_export_root: ET.Element) -> None:
    """The media section is <objects>, not <media>.

    `<!ELEMENT database (header, name-formats?, tags?, events?, people?,
    families?, citations?, sources?, places?, objects?, repositories?,
    notes?, ...)>`. Gramps calls media items "objects"; `media` is not
    a declared element anywhere in the DTD.
    """
    assert full_export_root.find(f"{{{GRAMPS_NS}}}media") is None
    assert full_export_root.find(f"{{{GRAMPS_NS}}}objects") is not None


def test_media_reference_element_is_objref(full_export_root: ET.Element) -> None:
    """Media cross-references are <objref>, not <mediaref>.

    The DTD declares no `mediaref`; every owner element's content model
    lists `objref*` where a media reference belongs (e.g.
    `<!ELEMENT person (gender, name*, eventref*, lds_ord*, objref*, ...>)`).
    """
    assert full_export_root.find(f".//{{{GRAMPS_NS}}}mediaref") is None
    assert full_export_root.find(f".//{{{GRAMPS_NS}}}objref") is not None


def test_citation_has_no_text_child() -> None:
    """<citation> has no <text> child — the transcription belongs to a <note>.

    `<!ELEMENT citation ((daterange|datespan|dateval|datestr)?, page?,
    confidence, noteref*, objref*, srcattribute*, sourceref, tagref*)>`.
    `<text>` is declared in the DTD but only inside `<note>`
    (`<!ELEMENT note (text, style*, tagref*)>`); a real Gramps export
    emits page/confidence/refs on a citation and never a bare <text>.
    """
    from rm2gramps.citations import CitationRecord, render_citation_xml

    rec = CitationRecord(
        citation_id=1,
        source_id=1,
        page="p. 1",
        actual_text="BBBBBB",
        short_footnote="CCCCCC",
    )
    xml = render_citation_xml(rec, change=CHANGE)
    assert "<text>" not in xml
    root = _wrap(xml, "citations")
    assert GrampsDtd().undeclared(root) == {}
    assert GrampsDtd().content_model_errors(root) == []


def test_source_carries_no_sformat_child() -> None:
    """<source> has no <sformat> child.

    `<!ELEMENT source (stitle?, sauthor?, spubinfo?, sabbrev?, noteref*,
    objref*, srcattribute*, reporef*, tagref*)>`. Gramps has no `sformat`
    element at all — `format` only exists inside the optional
    `<name-formats>` header block, as a child of `<format>`.
    """
    xml = render_source_xml(
        SourceRecord(source_id=1, name="AAAAAA", is_private=False), change=CHANGE
    )
    assert "sformat" not in xml
    root = _wrap(xml, "sources")
    assert GrampsDtd().undeclared(root) == {}
    assert GrampsDtd().content_model_errors(root) == []


def test_repository_uses_address_and_type_not_raddr() -> None:
    """<repository> takes (rname, type, address*, url*) — not <raddr>/<rurl>.

    `<!ELEMENT repository (rname, type, address*, url*, noteref*, tagref*)>`.
    `raddr`, `rurl`, `rphone` and a top-level `email` are not declared
    elements; the postal block is an <address> child and the contact
    details are <url href>/<address> children too.
    """
    rec = RepositoryRecord(
        address_id=1,
        name="AAAAAA",
        street1="BBBBBB",
        city="CCCCCC",
        state="DDDDDD",
        zip_code="EEEEEE",
        country="FFFFFF",
        phone="GGGGGG",
        email="HHHHHH",
        url="https://example.invalid/",
    )
    root = _wrap(render_repository_xml(rec, change=CHANGE), "repositories")
    assert GrampsDtd().undeclared(root) == {}
    # Required children per the DTD.
    repo = root.find(
        f"{{{GRAMPS_NS}}}repositories/{{{GRAMPS_NS}}}repository"
    )
    assert repo is not None
    children = [c.tag.split("}")[-1] for c in repo]
    assert children[0] == "rname"
    assert children[1] == "type"
    assert GrampsDtd().content_model_errors(root) == []


def test_media_description_is_a_file_attribute_not_a_child() -> None:
    """<file description="..."> is an attribute; <object> has no <description>.

    `<!ATTLIST file (src CDATA #REQUIRED mime CDATA #REQUIRED checksum
    CDATA #IMPLIED description CDATA #REQUIRED)>` and
    `<!ELEMENT object (file, attribute*, noteref*, date?, citationref*,
    tagref*)>`. A real Gramps export puts the label on the attribute.
    """
    rec = MediaRecord(
        media_id=1,
        media_file="AAAAAA.jpg",
        media_path="/data/AAAAAA.jpg",
        url="",
        media_type=1,
        description="BBBBBB",
    )
    root = _wrap(render_media_xml(rec, change=CHANGE), "objects")
    assert GrampsDtd().undeclared(root) == {}
    assert GrampsDtd().content_model_errors(root) == []
    obj = root.find(f"{{{GRAMPS_NS}}}objects/{{{GRAMPS_NS}}}object")
    assert obj is not None
    assert obj.find(f"{{{GRAMPS_NS}}}description") is None
    file_el = obj.find(f"{{{GRAMPS_NS}}}file")
    assert file_el is not None
    # `description` is #REQUIRED on <file>.
    assert file_el.get("description")


# --- child ordering -------------------------------------------------


def test_child_order_table_matches_the_dtd() -> None:
    """CHILD_ORDER must agree with the vendored DTD, element by element.

    Guards the copy: if a future Gramps release reorders a content
    model, or someone hand-edits CHILD_ORDER, this fails rather than
    the export silently drifting out of spec. The DTD's parenthesised
    date choice is expanded into its four alternatives for comparison.
    """
    import re

    from rm2gramps.schema_order import CHILD_ORDER

    dtd_text = Path(__file__).parent / "data" / "grampsxml.dtd"
    declared = GrampsDtd()
    assert declared.elements >= set(CHILD_ORDER), (
        "CHILD_ORDER names an element the DTD does not declare"
    )
    for name, expected in CHILD_ORDER.items():
        model = declared.content_model(name)
        body = model.strip()[1:-1].strip()
        # Split on commas only: a top-level `|` is inside a parenthesised
        # choice group, which is expanded on the next pass.
        flat: list[str] = []
        for particle in body.split(","):
            particle = particle.strip()
            if particle.startswith("(") and "|" in particle:
                # Drop the occurrence marker first, then exactly one
                # balanced outer pair. str.strip("()") strips any
                # leading/trailing paren *characters*, which mangles
                # "(a|b)?" into "a|b)?" — slice instead.
                inner_group = re.sub(r"[?*+]$", "", particle).strip()
                if inner_group.endswith(")"):
                    inner_group = inner_group[1:-1]
                else:
                    inner_group = inner_group[1:]
                for alt in inner_group.split("|"):
                    flat.append(re.sub(r"[?*+]$", "", alt).strip())
            else:
                flat.append(re.sub(r"[?*+]$", "", particle).strip())
        # Compare as ordered sets: the DTD also models these as open
        # (`...`), and a rank difference here would show up in the
        # content-model test instead.
        assert set(flat) == set(expected), (
            f"<{name}>: CHILD_ORDER has {sorted(set(expected) - set(flat))} "
            f"not in DTD, DTD has {sorted(set(flat) - set(expected))} "
            f"missing from CHILD_ORDER"
        )


def test_reorder_places_person_objref_before_noteref() -> None:
    """<person> puts objref ahead of noteref, per the DTD sequence."""
    from rm2gramps.schema_order import reorder_children

    out = reorder_children(
        '<person handle="_g_x" change="0" id="I0001">'
        "<gender>U</gender>"
        '<noteref hlink="_g_n1"/>'
        '<objref hlink="_g_o1"/>'
        '<citationref hlink="_g_c1"/>'
        "</person>"
    )
    tags = re.findall(r"<(gender|noteref|objref|citationref)", out)
    assert tags == ["gender", "objref", "noteref", "citationref"]


def test_reorder_places_event_objref_after_citationref() -> None:
    """<event> puts objref last, per its own (different) DTD sequence."""
    from rm2gramps.schema_order import reorder_children

    out = reorder_children(
        '<event handle="_g_e1" change="0" id="E0001">'
        "<type>Birth</type>"
        '<objref hlink="_g_o1"/>'
        '<citationref hlink="_g_c1"/>'
        '<noteref hlink="_g_n1"/>'
        '<place hlink="_g_p1"/>'
        "</event>"
    )
    tags = re.findall(r"<(type|place|noteref|citationref|objref)", out)
    assert tags == ["type", "place", "noteref", "citationref", "objref"]


def test_reorder_preserves_repeated_child_order() -> None:
    """Same-name children keep their order — that carries sort-date meaning."""
    from rm2gramps.schema_order import reorder_children

    out = reorder_children(
        '<person handle="_g_x" change="0" id="I0001">'
        '<eventref hlink="_g_e9"/>'
        '<eventref hlink="_g_e2"/>'
        '<eventref hlink="_g_e5"/>'
        '<gender>U</gender>'
        "</person>"
    )
    hlinks = re.findall(r'<eventref hlink="(_g_e\d)"/>', out)
    assert hlinks == ["_g_e9", "_g_e2", "_g_e5"]


def test_reorder_is_a_no_op_on_a_self_closing_element() -> None:
    """A self-closing element has no children to reorder."""
    from rm2gramps.schema_order import reorder_children

    xml = '<event handle="_g_e1" change="0" id="E0001"/>'
    assert reorder_children(xml) == xml


def test_database_sections_follow_dtd_order() -> None:
    """<database> children follow the DTD's declared sequence.

    The DTD puts `citations` before `sources`; v2.1/v2.2 emitted
    `sources` first, so a strict parser rejected the document.
    """
    xml = write_database(
        header_date="2026-01-01",
        version="rm2gramps/0.2.0",
        events=('<event handle="_g_e1" change="0" id="E0001"/>',),
        people=('<person handle="_g_x" change="0" id="I0001">'
                '<gender>U</gender>'
                '<name type="Birth Name"><first>A</first>'
                '<surname>AAAAAA</surname></name>'
                '<attribute type="_UID" value="AAAAAA"/>'
                '</person>',),
        families=('<family handle="_g_f1" change="0" id="F0001">'
                  '<rel>Married</rel>'
                  '</family>',),
        places=('<placeobj handle="_g_p1" change="0" id="P0001" type="Unknown">'
                '<pname><dateval val="1900"/></pname>'
                '</placeobj>',),
        citations=('<citation handle="_g_c1" change="0" id="C0001">'
                   '<confidence>2</confidence>'
                   '<sourceref hlink="_g_s1"/>'
                   '</citation>',),
        sources=('<source handle="_g_s1" change="0" id="S0001">'
                 '<stitle>AAAAAA</stitle>'
                 '</source>',),
    ).decode("utf-8")
    root = ET.fromstring(xml)
    order = [c.tag.split("}")[-1] for c in root]
    assert GrampsDtd().content_model_errors(root) == []
    # Spot-check the two sections the DTD orders against each other.
    assert order.index("citations") < order.index("sources")


# --- whole-document gate -------------------------------------------


def test_full_export_uses_no_undeclared_elements(
    full_export_root: ET.Element,
) -> None:
    """No element in a real SampleTree export is outside the DTD."""
    assert GrampsDtd().undeclared(full_export_root) == {}


def test_full_export_satisfies_every_content_model(
    full_export_root: ET.Element,
) -> None:
    """No element in a real SampleTree export breaks its declared model."""
    assert GrampsDtd().content_model_errors(full_export_root) == []
