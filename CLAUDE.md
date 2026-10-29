# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## What this is

`rm2gramps` converts RootsMagic 11 `.rmtree` SQLite databases into
Gramps XML `.gramps` files. Read-only on the input.

`AGENTS.md` is the authority on house style; this file records the
architecture and the commands. Read `AGENTS.md` before changing
anything — it is short and it binds.

## Commands

`uv` drives everything.

```sh
uv sync --all-extras      # setup
uv run pytest tests/ -q   # run (199 tests)
```

`SampleTree.rmtree` (RM 11, 4.6 MB) sits at the repository root and is
gitignored. Tests needing it **skip** rather than fail when it is
absent; point `RM_SAMPLE_TREE` at another file to override the
auto-detection.

CLI: `uv run rm2gramps --help`.

## Dependency

`rmread` is a **separate repository** and a hard runtime dependency. It
is not on PyPI; `[tool.uv.sources]` resolves it from `../rmread`. The
two repositories are expected to sit side by side under `~/projects/`.

RM column names, FactType IDs, and link-table semantics live in the
sibling repository's `docs/rm11-schema.md` — one source of truth, not a
copy.

## Architecture

A strict **renderer / writer split**:

- *Pure renderers* (`events.py`, `people.py`, `families.py`, `places.py`,
  `citations.py`, `sources.py`, `notes.py`, `media.py`,
  `repositories.py`, `citationrefs.py`, `schema_order.py`): dataclass in
  → string out, never touch `sqlite3`. The `change` timestamp is always
  a parameter, never read from the clock — that is what makes them
  testable without a live DB.
- `writer.py` — the only module that queries the database.
  `export_database()` is one ordered pipeline: events → places → people
  → families, then citations → sources, then a chain of *injection*
  passes (`citationref`, `noteref`, `objref`, `reporef`) that rewrite the
  rendered strings.
- `xml.py` — pre-rendered strings → document bytes; owns the
  `<database>` skeleton and section order.
- `cli/export.py` — argparse shim; owns exit codes (`0` ok, `2`
  IO/schema).

Rules that the code enforces and the tests pin:

- **Injection order matters.** Each pass seeds from the *already-injected*
  lists, not the `*_pre` originals — seeding from `_pre` silently
  discards every `<citationref>`.
- **`reorder_children()` runs last**, on every element.
  `schema_order.CHILD_ORDER` carries the DTD's per-element child
  sequence; `tests/test_schema.py` pins that table against the vendored
  `tests/data/grampsxml.dtd` so it cannot drift. The DTD order genuinely
  differs per element (`<person>` wants `objref` before `noteref`;
  `<event>` wants it after), and injection can only append.
- **Note dedup key is `(type, text)`**, not text alone — sha256 of
  `f"{note_type}\0{text}"`. The same string under two Gramps note types
  is two notes. Gramps' `type` attribute is matched case-sensitively, so
  the types must be Gramps' exact English names ("Person Note", "Source
  text"), not "general".
- **Note handles are content-derived**: `_g_n` + the first 12 hex of
  that same key. A note keeps its handle across a subset export and
  across a change in note kind; the *display id* (`N0001`) is
  sequential, per-export, and must not be used to identify a note
  between two files. The key and the handle are derived in one place
  (`notes.note_key`) so they cannot drift apart.
- **RM's citation owner types 7 and 19 are person-level citations**,
  not unknown types. `rmread.linktables.CITATION_PERSON_OWNER_TYPES`
  folds them into the `Person` bucket; dropping them cost 33 links
  and left 4 citations with no owner at all. Any other owner type
  outside 0–4 is warned and skipped.
- `--person-ids` narrows everything transitively — citations, sources,
  media, repositories, notes, places. `--person-ids 999999` must emit
  zero people *and* zero families.
- Unreferenced `<citation>` / `<source>` are **expected**, not a bug:
  some RM trees contain citations no owner links to. Every `<object>` /
  `<note>`, by contrast, must have at least one referencing owner.
- `export_database(..., change_ts=N)` pins every `change=` attribute, but
  `header_date` is `date.today()` and the CLI never passes `change_ts`,
  so **CLI output is not byte-reproducible**.
- Gramps XML is validated against a **DTD**, not an XSD.
  `tests/grampsdtd.py` is a stdlib content-model matcher;
  `tests/test_grampsdtd.py` asserts it *rejects* known-bad shapes so the
  checker itself is trustworthy.

## Evidence and privacy rules

These are not stylistic; the repo's outputs are meant to be cited.

- **Name the copy.** Before analysing an England & Wales vital record
  (registered after 1 July 1837) you must know whether you hold the
  local register copy, the GRO register copy, or a certified copy
  certificate. Handwriting and informant-signature analysis is only
  meaningful on the local register copy. Scripts touching vital records
  take a `--copy-type` flag; the default is *unknown* and must **refuse**
  to run record-graphy tests rather than silently pass. The output header
  states the copy type it ran against.
- **Cite inline, never as a trailing footnote.** Minimum shape:
  `Staines, Thomas, b. 1840 Q4, Aston. [GRO index, vol. XVI, p. 211]`. A
  claim with no citation is a draft, not a finding.
- **GEDCOM is a hypothesis, not kinship.** Authoritative on what it
  claims to exist; suspect on what it implies. Never infer kinship from
  a shared surname or shared parish.
- **Provenance over polish.** The source line goes next to the claim so
  another researcher can check it without going through you.
- **Never commit** records of anyone born after 1906 whose death is not
  registered, full dates for living people, or anything under a
  `RESEARCHER_PRIVATE.md` flag. Hash identifiers before writing; never
  log raw names.

Full rules: `references/evidence-discipline.md`.

## Synthetic-data conventions

Genealogy fixtures leak real names by accident. A plausible-looking
placeholder (`Zoe PlaceholderSurnameThree`) is mistakable in a research
note at 1am. The convention:

| Field | Convention | Example |
|---|---|---|
| Surname | six-or-more identical letters | `AAAAAA`, `O'CCCC` |
| Given name | recognisable placeholder | `Zoe`, `Wren`, `Xerxes` |
| Place | tagged fake | `FFakePlace-1`, `Fakeland` |
| Unique ID | `fp-` / `FAKE-UUID-` prefix | `fp-1` |
| Email | `.invalid` TLD | `test@example.invalid` |
| Phone | ITU reserved range | `+1 555-0100` |

If a test only needs a name, use the placeholder surname alone — skip
the plausible given name.

## Where the facts live

- `README.md` — current CLI docs (v3).
- `docs/rm11-schema.md` — *in the sibling `rmread` repository*. RM
  column names, fact-type IDs, link-table semantics. The single source
  for the schema.
- `docs/scaffolding-context.md` — per-tool house conventions
  (read-only belt-and-braces, fake-data naming, the fake-data
  override).
- `plans/` — the design record: what was decided, what was verified,
  what was deliberately deferred. A plan's "Status" line says what
  shipped; a plan's *body* may describe the state before a later slice,
  so read the dated "Changed" notes at the top.
- `references/evidence-discipline.md` — the sourcing rules.
