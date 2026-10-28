# `rm2gramps` — scaffolding context

Project-specific refinements of the general `scaffolding-codebases`
skill for this tool. Read the general skill for layout / naming /
gate rules; read this doc for the *how on this codebase*.

## Domain: genealogy tools

This repo is genealogy-only. The general fake-data convention
(six-of-a-letter surname, RFC `.invalid`, fake-marked UUIDs) is
strictly enforced; see the `scaffolding-codebases` skill's
`synthetic-data-naming.md` reference for the cross-project rules.

Repo-specific tightening: surname placeholders are **six or more
identical letters** (`AAAAAA`, `BBBBBB`). Given names use the rare /
cross-cultural ZoaUlrichWrenXerxes-style set. UUIDs are `FAKE-UUID-…`
prefixed. Living-people records, anything under UK GDPR / PIPL
constraints, or anything that names a real researcher / vault never
appears in a commit, ever — anonymise or hash before write.

`SampleTree.rmtree` is the canonical integration fixture for tools
that touch `.rmtree`. It is anonymised, gitignored, and kept outside
version control so tests have a real file to query. Each repository
that needs it keeps its own copy — this one at the repository root.
Do not commit any `.rmtree` file.

## Verified facts about the upstream tools

The plan for this tool initially claimed "RM can export to Gramps
XML via its GUI but the route isn't scriptable." That is wrong.
RM's own export menu is **GEDCOM only**. Verified against RM 11's
File → Export menu; cross-checked against the Gramps project
documentation. The correct premise is:

- RM exports only GEDCOM (via GUI; not scriptable).
- Gramps imports GEDCOM and exports Gramps XML (`.gramps`).
- A direct `.rmtree → .gramps` path fills the gap of skipping the
  lossy GEDCOM round-trip — RM retains precision that GEDCOM drops
  (full place hierarchy, citation detail, fact-type vocabulary
  beyond the GEDCOM set, primary/non-primary event flag).

Any future plan that frames this tool against "what RM can/can't
do" must verify the RM-side statement against RM's own UI or docs,
not from memory. The wrong premise wastes a "Why this exists"
rewrite once the user catches it.

## Sibling-tool reuse: `rmread`

`rmread` is the read-side companion, in a **separate repository** at
`../rmread`. It owns the SQLite adapter for `.rmtree` and registers
the `RMNOCASE` collation. This tool depends on `rmread`; the dep was
confirmed in plan mode by checking `rmread`'s public surface
(`rmread/__init__.py` exposes `open_database`, `RMDatabase`,
`SchemaError`, plus the row loaders in `person` / `family` / `event`
modules). It also imports `rmread.linktables` and `rmread.rmtext`
directly — treat those as public API.

When this tool needs an SQLite adapter, it imports from `rmread`,
not from its own copy. The first commit of this tool shipped a
duplicated `db.py` that was deleted after the plan-mode
discussion; the resulting dependency on `rmread` is the right
shape.

## Architecture: pure renderers + writer that drives them

Each Gramps object type has its own `src/rm2gramps/<type>.py`
module with a `render_<type>_xml(rec, *, change) -> str` function
and a corresponding `<Type>Record` dataclass. The renderers are
pure (no sqlite3, no ElementTree); the writer (TBD in T9) opens
the DB, walks SQL into the dataclasses, calls the renderers,
stitches the strings into the `<database>` skeleton via `xml.py`.

This shape makes each renderer independently testable with
synthetic `Record` values — no live DB needed for unit tests.
Integration tests in T10 open the real `SampleTree.rmtree`.

## Slice discipline

The plan (`plans/rm2gramps.md`) is the source of truth for what v1
ships and what v1 defers. **Re-read the plan's "Slice decision"
section before adding scope.** Common drift: adding citations /
sources / notes / media "while we're here" — these all require
per-link, per-`OwnerType` walks of RM's `*LinkTable` polymorphism
and are deferred to v2 by name. If a new requirement in that set
shows up, write a new plan section before coding.