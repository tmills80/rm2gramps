# rm2gramps

Convert RootsMagic 11 `.rmtree` SQLite databases into Gramps XML
`.gramps` files. Read-only on the input.

## Why

RootsMagic exports only to GEDCOM, not to Gramps XML. The Gramps XML
`.gramps` format is a Gramps-side format. The usual round-trip path
is `rmtree → GEDCOM → Gramps import → Gramps export → .gramps`, which
loses information we already have in the SQLite DB: the precise
fact-type vocabulary, full citation detail, multimedia links, and
the full place hierarchy. This tool goes directly from `.rmtree` to
`.gramps` and preserves all of that.

## Status: v2.2

v2.2 ships all nine Gramps object types that `.gramps` supports:
people, events, families, places (v1); citations, sources (v2.1);
notes, media, repositories (v2.2).

v2.2 additions:
- **Notes:** inline `Note TEXT` columns on Person / Event /
  Family / Place become one `<note>` per unique text (sha256
  dedup). Sources and Citations use `Comments` for the same
  field. Notes are referenced via `<noteref hlink="_g_n<N>"/>` on
  every owner that carries them.
- **Media:** `<object>` elements for media referenced by
  exported Person / Source / Citation / Event via `MediaLinkTable`.
  Thumbnail BLOBs dropped (Gramps re-extracts on import from the
  source file). `<mediaref>` on the four owner types.
- **Repositories:** `<repository>` elements for AddressTable rows
  linked to exported citations via `AddressLinkTable.OwnerType=3`.
  `<reporef>` on citations only. `AddressType` ignored — every
  address linked to a citation is a repository by convention.

`--person-ids` narrows **everything** transitively: citations,
sources, media, repositories, notes, places. Each object type is
restricted to what the requested people actually reach — a place
ships only if an exported event cites it, a source only if an
exported citation parents under it. Exporting 3 of 429 people in
`SampleTree.rmtree` yields ~7 KB against ~510 KB for the full
export.

Gramps import invariants enforced by the round-trip test:
- Every `<citationref>` / `<noteref>` / `<objref>` / `<reporef>`
  resolves to a real target (0 dangling across a full SampleTree
  export).
- Every `<object>` / `<note>` has at least one referencing owner.
  **Not** true of every `<citation>` or `<source>`: RM trees contain
  citations no owner links to (11 of 434 in SampleTree) and sources
  whose only citation was dropped (10 of 204). Those ship unreferenced
  — harmless for import, but don't read the count as a bug.

Known limitations:
- Inline notes use plain `<text>` only (no styling); v3 will
  lift to `<styledtext>`.
- MediaType → MIME is hard-coded for 4 common types; others
  fall back to `application/octet-stream`.
- `<confidence>2</confidence>` is hard-coded (no direct RM
  equivalent).
- **Citation transcriptions are not exported.** `ActualText` /
  `ShortFootnote` have no legal home on `<citation>` — Gramps models
  them as a `<note>`. The export prints a count to stderr so the
  omission is never silent; surfacing them as real notes is v3 work.
- Repository `email` is dropped: the schema has no email child on
  `<repository>` (`resemail` belongs to the `<researcher>` header).
- Unknown OwnerType values in `CitationLinkTable` /
  `MediaLinkTable` are warned once and skipped.

Notes, media, and repositories from v2.2 land the rest of the
plan-locked deferred slice. Any further work is v3+ (note
styling, source templates, RM-internal OwnerType extensions,
etc.).

## Install

Standard src-layout package. The CLI entry point
`rm2gramps` is registered via `[project.scripts]` in `pyproject.toml`.

```sh
# from the repository root — resolves the rmread dependency
uv sync --all-packages --all-extras
uv pip install -e tools/rm2gramps

# or, from inside tools/rm2gramps/ (pip resolves rmread from PyPI
# once it is published there):
pip install -e .
```

`rm2gramps` depends on `rmread` for the SQLite open path, and declares
it as a runtime dependency. Both are stdlib-only Python; no third-party
packages. `rmread` is not yet on PyPI, so in a checkout the workspace
root (`pyproject.toml` at the repository root) is what makes the
dependency resolvable.

## Usage

```
rm2gramps [-h] [--no-gzip] [--person-ids IDS] [--quiet] rmtree out_gramps

positional:
  rmtree         path to input .rmtree (read-only)
  out_gramps     path to output .gramps

options:
  --no-gzip      write raw XML instead of gzipped output
  --person-ids   comma-separated PersonID subset to export
                 (default: export the entire database)
  --quiet        suppress progress output to stderr
  -h, --help     show this help
```

### Examples

```sh
# Full export, gzipped (matches RM's own convention)
rm2gramps ~/research/FamilyTree.rmtree out.gramps.gz

# Full export, raw XML (so you can grep it)
rm2gramps FamilyTree.rmtree out.gramps --no-gzip

# Subset: only persons 1, 2, 3 and their immediate relatives
rm2gramps FamilyTree.rmtree subset.gramps --person-ids 1,2,3

# Quiet (no progress on stderr; suitable for pipelines)
rm2gramps FamilyTree.rmtree out.gramps.gz --quiet
```

Exit codes:
- `0` — success
- `2` — input / IO error (file missing, schema rejection, write fail)

## Output

A Gramps XML 1.7.2 document, gzipped by default. Section order:
`<events>` → `<people>` → `<families>` → `<places>` (matches Gramps'
own export convention).

Every export is byte-deterministic for a given `.rmtree` **when
`change_ts` is fixed**. `export_database(..., change_ts=N)` embeds `N`
in every `change="…"` attribute and is reproducible across any time
interval; omit it and the value is `datetime.now()`, so two runs a
minute apart differ (matching Gramps' own behaviour). The `rm2gramps`
CLI does not pass `change_ts`, so CLI output is not byte-reproducible
unless you script the library call.

## Identity

| Object | Handle scheme | Display id |
|---|---|---|
| Person | `_g_<rm_uuid>` (lowercased) | `I0001`, `I0002`, … |
| Event | `_g_e<EventID>` | `E0001`, `E0002`, … |
| Family | `_g_f<FamilyID>` | `F0001`, `F0002`, … |
| Place | `_g_p<PlaceID>` | `P0001`, `P0002`, … |
| Source | `_g_s<SourceID>` | `S0001`, `S0002`, … | (v2.1)
| Citation | `_g_c<CitationID>` | `C0001`, `C0002`, … | (v2.1)
| Note | `_g_n<note_id>` (synthesised) | `N0001`, `N0002`, … | (v2.2)
| Media | `_g_o<MediaID>` | `O0001`, `O0002`, … | (v2.2)
| Repository | `_g_r<AddressID>` | `R0001`, `R0002`, … | (v2.2)

Mirrors the format Gramps itself emits. The display id `I0001` is
**not stable across databases** — the RM `PersonID` it derives from
is per-tree. For round-tripping back to RM, use the `_UID` attribute
on each `<person>` (carries the RM UniqueID verbatim).

## Privacy

v1 does **not** anonymise. AGENTS.md and
`references/evidence-discipline.md` § "Anonymisation for public
commits" say don't commit records of anyone born after 1906 whose
death isn't registered. That's the researcher's responsibility when
they commit the output. The `--person-ids` flag lets you subset the
export to a known-safe cohort for testing.

## Architecture

```
src/rm2gramps/
    cli/export.py        argparse entry point
    writer.py            SQL-walk glue (uses rmread)
    events.py            pure <event> renderer
    people.py            pure <person> renderer
    families.py          pure <family> renderer
    places.py            pure <placeobj> renderer
    xml.py               <database> skeleton writer
    handles.py           stable handle / display-id derivation
    xmlutil.py           XML escape (the five predefined entities)
```

Pure renderers (T4–T7) take dataclasses in, return strings out, and
never touch sqlite3 — keeps them unit-testable without a live DB.
`writer.py` (T9) is the SQL-walk layer that opens the `.rmtree`,
runs the queries, and feeds the renderers.

## Tests

167 tests, all green (1 skipped — see below). Pure renderer tests
need no fixture; writer and CLI tests use `SampleTree.rmtree` (RM
11.0, 4.6 MB) at the repo root.

```sh
python -m pytest tools/rm2gramps/tests/
```

The integration tests need the `SampleTree.rmtree` sample database. It
is gitignored, so it is absent from a fresh clone; those tests are
**skipped** rather than failed when it is missing. Point `RM_SAMPLE_TREE`
at it to run them:

```sh
RM_SAMPLE_TREE=/path/to/SampleTree.rmtree \
  python -m pytest tools/rm2gramps/tests/
```

### Schema conformance (`test_schema.py`)

The export is checked against Gramps' own DTD, vendored at
`tests/data/grampsxml.dtd` (Gramps is GPL — see the license header
in that file). `tests/grampsdtd.py` is a stdlib-only content-model
matcher; `test_schema.py` runs the full `SampleTree` export through it
and asserts:

- no element outside the DTD's declared vocabulary
- every element's children satisfy its declared ordered content model
- the renderer-level rules individually (`<objects>` not `<media>`,
  `<objref>` not `<mediaref>`, no `<sformat>`, no `<text>` on a
  citation, `<repository>` shape, `<file description>` attribute,
  `<database>` section order)

`CHILD_ORDER` in `src/rm2gramps/schema_order.py` carries the DTD's
per-element child sequence; a test pins that table against the vendored
DTD so the copy cannot drift.

The matcher's own correctness is pinned by `test_grampsdtd.py`, which
runs it over a hand-built conformant document and asserts it *rejects*
known-bad shapes. A real Gramps 6.0.8 export is used as a control when
`tests/data/example.gramps` is present; that file is real research
data and is **not committed**, so that one test skips by default.

### v2.3 — schema conformance fix

The v2.1/v2.2 output was internally consistent but **not
schema-valid**; the test suite asserted rm2gramps' own conventions
against itself, so it passed. Corrected against the DTD:

| Was (invalid) | Now | Why |
|---|---|---|
| `<media>` section | `<objects>` | the DTD's `<database>` model has no `media` |
| `<mediaref>` | `<objref>` | no `mediaref` element exists; owners declare `objref*` |
| `<sformat>` on `<source>` | *(removed)* | no such element; `format` lives in `<name-formats>` |
| `<raddr>/<rurl>/<rphone>/<email>` | `<address>` + `<url href>` + `<phone>` | none declared; `<repository>` is `(rname, type, address*, url*)` |
| `<description>` on `<object>` | `<file description="…">` | `description` is a #REQUIRED *attribute* of `<file>` |
| `<text>` on `<citation>` | *(removed)* | only legal inside `<note>` |
| sources before citations | citations first | `<database>` declares that order |

`<type>` is now required on every `<repository>` (`Library`, or `Web
site` when the address carries a URL). RM's State maps to `<state>`,
not `<county>`. Media rows with no usable file path emit no `<object>`
at all, since `<file>` is mandatory inside one.

Child order is no longer incidental: `schema_order.reorder_children`
stably sorts each element's children into the DTD's sequence, because
the order differs by element type (`<person>` wants `objref` before
`<noteref>`; `<event>` wants it after) and the cross-reference
injection pass could only ever append at the end.

## Schema reference

RM column names, FactType IDs, and link-table semantics live in
`tools/rmread/docs/rm11-schema.md`. The Gramps XML format reference
is `example.gramps` at the repo root.

## Roadmap

- v2: citations, sources, notes, media, repositories — `*LinkTable`
  polymorphism walks, per-`OwnerType`. Slice decision deferred.
- Possible: RM → Gramps export of RM's `<note>` field as Gramps
  `<note>` (currently dropped in v1).
- Possible: handle-based `<eventref role="Primary">` audit — v1
  trusts RM's `IsPrimary` flag.