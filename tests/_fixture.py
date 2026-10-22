"""Locate the RootsMagic sample database used by the integration tests.

`SampleTree.rmtree` is a real (anonymised) RootsMagic 11 database. It is
gitignored, so it is not present in a fresh clone, and it lives wherever
the maintainer keeps it. Its location is therefore configurable:

* ``RM_SAMPLE_TREE`` environment variable — an explicit path; or
* any directory at or above this package, which is where it has been
  kept (the repository root in a checkout, the package root once the
  tool is split out into its own repository).

When neither yields a file, the tests that need it are *skipped* rather
than failing. A fresh clone without the fixture is a normal state, not a
broken one.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Environment variable naming the sample database.
ENV_VAR = "RM_SAMPLE_TREE"

#: The file name of the sample database.
FIXTURE_NAME = "SampleTree.rmtree"

#: How far up the directory tree to look for the fixture.
_SEARCH_DEPTH = 4


def sample_tree_path() -> Path | None:
    """The path to the sample database, or None when it is not available."""
    from_env = os.environ.get(ENV_VAR)
    if from_env:
        candidate = Path(from_env).expanduser()
        return candidate if candidate.is_file() else None

    # Walk up from this file: the package's own directory, then each
    # ancestor, which is where the fixture has been kept.
    here = Path(__file__).resolve().parent
    for directory in (here, *here.parents[:_SEARCH_DEPTH]):
        candidate = directory / FIXTURE_NAME
        if candidate.is_file():
            return candidate
    return None
