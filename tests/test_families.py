"""Tests for rm2gramps.families — FamilyTable row → <family> element.

T6 cases from ``tools/rm2gramps/plans/rm2gramps.md`` § T6:

- both parents → <family> with <father>, <mother>, <rel type="Married"/>
- single parent (father only) → <rel type="Unknown"/>, no <mother>
- no parents → <rel type="Unknown"/>, no <father>/<mother>
- children from ChildTable ordered by ChildOrder → <childref> list
- family-attached events (OwnerType=1) → <eventref role="Family">

The renderer takes a populated :class:`FamilyRecord` plus the
per-family ChildRef / event-id lists the writer assembles from a
live DB query. We deliberately don't query sqlite3 inside this
module — same pure-renderer pattern as ``events.py`` / ``places.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from rm2gramps.families import (
    ChildRef,
    FamilyRecord,
    render_family_xml,
)


def test_family_with_both_parents() -> None:
    """Canonical family: father + mother → Married relationship."""
    rec = FamilyRecord(
        family_id=12,
        father_uid="AAAA1111",   # any string stands in for a UniqueID
        mother_uid="BBBB2222",
        father_id=7,
        mother_id=8,
        children=(
            ChildRef(child_id=1, child_uid="CCCC3333", child_order=0),
        ),
        family_event_ids=(),
    )
    xml = render_family_xml(rec, change=1700000000)
    assert xml == (
        '<family handle="_g_f12" change="1700000000" id="F0012">'
        '<rel type="Married"/>'
        '<father hlink="_g_aaaa1111"/>'
        '<mother hlink="_g_bbbb2222"/>'
        '<childref hlink="_g_cccc3333"/>'
        '</family>'
    )


def test_family_single_parent() -> None:
    """Only father → no <mother>, <rel type="Unknown"/>."""
    rec = FamilyRecord(
        family_id=13,
        father_uid="DDDD4444",
        mother_uid="",
        father_id=9,
        mother_id=0,
        children=(),
        family_event_ids=(),
    )
    xml = render_family_xml(rec, change=1700000000)
    assert "<rel type=\"Unknown\"/>" in xml
    assert "<father hlink=\"_g_dddd4444\"/>" in xml
    assert "<mother" not in xml


def test_family_with_no_parents() -> None:
    """No parents → still emit the wrapper, <rel type="Unknown"/>."""
    rec = FamilyRecord(
        family_id=14,
        father_uid="",
        mother_uid="",
        father_id=0,
        mother_id=0,
        children=(),
        family_event_ids=(),
    )
    xml = render_family_xml(rec, change=1700000000)
    assert "<rel type=\"Unknown\"/>" in xml
    assert "<father" not in xml
    assert "<mother" not in xml
    # wrapper still emitted so id/handle resolve
    assert 'handle="_g_f14"' in xml
    assert 'id="F0014"' in xml


def test_family_children_from_child_table_order() -> None:
    """ChildRefs render in the order passed (ChildTable.ChildOrder)."""
    rec = FamilyRecord(
        family_id=15,
        father_uid="EEEE5555",
        mother_uid="FFFF6666",
        father_id=10,
        mother_id=11,
        children=(
            ChildRef(child_id=2, child_uid="GGGG7777", child_order=0),
            ChildRef(child_id=3, child_uid="HHHH8888", child_order=1),
            ChildRef(child_id=4, child_uid="IIII9999", child_order=2),
        ),
        family_event_ids=(),
    )
    xml = render_family_xml(rec, change=1700000000)
    # Each childref should appear, in order, with the right handles.
    g_idx = xml.find('hlink="_g_gggg7777"')
    h_idx = xml.find('hlink="_g_hhhh8888"')
    i_idx = xml.find('hlink="_g_iiii9999"')
    assert g_idx != -1 and h_idx != -1 and i_idx != -1
    assert g_idx < h_idx < i_idx


def test_family_event_refs_use_family_role() -> None:
    """Events owned by the family (OwnerType=1) → <eventref role=\"Family\">."""
    rec = FamilyRecord(
        family_id=16,
        father_uid="JJJJ0000",
        mother_uid="KKKK1111",
        father_id=12,
        mother_id=13,
        children=(),
        family_event_ids=(40, 41),
    )
    xml = render_family_xml(rec, change=1700000000)
    assert '<eventref hlink="_g_e40" role="Family"/>' in xml
    assert '<eventref hlink="_g_e41" role="Family"/>' in xml


def test_family_no_married_relationship_when_both_parents_absent_or_when_only_one() -> (
    None
):
    """<rel type=\"Married\"/> is only emitted when both parents exist."""
    # Both parents present → Married (already covered). Only one → Unknown.
    rec_one = FamilyRecord(
        family_id=17,
        father_uid="AAAA1111",
        mother_uid="",
        father_id=1,
        mother_id=0,
        children=(),
        family_event_ids=(),
    )
    xml_one = render_family_xml(rec_one, change=1700000000)
    assert "<rel type=\"Unknown\"/>" in xml_one
    assert "<rel type=\"Married\"/>" not in xml_one


def test_family_change_zero_emitted_verbatim() -> None:
    """change=\"0\" is valid; always emit it."""
    rec = FamilyRecord(
        family_id=18,
        father_uid="",
        mother_uid="",
        father_id=0,
        mother_id=0,
        children=(),
        family_event_ids=(),
    )
    xml = render_family_xml(rec, change=0)
    assert 'change="0"' in xml