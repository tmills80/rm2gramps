"""Tests for rm2gramps.xml — top-level <database> writer.

T8 cases from ``tools/rm2gramps/plans/rm2gramps.md`` § T8:

- writer emits the required root attributes (xmlns + version + the
  correct DTD / encoding prolog) and a <header> with <created> and
  empty <researcher>
- writer emits a valid empty database (header + four empty child
  sections) so an empty file is still importable into Gramps
- writer orders sections events → people → families → places

Pure unit tests — no live sqlite3, no gzip file IO. The gzip /
file-writing wrapper is tested in T9 (CLI).
"""

from __future__ import annotations

from rm2gramps.xml import write_database


def _capture(*, header_date: str = "2026-01-01", version: str = "rm2gramps/0.0.1",
             events: tuple[str, ...] = (),
             people: tuple[str, ...] = (),
             families: tuple[str, ...] = (),
             places: tuple[str, ...] = ()) -> str:
    """Run write_database and return the rendered XML string.

    write_database returns bytes (XML declaration is explicit); we
    decode here so the assertions are readable.
    """
    return write_database(
        header_date=header_date,
        version=version,
        events=events,
        people=people,
        families=families,
        places=places,
    ).decode("utf-8")


def test_writer_emits_required_root_attributes() -> None:
    """Prolog + namespace + <header> with <created> + empty <researcher>."""
    xml = _capture()
    # XML declaration with explicit encoding
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    # Gramps DTD
    assert (
        '<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.2//EN" '
        '"http://gramps-project.org/xml/1.7.2/grampsxml.dtd">'
    ) in xml
    # Root element with the Gramps 1.7.2 namespace
    assert '<database xmlns="http://gramps-project.org/xml/1.7.2/">' in xml
    # Header
    assert '<header>' in xml
    assert '<created date="2026-01-01" version="rm2gramps/0.0.1"/>' in xml
    assert '<researcher/>' in xml


def test_writer_emits_empty_database_with_four_sections() -> None:
    """Empty inputs still produce a valid <database> with all four child sections."""
    xml = _capture()
    assert "<events>" in xml
    assert "</events>" in xml
    assert "<people>" in xml
    assert "</people>" in xml
    assert "<families>" in xml
    assert "</families>" in xml
    assert "<places>" in xml
    assert "</places>" in xml
    # No actual event/person/family/place bodies
    assert "<event " not in xml
    assert "<person " not in xml
    assert "<family " not in xml
    assert "<placeobj " not in xml


def test_writer_orders_sections_events_people_families_places() -> None:
    """Section order matches Gramps' own convention (and the plan)."""
    xml = _capture(
        events=('<event handle="_g_e1" change="0" id="E0001"/>',),
        people=('<person handle="_g_x" change="0" id="I0001"/>',),
        families=('<family handle="_g_f1" change="0" id="F0001"/>',),
        places=('<placeobj handle="_g_p1" change="0" id="P0001"/>',),
    )
    e_idx = xml.find("<events>")
    p_idx = xml.find("<people>")
    f_idx = xml.find("<families>")
    pl_idx = xml.find("<places>")
    assert e_idx != -1 and p_idx != -1 and f_idx != -1 and pl_idx != -1
    assert e_idx < p_idx < f_idx < pl_idx


def test_writer_emits_inner_content_inside_section() -> None:
    """Section bodies land inside the section wrappers, not outside."""
    xml = _capture(
        events=('<event handle="_g_e42" change="0" id="E0042"/>',),
    )
    events_open = xml.find("<events>")
    events_close = xml.find("</events>")
    body = xml.find('handle="_g_e42"')
    assert events_open != -1 and events_close != -1 and body != -1
    assert events_open < body < events_close


def test_writer_returns_bytes_with_utf8_encoding() -> None:
    """write_database returns bytes (UTF-8 encoded), not str."""
    out = write_database(
        header_date="2026-01-01",
        version="rm2gramps/0.0.1",
        events=(),
        people=(),
        families=(),
        places=(),
    )
    assert isinstance(out, bytes)
    # Round-trip a non-ASCII name to prove UTF-8 (not latin-1).
    out2 = write_database(
        header_date="2026-01-01",
        version="rm2gramps/0.0.1",
        events=(),
        people=('<person handle="_g_xx" change="0" id="I0001">'
                '<gender>U</gender>'
                '<name type="Birth Name"><first>Müller</first><surname>Ångström</surname></name>'
                '<attribute type="_UID" value="xx"/>'
                '</person>',),
        families=(),
        places=(),
    )
    # Müller → M\xC3\xBC, Ångström → \xC3\x85ngstr\xC3\xB6m
    assert b"M\xc3\xbc" in out2
    assert b"\xc3\x85ngstr\xc3\xb6m" in out2
    assert "Müller" in out2.decode("utf-8")
    assert "Ångström" in out2.decode("utf-8")