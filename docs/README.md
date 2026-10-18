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

## Status: v1

v1 emits the core four Gramps object types — people, events,
families, places. Citations, sources, notes, media, and repositories
are deferred to v2 (they require per-link, per-`OwnerType` walks of
RM's `*LinkTable` polymorphism — see
`tools/rmread/docs/rm11-schema.md` § "Conventions every `*LinkTable`
shares" for why they're a separate slice).

A v1 export opens in Gramps and shows a coherent tree but no source
citations or media. Researchers who need those use RM's own GEDCOM
exporter for now and the v2 tool once it lands.

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

Every export is byte-deterministic for a given `.rmtree` (the
`change` attribute uses a stable value when called programmatically,
or `datetime.now()` when called from the CLI — two CLI runs within
the same second are byte-equal).

## Identity

| Object | Handle scheme | Display id |
|---|---|---|
| Person | `_g_<rm_uuid>` (lowercased) | `I0001`, `I0002`, … |
| Event | `_g_e<EventID>` | `E0001`, `E0002`, … |
| Family | `_g_f<FamilyID>` | `F0001`, `F0002`, … |
| Place | `_g_p<PlaceID>` | `P0001`, `P0002`, … |

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