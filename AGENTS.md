# AGENTS.md — rm2gramps

## What this is

**rm2gramps** converts RootsMagic 11 `.rmtree` SQLite databases into
Gramps XML `.gramps` files. Read-only on the input.

This repository used to live inside the `genealogy_tools` workspace, at
`tools/rm2gramps/`. It now stands alone. The house style below is
inherited from that workspace and is unchanged; only the *Layout* and
the *Sibling repository* sections are specific to this project.

Everything here should be **evidence-grade** — the kind of code that
gets cited in a research note, run against real records, and audited
later when a conclusion is challenged.

Optimise for: **correctness, traceability, reproducibility of evidence,
and clean hand-off to other researchers**. Optimise against: clever
abstractions, clever frameworks, "scale," premature packaging.

## Sibling repository

`rmread` is a **separate repository** and a hard runtime dependency. It
owns the read-only RootsMagic SQLite reader, the RootsMagic markup
dialect (`rmread.rmtext`), and the RM 11 schema reference
(`docs/rm11-schema.md` in *that* repository — the single source of
truth for column names, FactType IDs, and link-table semantics).

Neither repository copies the other's schema knowledge. When you change
something that the schema doc records, change it there too.

The two are expected to sit side by side:

```
~/projects/
├── rmread/
└── rm2gramps/
```

`rmread` is not on PyPI, so `[tool.uv.sources]` in `pyproject.toml`
resolves it from `../rmread`. Delete that block once `rmread` is
published.

## House style

- **Plain Python 3.12+**, standard library first. Reach for a
  third-party package only when the standard library genuinely cannot do
  the job.
- **One script per concern.** Don't build a framework until four scripts
  need the same code — then factor it, not before.
- **Files are evidence.** Every output that names a person, date, or
  place must carry a source citation (archive, series, volume,
  folio/image, reference) next to the claim, not as a footnote. See
  [`references/evidence-discipline.md`](references/evidence-discipline.md)
  for what that means in practice.
- **No silent failure.** If a script produces no result, say so. If it
  picks between multiple plausible interpretations, surface them —
  never paper over.

## Conventions for code

- Type hints on public function signatures. Narrow types beat broad
  ones.
- Functions take **paths and parameters explicitly**; no implicit
  globals, no hidden state.
- CLI entry points use `argparse` with `--help` that documents every
  flag.
- Errors raise with context. `raise ValueError(f"line {lineno}: …")`,
  not bare `raise ValueError`.
- Tests live next to the code they test, named `test_*.py`.

## Conventions for evidence handling

For anything that touches a record, read the evidence-discipline
reference and follow it. The short version:

1. **Name the copy** (local register / GRO register / certified
   certificate).
2. **Cite inline**, not at the end.
3. **Treat GEDCOM as hypothesis**, not kinship.
4. **Provenance over polish** — the source line goes next to the claim.

Full rules: [`references/evidence-discipline.md`](references/evidence-discipline.md).

## Don't

- Don't add a `requirements.txt` for a one-file script.
- Don't reach for pandas / numpy / a database to join two CSV-shaped
  lists.
- Don't write a class when a function with module-level constants will
  do.
- Don't commit raw personal data, living-people records, or anything
  under UK GDPR / PIPL constraints. Anonymise or hash before committing.
- Don't rewrite history — `git rebase` is fine locally, but the public
  branch is append-only.

## Architecture rules

The architecture is a strict **renderer / writer split**:

- *Pure renderers* (`events.py`, `people.py`, `families.py`, `places.py`,
  `citations.py`, `sources.py`, `notes.py`, `media.py`,
  `repositories.py`, `citationrefs.py`, `schema_order.py`): dataclass in
  → string out, never touch `sqlite3`. The `change` timestamp is always
  a parameter, never read from the clock.
- `writer.py` — the only module that queries the database.
  `export_database()` is one ordered pipeline: events → places → people
  → families, then citations → sources, then a chain of *injection*
  passes (`citationref`, `noteref`, `objref`, `reporef`) that rewrite the
  rendered strings.
- `xml.py` — pre-rendered strings → document bytes.

Three rules the code enforces and the tests pin:

- **Injection order matters.** Each pass seeds from the *already-injected*
  lists, not the `*_pre` originals — seeding from `_pre` silently
  discards every `<citationref>`.
- **`reorder_children()` runs last**, on every element.
  `schema_order.CHILD_ORDER` carries the DTD's per-element child
  sequence; `tests/test_schema.py` pins that table against the vendored
  `tests/data/grampsxml.dtd` so it cannot drift.
- **Note dedup key is `(type, text)`**, not text alone — sha256 of
  `f"{note_type}\0{text}"`. The same string under two Gramps note types
  is two notes.
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

## Layout

```
AGENTS.md                                  ← you are here
CLAUDE.md                                  ← Claude Code entry point
LICENSE                                    ← MIT
MANIFEST.in                                ← sdist contents (tests + DTD)
README.md                                  ← the tool's documentation
pyproject.toml                             ← package metadata
uv.lock                                    ← pinned resolution
references/evidence-discipline.md           ← sourcing rules
docs/                                      ← project-specific guides
plans/                                     ← the design record
src/rm2gramps/                             ← library code on src-layout
src/rm2gramps/cli/                         ← CLI entry points
tests/                                     ← tests next to the code
```

`plans/` is the design record: what was decided, what was verified, what
was deliberately deferred. A plan's "Status" line says what shipped; a
plan's *body* may describe the state before a later slice, so read the
dated "Changed" notes at the top.

Per-tool `docs/` may hold things like `scaffolding-context.md` —
domain-specific refinements of the general scaffolding conventions,
written when a project has its own (fake-data rules, schema-name
quirks, read-only belt-and-braces).

Real research data (RootsMagic `.rmtree`, Gramps XML) lives outside the
repository and is gitignored.

## When you are unsure

Ask. One short question beats guessing and rewriting.
