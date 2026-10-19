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
- Every `<citationref>` / `<noteref>` / `<mediaref>` / `<reporef>`
  resolves to a real target.
- Every `<note>` / `<citation>` has at least one referencing
  owner (no dangling).

Known v2.2 limitations:
- Inline notes use plain `<text>` only (no styling); v3 will
  lift to `<styledtext>`.
- MediaType → MIME is hard-coded for 4 common types; others
  fall back to `application/octet-stream`.
- `<confidence>2</confidence>` and `<sformat>book</sformat>` are
  hard-coded (no direct RM equivalents).
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
# from inside tools/rm2gramps/
pip install -e .
# or just use it without installing — see Usage below.
```

`rm2gramps` depends on `rmread` for the SQLite open path. Both are
stdlib-only Python; no third-party packages.

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

51 tests, all green. Pure renderer tests need no fixture; writer
and CLI tests use `SampleTree.rmtree` (RM 11.0, 4.6 MB) at the repo
root.

```sh
python -m pytest tools/rm2gramps/tests/
```

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