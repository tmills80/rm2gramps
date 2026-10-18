"""Tests for rm2gramps.people — PersonTable + NameTable rows → <person>.

T7 cases from ``tools/rm2gramps/plans/rm2gramps.md`` § T7:

- person minimum (gender, primary name, _UID attribute)
- eventrefs in chronological (SortDate) order
- childof / parentin walks via ChildTable → FamilyTable
- gender mapping: RM Sex 0/1/2 → Gramps U/M/F
- alt names: multiple NameTable rows → multiple <name> elements,
  NameType=0 stays ``Birth Name``, others mapped to Gramps strings

Pure renderer pattern matches events.py / places.py / families.py:
takes pre-loaded dataclasses (``PersonRecord`` + tuples for
events / parent families / child families / alt names) and returns
one <person> XML string. The writer is responsible for the SQL
walk that produces those tuples.
"""

from __future__ import annotations

from dataclasses import dataclass

from rm2gramps.people import (
    NameRecord,
    PersonRecord,
    render_person_xml,
)


def test_person_minimum() -> None:
    """Primary name → <name type=\"Birth Name\">; gender from Sex; _UID attribute."""
    rec = PersonRecord(
        person_id=1,
        unique_id="B4D8A126626343AE",
        sex=1,
        primary_name=NameRecord(
            surname="Mills",
            given="Tristan William Ernest",
            prefix="",
            suffix="",
        ),
        alt_names=(),
        event_refs=(),
        parent_families=(),
        child_families=(),
    )
    xml = render_person_xml(rec, change=1748502000)
    assert xml == (
        '<person handle="_g_b4d8a126626343ae" '
        'change="1748502000" id="I0001">'
        '<gender>M</gender>'
        '<name type="Birth Name">'
        '<first>Tristan William Ernest</first>'
        '<surname>Mills</surname>'
        '</name>'
        '<attribute type="_UID" value="B4D8A126626343AE"/>'
        '</person>'
    )


def test_person_gender_unknown() -> None:
    """RM Sex=0 (unknown) → <gender>U</gender>."""
    rec = PersonRecord(
        person_id=2,
        unique_id="CCCC0000",
        sex=0,
        primary_name=NameRecord(
            surname="Doe", given="Jane", prefix="", suffix="",
        ),
        alt_names=(),
        event_refs=(),
        parent_families=(),
        child_families=(),
    )
    xml = render_person_xml(rec, change=1700000000)
    assert "<gender>U</gender>" in xml


def test_person_gender_female() -> None:
    """RM Sex=2 → <gender>F</gender>."""
    rec = PersonRecord(
        person_id=3,
        unique_id="DDDD1111",
        sex=2,
        primary_name=NameRecord(
            surname="Doe", given="Jane", prefix="", suffix="",
        ),
        alt_names=(),
        event_refs=(),
        parent_families=(),
        child_families=(),
    )
    xml = render_person_xml(rec, change=1700000000)
    assert "<gender>F</gender>" in xml


def test_person_eventrefs_in_caller_order() -> None:
    """Events render in the order the caller passes (writer sorts by SortDate)."""
    # Event 10 is primary, 11 is not, 12 is primary — verifies the
    # Primary role is attached iff is_primary is True.
    rec = PersonRecord(
        person_id=4,
        unique_id="EEEE2222",
        sex=1,
        primary_name=NameRecord(
            surname="Smith", given="John", prefix="", suffix="",
        ),
        alt_names=(),
        event_refs=((10, True), (11, False), (12, True)),
        parent_families=(),
        child_families=(),
    )
    xml = render_person_xml(rec, change=1700000000)
    a = xml.find('hlink="_g_e10"')
    b = xml.find('hlink="_g_e11"')
    c = xml.find('hlink="_g_e12"')
    assert a != -1 and b != -1 and c != -1
    assert a < b < c
    assert 'hlink="_g_e10" role="Primary"' in xml
    assert 'hlink="_g_e11" role="Primary"' not in xml
    assert 'hlink="_g_e12" role="Primary"' in xml


def test_person_childof_and_parentin() -> None:
    """ChildTable walks → one <childof> per parent family; one <parentin> per family-as-parent."""
    rec = PersonRecord(
        person_id=5,
        unique_id="FFFF3333",
        sex=1,
        primary_name=NameRecord(
            surname="Carter", given="Howard", prefix="", suffix="",
        ),
        alt_names=(),
        event_refs=(),
        parent_families=(20,),
        child_families=(30, 31),
    )
    xml = render_person_xml(rec, change=1700000000)
    assert '<childof hlink="_g_f20"/>' in xml
    assert '<parentin hlink="_g_f30"/>' in xml
    assert '<parentin hlink="_g_f31"/>' in xml
    # exactly two parentin, one childof
    assert xml.count("<parentin") == 2
    assert xml.count("<childof") == 1


def test_person_alt_names() -> None:
    """Multiple NameTable rows → multiple <name> elements; NameType=0 is Birth Name."""
    rec = PersonRecord(
        person_id=6,
        unique_id="GGGG4444",
        sex=2,
        primary_name=NameRecord(
            surname="Bloggs",
            given="Mary Ann",
            prefix="",
            suffix="",
            name_type=0,
            is_primary=True,
        ),
        alt_names=(
            NameRecord(
                surname="Bloggs",
                given="Mary Ann",
                prefix="",
                suffix="",
                name_type=1,
                is_primary=False,
            ),
        ),
        event_refs=(),
        parent_families=(),
        child_families=(),
    )
    xml = render_person_xml(rec, change=1700000000)
    # primary name stays "Birth Name"; alt name (NameType=1) becomes "Married Name"
    assert '<name type="Birth Name">' in xml
    assert '<name type="Married Name">' in xml


def test_person_change_zero_emitted_verbatim() -> None:
    rec = PersonRecord(
        person_id=7,
        unique_id="HHHH5555",
        sex=0,
        primary_name=NameRecord(
            surname="X", given="Y", prefix="", suffix="",
        ),
        alt_names=(),
        event_refs=(),
        parent_families=(),
        child_families=(),
    )
    xml = render_person_xml(rec, change=0)
    assert 'change="0"' in xml


def test_person_empty_given_and_surname_still_emits_name() -> None:
    """A person with no recorded name → still emit a <name> wrapper, no <first>/<surname>."""
    rec = PersonRecord(
        person_id=8,
        unique_id="IIII6666",
        sex=0,
        primary_name=NameRecord(surname="", given="", prefix="", suffix=""),
        alt_names=(),
        event_refs=(),
        parent_families=(),
        child_families=(),
    )
    xml = render_person_xml(rec, change=1700000000)
    assert '<name type="Birth Name">' in xml
    assert "</name>" in xml
    assert "<first" not in xml
    assert "<surname" not in xml