"""Minimal DTD content-model matcher for the Gramps XML vocabulary.

Stdlib only. Parses the element declarations out of the vendored
``grampsxml.dtd`` (Gramps' own schema, GPL — see ``data/README.md``)
and checks that an ElementTree document only uses declared elements
in an order each declaration permits.

Why not lxml: rm2gramps is stdlib-only by design (see the tool
README), and a test that needs a third-party wheel installed is a
test that silently stops running. This module keeps the schema gate
dependency-free. ``test_grampsdtd.py`` *also* runs a real lxml
DTD validation when lxml happens to be importable, as a second,
independent opinion.

The Gramps DTD marks most declarations as open with a trailing
``...`` (``<!ELEMENT person (gender, name*, ... tagref*...)>``): the
listed particles are ordered but not exhaustive. This matcher honours
that — once the declared prefix is consumed, extra children pass.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

DTD_PATH = Path(__file__).parent / "data" / "grampsxml.dtd"

# <!ELEMENT name (content model)>
#
# Two shapes trip a naive pattern:
#  - content models wrap across newlines and may nest parentheses,
#    e.g. `(daterange|datespan|dateval|datestr)?`;
#  - an occurrence marker may follow the closing paren, e.g.
#    `<!ELEMENT sources (source)*>`.
# Both are accepted; `_content_model_ok` strips the marker.
_ELEMENT_DECL = re.compile(
    r"<!ELEMENT\s+(?P<name>\w+)\s+"
    r"(?P<model>\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*?\)\s*[*+?]?|EMPTY|ANY)\s*>",
    re.S,
)

# A declaration whose body is exactly `(#PCDATA)` means "text content,
# no child elements" — the Gramps DTD's stand-in for mixed content.
# Such a declaration is satisfied by any childless element and must
# not be run through the particle matcher.
_PCDATA_ONLY = re.compile(r"\(\s*#PCDATA\s*\)")


def _split_top(text: str, separators: str = ",|") -> list[str]:
    """Split on top-level separators, ignoring those inside parens."""
    parts: list[str] = []
    depth = 0
    current = ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and ch in separators:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _particle(text: str) -> tuple[str, str]:
    """Split a particle into ``(name, occurrence)``.

    The occurrence marker may sit inside the group (``(event)*``,
    ``(a|b)+``) or after it (``(source)*``), so peel it off first
    and then unwrap whatever group remains.
    """
    text = text.strip()
    marker = ""
    for candidate in ("?", "*", "+"):
        if text.endswith(candidate):
            marker = candidate
            text = text[:-1].strip()
            break
    return _unwrap(text), marker


def _unwrap(text: str) -> str:
    """Strip redundant outer parentheses, however deeply nested."""
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        # Only unwrap when the outer parens wrap the whole particle —
        # a partial wrap like `(a|b` is not a group.
        if inner.count("(") != inner.count(")"):
            break
        text = inner
    return text


def _matches(particle: str, tag: str) -> bool:
    """Does this particle accept ``tag``?

    ``particle`` has already been unwrapped by :func:`_particle`, so a
    choice group arrives here as a bare ``a|b`` string; any further
    nesting is handled by recursing on each alternative.
    """
    particle = particle.strip()
    if particle == "#PCDATA":
        return False
    if "|" in particle:
        return any(_matches(alt, tag) for alt in _split_top(particle, "|"))
    if particle.startswith("(") and particle.endswith(")"):
        return _matches(particle[1:-1].strip(), tag)
    return particle == tag


def _match_seq(
    seq: list[tuple[str, str]],
    children: list[str],
    open_ellipsis: bool,
) -> bool:
    """Match ``children`` against an ordered particle list."""
    index = 0
    for name, occ in seq:
        if occ == "?":
            if index < len(children) and _matches(name, children[index]):
                index += 1
        elif occ == "*":
            while index < len(children) and _matches(name, children[index]):
                index += 1
        elif occ == "+":
            if index >= len(children) or not _matches(name, children[index]):
                return False
            while index < len(children) and _matches(name, children[index]):
                index += 1
        else:  # exactly one
            if index >= len(children) or not _matches(name, children[index]):
                return False
            index += 1
    return open_ellipsis or index == len(children)


class GrampsDtd:
    """Parsed element declarations from the Gramps XML DTD."""

    def __init__(self, path: Path = DTD_PATH) -> None:
        self._decls: dict[str, tuple[str, bool]] = {}
        text = path.read_text(encoding="utf-8")
        for match in _ELEMENT_DECL.finditer(text):
            name = match.group("name")
            model = match.group("model").strip()
            self._decls[name] = model, model in ("EMPTY", "ANY")

    @property
    def elements(self) -> set[str]:
        """Every element name declared in the DTD."""
        return set(self._decls)

    def content_model(self, name: str) -> str:
        """The raw declared content model for ``name``.

        Returns ``""`` when the element is not declared, so callers
        that are checking an existing element can fail on the empty
        model rather than on a KeyError.
        """
        return self._decls.get(name, ("", False))[0]

    def undeclared(self, root: ET.Element) -> dict[str, int]:
        """Element name -> occurrence count, for names the DTD never declares."""
        counts: dict[str, int] = {}
        for element in root.iter():
            tag = element.tag.split("}")[-1]
            if tag not in self._decls:
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    def content_model_errors(self, root: ET.Element) -> list[str]:
        """Report every element whose children violate its declared model."""
        errors: list[str] = []
        for element in root.iter():
            tag = element.tag.split("}")[-1]
            if tag not in self._decls:
                continue
            model, permissive = self._decls[tag]
            if permissive or _PCDATA_ONLY.fullmatch(model):
                continue
            children = [c.tag.split("}")[-1] for c in element]
            if not _content_model_ok(model, children):
                errors.append(
                    f"<{tag} {element.get('id') or ''}> children {children} "
                    f"violate DTD model: {' '.join(model.split())}"
                )
        return errors


def _content_model_ok(model: str, children: list[str]) -> bool:
    body = model.strip()
    # Drop an occurrence marker that trails the closing paren
    # (`<!ELEMENT sources (source)*>`), then unwrap.
    occ = ""
    for marker in ("?", "*", "+"):
        if body.endswith(marker) and body.endswith(f"){marker}"):
            occ = marker
            body = body[:-1]
            break
    body = body.strip()[1:-1].strip()
    open_ellipsis = body.endswith("...")
    body = body.removesuffix("...").strip()

    # Split the content model into top-level particles on commas only.
    # A `|` at the top level means the whole model is a choice group
    # (`(a|b)?` inside a sequence is already parenthesised, so it is
    # not seen here); commas separate particles within a sequence.
    seq = [_particle(a) for a in _split_top(body, ",")]
    if not seq:
        return not children
    if len(seq) == 1 and "|" in seq[0][0] and not seq[0][1]:
        # A bare choice group with no occurrence marker (e.g. the
        # `#PCDATA`-adjacent `(a|b)` form) accepts any run of the
        # alternatives, not exactly one.
        return all(_matches(seq[0][0], tag) for tag in children)
    # A trailing marker outside the group (`((a|b))*`) means the same
    # thing as repeating the particle, which _match_seq already models
    # once the marker is folded back onto the particle.
    if occ:
        seq = [(seq[0][0], occ if not seq[0][1] else seq[0][1])]
    return _match_seq(seq, children, open_ellipsis)
