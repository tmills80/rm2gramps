"""The sample-database fixture resolves, and its absence skips cleanly."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from ._fixture import ENV_VAR, FIXTURE_NAME, sample_tree_path


def test_env_var_names_a_real_file(tmp_path: Path) -> None:
    """``RM_SAMPLE_TREE`` points at the fixture when it names a real file."""
    fake = tmp_path / FIXTURE_NAME
    fake.write_bytes(b"not really a database")
    os.environ[ENV_VAR] = str(fake)
    try:
        assert sample_tree_path() == fake
    finally:
        del os.environ[ENV_VAR]


def test_env_var_naming_a_missing_file_yields_none(tmp_path: Path) -> None:
    """A ``RM_SAMPLE_TREE`` that names a missing file does not fall back."""
    os.environ[ENV_VAR] = str(tmp_path / "absent.rmtree")
    try:
        assert sample_tree_path() is None
    finally:
        del os.environ[ENV_VAR]


#: An absolute filesystem path literal — a path passed to `Path(...)`
#: or opened as a file. A bare `/`-prefixed string that is *data* (a
#: media path in a fixture, say) is not matched: it names something
#: inside a record, not a location on this machine.
ABSOLUTE_PATH = re.compile(
    r"""Path\(\s*["']/(?:home|Users|root|tmp|var|opt|mnt|media)"""
)


def test_no_absolute_paths_are_hard_coded() -> None:
    """No test file hard-codes an absolute path to the fixture.

    A hard-coded path is valid on exactly one machine and fails
    everywhere else; the fixture is located at runtime instead.
    """
    here = Path(__file__).resolve().parent
    this_file = Path(__file__).name
    offenders = [
        str(path.relative_to(here))
        for path in sorted(here.rglob("*.py"))
        if path.name != this_file
        and ABSOLUTE_PATH.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "these test files hard-code an absolute path: " f"{offenders}"
    )


def test_missing_fixture_skips_rather_than_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no fixture anywhere, the DB-backed tests skip, not fail."""
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "absent.rmtree"))
    # The repository-root fallback must not find one either.
    monkeypatch.setattr(
        "tests._fixture.Path.is_file", lambda self: False, raising=False
    )
    assert sample_tree_path() is None
