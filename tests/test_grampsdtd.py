"""The DTD matcher itself, checked against a minimal hand-built control.

The strongest available control would be a real Gramps export, but
`example.gramps` must not be committed to this repo (it is real
research data). So the control is built here from the shapes the
Gramps DTD and Gramps' own documentation agree on — deliberately
including the constructs that broke earlier versions of this matcher
(`(source)*` containers, `(#PCDATA)` text content, nested choice
groups, open `...` models).

``test_grampsdtd.py`` also pins that the matcher *rejects* the
element names rm2gramps used to invent, so a schema regression can
never be "fixed" by loosening a broken matcher.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from .grampsdtd import GrampsDtd

GRAMPS_NS = "http://gramps-project.org/xml/1.7.2/"

# Optional: when a real Gramps export is present locally (it is not
# committed), use it as the control in preference to the synthetic one.
EXAMPLE = Path(__file__).parent / "data" / "example.gramps"


def _control_document() -> ET.Element:
    """A document exercising every content-model shape in the DTD.

    Shapes included deliberately:
      - `(source)*`            container with an occurrence marker
      - `(#PCDATA)`            text-only content (`<rname>`)
      - `((a|b)?)`             nested optional choice (`<placeref>`)
      - `(a, b?, c*)...`       open model with a mid-sequence choice
      - `EMPTY`                `<place hlink="…"/>` inside `<event>`
    """
    return ET.fromstring(
        f'<database xmlns="{GRAMPS_NS}">'
        "<header><created date=\"2026-01-01\" version=\"6.0.8\"/>"
        "<researcher/></header>"
        "<events>"
        '<event handle="_e1" change="0" id="E0000">'
        "<type>Birth</type><dateval val=\"1980-11-20\"/>"
        '<place hlink="_p1"/><description>born</description>'
        "</event>"
        "</events>"
        "<people>"
        '<person handle="_pp1" change="0" id="I0000">'
        "<gender>F</gender>"
        '<name type="Birth Name"><first>A</first><surname>AAAAAA</surname></name>'
        '<eventref hlink="_e1" role="Primary"/>'
        '<objref hlink="_o1"/>'
        '<attribute type="_UID" value="AAAAAA"/>'
        '<childof hlink="_f1"/>'
        '<noteref hlink="_n1"/>'
        '<citationref hlink="_c1"/>'
        "</person>"
        "</people>"
        "<families>"
        '<family handle="_f1" change="0" id="F0000"><rel>Married</rel>'
        '<father hlink="_pp1"/><eventref hlink="_e1"/><childref hlink="_pp1"/>'
        "</family>"
        "</families>"
        "<citations>"
        '<citation handle="_c1" change="0" id="C0000">'
        "<dateval val=\"1900\"/><page>p. 1</page><confidence>2</confidence>"
        '<noteref hlink="_n1"/><objref hlink="_o1"/><sourceref hlink="_s1"/>'
        "</citation>"
        "</citations>"
        "<sources>"
        '<source handle="_s1" change="0" id="S0000"><stitle>AAAAAA</stitle>'
        '<sabbrev>A</sabbrev><objref hlink="_o1"/><reporef hlink="_r1"/>'
        "</source>"
        "</sources>"
        "<places>"
        '<placeobj handle="_p1" change="0" id="P0000" type="Unknown">'
        "<ptitle>AAAAAA</ptitle>"
        "<pname><dateval val=\"1900\"/></pname>"
        '<placeref hlink="_p1"/><location><locality>AAAAAA</locality></location>'
        '<objref hlink="_o1"/><citationref hlink="_c1"/>'
        "</placeobj>"
        "</places>"
        "<objects>"
        '<object handle="_o1" change="0" id="O0000">'
        '<file src="AAAAAA.jpg" mime="image/jpeg" description="AAAAAA"/>'
        '<noteref hlink="_n1"/><citationref hlink="_c1"/>'
        "</object>"
        "</objects>"
        "<repositories>"
        '<repository handle="_r1" change="0" id="R0000">'
        "<rname>AAAAAA</rname><type>Library</type>"
        "<address><street>AAAAAA</street><city>BBBBBB</city>"
        "<state>CCCCCC</state><country>EEEEEE</country>"
        "<postal>DDDDDD</postal><phone>FFFFFF</phone></address>"
        '<url href="https://example.invalid/" type="Web Home" '
        'description="AAAAAA"/>'
        "</repository>"
        "</repositories>"
        "<notes>"
        '<note handle="_n1" change="0" id="N0000" type="Person Note">'
        "<text>AAAAAA</text></note>"
        "</notes>"
        "</database>"
    )


def test_matcher_finds_the_known_schema_facts() -> None:
    """The DTD says objects/objref, not media/mediaref."""
    dtd = GrampsDtd()
    assert "objects" in dtd.elements
    assert "objref" in dtd.elements
    # These are rm2gramps' inventions; the DTD never declares them.
    assert "media" not in dtd.elements
    assert "mediaref" not in dtd.elements


def test_control_document_declares_no_unknown_elements() -> None:
    """A conformant document must come out clean of undeclared elements."""
    assert GrampsDtd().undeclared(_control_document()) == {}


def test_control_document_satisfies_every_content_model() -> None:
    """A conformant document must satisfy every declared content model."""
    assert GrampsDtd().content_model_errors(_control_document()) == []


@pytest.mark.skipif(
    not EXAMPLE.exists(), reason="real Gramps export not committed to this repo"
)
def test_real_gramps_export_declares_no_unknown_elements() -> None:
    """When a real export is available, it must also come out clean."""
    import gzip

    root = ET.fromstring(gzip.open(EXAMPLE, "rb").read())
    assert GrampsDtd().undeclared(root) == {}


def test_matcher_rejects_a_known_bad_document() -> None:
    """The matcher must actually bite — control test, not a rubber stamp.

    A matcher that accepts anything would pass the tests above for the
    wrong reason. This pins that rm2gramps' own (wrong) element names
    are rejected.
    """
    bad = ET.fromstring(
        f'<database xmlns="{GRAMPS_NS}">'
        "<sources><source><sformat>book</sformat></source></sources>"
        "</database>"
    )
    assert GrampsDtd().undeclared(bad) == {"sformat": 1}


def test_matcher_rejects_children_in_the_wrong_order() -> None:
    """A required-child sequence violation must be caught, not tolerated."""
    bad = ET.fromstring(
        f'<database xmlns="{GRAMPS_NS}">'
        "<repositories>"
        '<repository handle="_r1" change="0" id="R0000">'
        "<type>Library</type><rname>AAAAAA</rname>"
        "</repository>"
        "</repositories>"
        "</database>"
    )
    # `rname` and `type` are swapped relative to `(rname, type, ...)`.
    assert GrampsDtd().content_model_errors(bad) != []
