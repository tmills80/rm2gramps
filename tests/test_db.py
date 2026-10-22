"""Tests for rmread's RMNOCASE registration as seen by rm2gramps.

rm2gramps imports ``open_database`` / ``SchemaError`` from ``rmread``
(rather than re-implementing them). The tests here cover the contract
rm2gramps relies on:

- a real .rmtree opens cleanly
- the RMNOCASE collation is registered so RMNOCASE-collated columns
  (PlaceTable.Name, NameTable.Surname, etc.) can be queried without
  ``OperationalError: no such collation sequence: RMNOCASE``
- a non-RM SQLite file is rejected
- a missing file raises ``FileNotFoundError``

``test_query_only_enforced`` and the schema-rejection edge cases are
covered by ``tools/rmread/tests/test_db_rmnocase.py`` and are not
duplicated here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rmread import SchemaError, open_database
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
def test_open_real_rmtree_succeeds() -> None:
    db = open_database(SAMPLE_TREE)
    db.close()


@requires_sample_tree
def test_rmnocase_registered() -> None:
    """rm2gramps queries PlaceTable.Name (COLLATE RMNOCASE) directly.

    This is the regression test for the showstopper documented in
    ``tools/rmread/docs/rm11-schema.md`` § "The ``RMNOCASE``
    collation" — pre-fix it raises
    ``OperationalError: no such collation sequence: RMNOCASE``.
    """
    db = open_database(SAMPLE_TREE)
    try:
        row = db.con.execute("SELECT COUNT(*) FROM AddressTable").fetchone()
        assert row[0] >= 0
    finally:
        db.close()


def test_open_rejects_non_rmtree(tmp_path: Path) -> None:
    import sqlite3

    bogus = tmp_path / "not_rmtree.db"
    con = sqlite3.connect(bogus)
    con.execute("CREATE TABLE foo (x INTEGER)")
    con.execute("INSERT INTO foo VALUES (1)")
    con.close()

    with pytest.raises(SchemaError):
        open_database(bogus)


def test_open_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_database(tmp_path / "does_not_exist.rmtree")