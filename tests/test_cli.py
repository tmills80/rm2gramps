"""Tests for rm2gramps.cli.export — argparse CLI entry point.

T9 (CLI half): the CLI opens the input .rmtree, walks the DB, and
writes a (gzipped) .gramps to disk. It is a thin shim over
``rm2gramps.writer.export_database`` and ``gzip.GzipFile``.

Cases from ``tools/rm2gramps/plans/rm2gramps.md`` § T9:
- default: output is gzipped (magic bytes ``\\x1f\\x8b``)
- ``--no-gzip``: output is raw XML (starts with ``<?xml``)
- ``--person-ids``: subset the export
- missing input: exit code 2, error on stderr
- invalid input: exit code 2, "not a RootsMagic database" on stderr
- ``--help``: argparse-style
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from rm2gramps.cli.export import main
from ._fixture import sample_tree_path


SAMPLE_TREE = sample_tree_path()



#: Skip a test that needs the sample database when it is absent.
requires_sample_tree = pytest.mark.skipif(
    SAMPLE_TREE is None,
    reason=(
        "the RootsMagic sample database is not available; set RM_SAMPLE_TREE "
        "to its path to run this test"
    ),
)

@requires_sample_tree
def test_cli_writes_gzipped_file_by_default(tmp_path: Path) -> None:
    """Default output is gzip-compressed (magic bytes 0x1f 0x8b)."""
    out = tmp_path / "out.gramps"
    rc = main([str(SAMPLE_TREE), str(out)])
    assert rc == 0
    data = out.read_bytes()
    assert data[:2] == b"\x1f\x8b", "output not gzipped"


@requires_sample_tree
def test_cli_no_gzip_writes_raw_xml(tmp_path: Path) -> None:
    """``--no-gzip`` produces raw XML starting with the declaration."""
    out = tmp_path / "out.gramps"
    rc = main([str(SAMPLE_TREE), str(out), "--no-gzip"])
    assert rc == 0
    data = out.read_bytes()
    assert data.startswith(b"<?xml")
    # Verify the gzipped content is also valid XML when gunzipped.
    gz_out = tmp_path / "out.gramps.gz"
    rc = main([str(SAMPLE_TREE), str(gz_out)])
    assert rc == 0
    with gzip.open(gz_out, "rb") as f:
        raw = f.read()
    assert raw.startswith(b"<?xml")


@requires_sample_tree
def test_cli_person_ids_subset(tmp_path: Path) -> None:
    """``--person-ids 1,2`` restricts the export to those PersonIDs."""
    import sqlite3
    import unicodedata
    import xml.etree.ElementTree as ET

    # Resolve two real PersonIDs from the DB so the test is robust.
    con = sqlite3.connect(f"file:{SAMPLE_TREE}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    con.create_collation(
        "RMNOCASE",
        lambda s, _n=None: None if s is None else "".join(
            c for c in unicodedata.normalize("NFKD", str(s))
            if not unicodedata.combining(c)
        ).casefold(),
    )
    ids = [r[0] for r in con.execute(
        "SELECT PersonID FROM PersonTable ORDER BY PersonID LIMIT 2"
    ).fetchall()]
    con.close()

    out = tmp_path / "subset.gramps"
    rc = main([str(SAMPLE_TREE), str(out), "--no-gzip",
               "--person-ids", ",".join(str(i) for i in ids)])
    assert rc == 0
    ns = "{http://gramps-project.org/xml/1.7.2/}"
    root = ET.fromstring(out.read_bytes())
    people = root.findall(f"{ns}people/{ns}person")
    assert len(people) == 2

    # v2.1 narrowing: citations get filtered too. The full export
    # has more citations than the subset export because citations
    # are restricted to those referenced by exported owners.
    citations_sub = root.findall(f"{ns}citations/{ns}citation")
    sub_count = len(citations_sub)
    assert sub_count > 0, "subset export should still have citations"

    # Run again with no --person-ids (full export) and compare.
    full_out = tmp_path / "full.gramps"
    rc = main([str(SAMPLE_TREE), str(full_out), "--no-gzip"])
    assert rc == 0
    full_root = ET.fromstring(full_out.read_bytes())
    full_count = len(full_root.findall(f"{ns}citations/{ns}citation"))
    assert full_count > sub_count, (
        f"subset citations ({sub_count}) should be < full citations "
        f"({full_count}) — narrowing didn't narrow"
    )

    # v2.2 narrowing: media + repositories also narrow with
    # --person-ids because they're linked to exported owners.
    #
    # Strict `<` — this previously asserted `<=`, which passes when
    # narrowing is entirely absent (subset == full). Both were
    # equal-by-default, so the assertion could not fail.
    for section, elem, label in (
        ("objects", "object", "objects"),
        ("repositories", "repository", "repositories"),
        ("sources", "source", "sources"),
        ("places", "placeobj", "places"),
    ):
        sub_n = len(root.findall(f"{ns}{section}/{ns}{elem}"))
        full_n = len(full_root.findall(f"{ns}{section}/{ns}{elem}"))
        assert sub_n < full_n, (
            f"subset {label} ({sub_n}) should be < full {label} "
            f"({full_n}) — narrowing didn't narrow"
        )


def test_cli_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out.gramps"
    rc = main([str(tmp_path / "does_not_exist.rmtree"), str(out)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower() or "doesnotexist" in captured.err.lower()


def test_cli_invalid_rmtree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import sqlite3

    bogus = tmp_path / "not_rmtree.db"
    con = sqlite3.connect(bogus)
    con.execute("CREATE TABLE foo (x INTEGER)")
    con.execute("INSERT INTO foo VALUES (1)")
    con.close()

    out = tmp_path / "out.gramps"
    rc = main([str(bogus), str(out)])
    assert rc == 2
    captured = capsys.readouterr()
    # The CLI surfaces rmread's schema-rejection message verbatim —
    # for a non-RM SQLite file, that message names ConfigTable. The
    # important contract is "exit 2 and no .gramps written", not the
    # exact wording, which is rmread's responsibility.
    assert "configtable" in captured.err.lower()
    assert not out.exists(), "invalid input must not produce an output file"


def test_cli_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0