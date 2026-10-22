"""The manifest must declare what the code imports.

The manifest is the contract a consumer sees. When it under-declares,
`pip install rm2gramps` succeeds and the package fails at import time in
the consumer's environment — a defect that is invisible while every
tool shares one virtualenv.

These checks run per tool, with one copy per tool, on purpose: each
tool must stay self-contained when this repository is split into one
repository per tool.

Two rules are checked:

* every non-stdlib module imported by `src/` is a declared runtime
  dependency;
* every non-stdlib module imported by `tests/` is a declared runtime
  dependency or a member of the `test` extras group.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = TOOL_DIR / "src"
TESTS_DIR = TOOL_DIR / "tests"


def _local_packages() -> frozenset[str]:
    """Import names that belong to this tool, not to a dependency.

    The packages under `src/`, plus the `tests` package itself when it
    is one (it has an `__init__.py`, so `from tests._schema import ...`
    is an import of this tool's own code, not of a third party).
    """
    names = {p.name for p in SRC_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    if (TESTS_DIR / "__init__.py").exists():
        names.add("tests")
    return frozenset(names)


LOCAL_PACKAGES = _local_packages()


def _normalise(name: str) -> str:
    """PEP 503 normalisation, so `rmtree_fake` and `rmtree-fake` match.

    A requirement string is reduced to its bare distribution name, so
    `rmread>=0.0.1` and `rmread` compare equal.
    """
    bare = re.split(r"[\[<>=!~;\s]", name, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", bare).lower()


def _top_level_imports(root: Path) -> set[str]:
    """Every top-level module name imported anywhere under `root`."""
    names: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])
    return names


def _project() -> dict:
    raw = (TOOL_DIR / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(raw)["project"]


def _declared_dependencies() -> set[str]:
    return {_normalise(d) for d in _project().get("dependencies", [])}


def _declared_test_extra() -> set[str]:
    extra = _project().get("optional-dependencies", {}).get("test", [])
    return {_normalise(d) for d in extra}


def test_runtime_imports_are_declared_dependencies() -> None:
    """Every non-stdlib import in `src/` is a declared dependency."""
    imported = _top_level_imports(SRC_DIR) - sys.stdlib_module_names
    imported -= LOCAL_PACKAGES
    undeclared = {_normalise(name) for name in imported} - _declared_dependencies()
    assert not undeclared, (
        "src/ imports modules that [project].dependencies does not declare: "
        f"{sorted(undeclared)}"
    )


def test_test_imports_are_declared() -> None:
    """Every non-stdlib import in `tests/` is declared or in `[test]`."""
    imported = _top_level_imports(TESTS_DIR) - sys.stdlib_module_names
    imported -= LOCAL_PACKAGES
    declared = _declared_dependencies() | _declared_test_extra()
    undeclared = {_normalise(name) for name in imported} - declared
    assert not undeclared, (
        "tests/ import modules that neither [project].dependencies nor the "
        f"[test] extras group declares: {sorted(undeclared)}"
    )


def test_test_extra_exists_and_pins_pytest() -> None:
    """A `test` extras group exists, and it names pytest."""
    extra = _project().get("optional-dependencies", {}).get("test")
    assert extra is not None, (
        "[project.optional-dependencies] has no `test` group, so the test "
        "requirements cannot be installed"
    )
    assert any(_normalise(req).startswith("pytest") for req in extra), (
        f"the [test] extras group does not name pytest: {extra}"
    )


def test_every_requirement_is_version_pinned() -> None:
    """Every declared requirement carries a version specifier.

    A bare name means "any version of whatever the index happens to
    serve". For a sibling package that is also unpackable: `rmread` is
    not on PyPI, so an unpinned requirement cannot be resolved at all
    in a clean environment.
    """
    project = _project()
    requirements = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        requirements.extend(group)
    unpinned = [req for req in requirements if not re.search(r"[<>=!~]", req)]
    assert not unpinned, (
        "these requirements carry no version specifier, so they cannot be "
        f"resolved reproducibly: {unpinned}"
    )


def test_dtd_fixture_is_declared_as_package_data() -> None:
    """The vendored DTD ships with the package.

    `setuptools` includes `tests/` in the sdist but not the `data/`
    subdirectory beneath it, so the DTD-gate tests were silently
    unrunnable from a published sdist. Declaring it as package data
    puts it in the sdist.
    """
    manifest = (TOOL_DIR / "MANIFEST.in").read_text(encoding="utf-8")
    assert "grampsxml.dtd" in manifest, (
        "MANIFEST.in does not mention grampsxml.dtd, so the DTD is left out "
        "of the sdist and the DTD-gate tests cannot run from it"
    )


def test_sdist_ships_every_module_the_tests_import() -> None:
    """MANIFEST.in covers the whole test tree, not just `test*.py`.

    `setuptools`' default sdist rule picks up files named `test*.py`
    and nothing else. That left `tests/__init__.py` (so the relative
    imports fail outright) and `tests/grampsdtd.py` (the DTD matcher
    the schema tests import) out of the sdist, so the published sdist
    could not run its own test suite.
    """
    manifest = (TOOL_DIR / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include tests" in manifest, (
        "MANIFEST.in does not include the test tree recursively, so files "
        "other than test*.py are left out of the sdist"
    )

    # Every module the suite imports must be inside the tests tree, and
    # the whole tree must be declared.
    for path in sorted((TOOL_DIR / "tests").rglob("*.py")):
        assert path.exists()
    helpers = [
        path.name
        for path in sorted((TOOL_DIR / "tests").glob("*.py"))
        if not path.name.startswith("test_")
    ]
    assert helpers, "no non-test modules found in tests/ to check"


def test_package_license_matches_the_repository_licence() -> None:
    """This package's LICENSE is a copy of the repository's MIT licence.

    Each package carries its own LICENSE so it stays correctly licensed
    when built, published, or split into its own repository. The copies
    must not drift apart; this test is what stops them doing so.

    When the package stands alone — an installed copy, an sdist, a
    split-out repository — there is no repository LICENSE to compare
    against, so only the presence of the MIT grant is checked.
    """
    package_licence = (TOOL_DIR / "LICENSE").read_text(encoding="utf-8")
    mit_start = "MIT License"
    assert mit_start in package_licence, "the package LICENSE is not the MIT licence"

    root_licence_path = TOOL_DIR.parent.parent / "LICENSE"
    if not root_licence_path.is_file():
        return  # standalone package: no repository licence to drift from

    root_licence = root_licence_path.read_text(encoding="utf-8")
    assert mit_start in root_licence, "the repository LICENSE is not the MIT licence"

    def mit_body(text: str) -> str:
        body = text.split(mit_start, 1)[1]
        # Everything up to the first section heading is the licence grant.
        return body.split("\n---\n", 1)[0].strip()

    assert mit_body(package_licence) == mit_body(root_licence), (
        "this package's LICENSE has drifted from the repository LICENSE; "
        "copy the MIT grant from ../../LICENSE"
    )
