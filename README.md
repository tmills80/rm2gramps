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

## Status: v3.3

v3.3 ships all nine Gramps object types that `.gramps` supports, with
notes that mean what Gramps means by a note — right type, real
transcriptions, and RootsMagic's markup carried across as style ranges
— with note handles that survive a change in the export, with every
citation RootsMagic links to a person actually reaching that person in
the output, and with a **byte-reproducible** command-line export.

| Version | Adds |
|---|---|
| v1 | people, events, families, places |
| v2.1 | citations, sources |
| v2.2 | notes, media, repositories |
| v2.3 | schema conformance fix against the Gramps DTD |
| v3 | typed notes, transcriptions, styling |
| v3.1 | content-derived note handles |
| v3.2 | person-level citations recovered (RM owner types 7 and 19) |
| v3.3 | byte-reproducible CLI output (`--change-ts`, `SOURCE_DATE_EPOCH`) |

### v3.3 — byte-reproducible exports

An export is evidence. "Here is the file this claim came from" has to
mean the same file tomorrow, or a researcher has to trust that nobody
edited it.

The document had two moving parts: every `change="…"` attribute, and
the `<created date="…">` header. The header was `date.today()` — read
from the clock — so even a perfectly pinned export differed from the
previous day's.

Both now come from one number. The header date is derived from the
change timestamp (its UTC date), and the CLI passes that timestamp
through `--change-ts` or `SOURCE_DATE_EPOCH`:

```sh
rm2gramps Tree.rmtree out.gramps --change-ts 1700000000
```

The gzip header was the last moving part: it stored the current time
and the output file's name. It now stores neither, so the **file on
disk** is byte-identical between runs — not just the XML inside it.
Two runs writing to differently-named files produce the same bytes.

### v3.2 — person-level citations

RootsMagic records a citation against a person twice over: once on
the *fact* (the birth, the census) and once on the *person*. The
fact-level citation goes through `EventTable`; the person-level one
goes through `CitationLinkTable` with owner type `0`.

RM also uses two owner types outside the global enum — `7` and `19` —
for the same thing. rm2gramps treated them as unknown and dropped
them: **33 citation links** went missing, and 4 citations in
SampleTree were reachable *only* through them, so they reached Gramps
with no owner at all.

They are folded into the person bucket now (`rmread.linktables.
CITATION_PERSON_OWNER_TYPES`). Verified against SampleTree: all 33
owner ids resolve to people, and in 20 of the 24 type-7 rows the
citation's source is also cited by that same person's own facts —
the signature of a citation copied up from a fact to the person.

| | before | after |
|---|---|---|
| `<citationref>` on people | 17 | 50 |
| citations emitted | 434 | 435 |
| citations with no owner | 11 | 8 |

RM's precise label for the difference between 7 and 19 is not
recoverable from the file alone; both are attached to the person,
which is where they live in RootsMagic.

### v3.1 — content-derived note handles

A note's handle used to be `_g_n<note_id>`, with the id assigned in
first-seen order. That made the handle a property of the *export*,
not of the note: adding a note kind renumbered every note after it,
and a `--person-ids` subset renumbered its notes differently from the
full tree. Two exports of the same tree could not be diffed against
each other — a changed note and a moved note looked identical.

The handle is now derived from the note's content, using the same
key the dedup already used:

```
handle = "_g_n" + sha256(f"{note_type}\0{text}").hexdigest()[:12]
```

The type is in the key because it is part of the note's identity — the
same words as a "Citation" and as a "Source text" are two different
notes in Gramps, and get two different handles.

The display id (`N0001`) is still sequential and still per-export: it
is a label, nothing references it, and Gramps renumbers on import.
The handle is the identity.

### v3 — note types, transcriptions, styling

v2.2 shipped notes as an afterthought: every note came out
`type="general"` with the text flattened. Three defects followed, and
v3 fixes all three.

**1. Wrong type.** `type="general"` is not a Gramps type name.
Gramps' `GrampsType.set_from_xml_str` looks the string up in
`_E2IMAP`, keyed on the exact English type name and matched
**case-sensitively**. `"general"` is not a key, so Gramps imported
every rm2gramps note as a *custom* type literally named "general"
instead of the built-in "General". Every note now carries Gramps' own
English type name, one per RM column:

| RM column | Gramps type | SampleTree non-empty |
|---|---|---|
| `PersonTable.Note` | `Person Note` | 5 |
| `EventTable.Note` | `Event Note` | 33 |
| `FamilyTable.Note` | `Family Note` | 11 |
| `PlaceTable.Note` | `Place Note` | 0 |
| `SourceTable.Comments` | `Source Note` | 6 |
| `SourceTable.ActualText` | `Source text` | 47 |
| `CitationTable.Comments` | `Citation` | 2 |
| `CitationTable.ActualText` | `Source text` | 31 |

**2. Lost transcriptions.** `SourceTable.ActualText` (47 non-empty rows
in SampleTree) and `CitationTable.ActualText` (31 rows) are the
researcher's verbatim transcription — of the source, and of the
specific citation. v2.2 exported none of it. Both now become `Source
text` notes, referenced from their `<source>` / `<citation>` owner.

**3. Lost styling.** RM note text carries `<b>` and `<i>`; v2.2 escaped
them into the note text as literal markup. They now survive as
Gramps `<style>` / `<range>` children.

Two consequences of the v3 work worth knowing:

- **The dedup key is `(type, text)`, not text.** The same words as a
  `Citation` and as a `Source text` are two different notes in
  Gramps, so the type is part of the key
  (sha256 of `f"{type}\0{text}"`). Collapsing them would give one of
  the two the wrong type.
- **The RootsMagic markup dialect lives in `rmread`**, not here.
  `rmread.rmtext` provides `tokenize()`, `plain_text()` and
  `normalize_newlines()`. It is a fact about the RootsMagic file
  format, so it belongs to the package that reads that format — and
  `rmcite` consumes the same tokenizer.

### v2.2 — media and repositories

- **Media:** `<object>` elements for media referenced by exported
  Person / Source / Citation / Event via `MediaLinkTable`. Thumbnail
  BLOBs dropped (Gramps re-extracts on import from the source file).
  `<objref>` on the four owner types.
- **Repositories:** `<repository>` elements for `AddressTable` rows
  linked to an exported source via `AddressLinkTable.OwnerType=3` —
  OwnerType 3 is **Source** in the global enum, not Citation. The
  `<reporef>` therefore lands on the `<source>`, which is also where
  the DTD allows it (`<source>` declares `reporef*`; `<citation>`
  does not). `AddressType` ignored — every address linked to a
  source is a repository by convention.

### `--person-ids` narrowing

`--person-ids` narrows **everything** transitively: citations,
sources, media, repositories, notes, places. Each object type is
restricted to what the requested people actually reach — a place
ships only if an exported event cites it, a source only if an
exported citation parents under it. Exporting 3 of 429 people in
`SampleTree.rmtree` yields ~7 KB against ~510 KB for the full
export.

### Gramps import invariants

Enforced by the round-trip test:
- Every `<citationref>` / `<noteref>` / `<objref>` / `<reporef>`
  resolves to a real target (0 dangling across a full SampleTree
  export).
- Every `<object>` / `<note>` has at least one referencing owner.
  **Not** true of every `<citation>` or `<source>`: RM trees contain
  citations no owner links to (8 of 435 in SampleTree) and sources
  whose only citation was dropped (10 of 204). Those ship unreferenced
  — harmless for import, but don't read the count as a bug.

### One deliberate divergence: shared notes

rm2gramps emits **one `<note>` per unique `(type, text)`**, shared by
every owner that carries it. Gramps does neither sharing nor
deduplication: in a real Gramps export of the same tree, no note is
referenced by more than one owner, and 20 groups of byte-identical
notes exist with distinct handles.

The collapse stays — v2.2 locked it, and it keeps the export small.
But it is now a stated choice rather than an accident, with the limit
spelled out: because the type is part of the key, a collapse can never
merge two notes of different types. A researcher who wants Gramps'
one-note-per-owner shape splits them on import.

### v3 verification record

Full `SampleTree.rmtree` export, checked against the vendored DTD:

| Check | Result |
|---|---|
| notes emitted | 128 |
| style elements | 28 (25 bold, 3 italic) |
| undeclared elements vs DTD | 0 |
| content-model errors vs DTD | 0 |
| source transcriptions exported | 47 of 47 non-empty |
| citation transcriptions exported | 31 of 31 non-empty |
| notes with literal `<b>` / `<i>` left in the text | 0 |
| notes carrying a non-Gramps type name | 0 |
| dangling `<noteref>` | 0 |
| notes referenced by nothing | 0 |

### Known limitations

- **RM's `ShortFootnote` / `Footnote` / `Bibliography` are not
  exported** (31 rows each). They are RootsMagic's *rendered* citation
  strings, not source text — Gramps renders its own footnotes from the
  citation's own fields. The export prints a count to stderr so the
  omission is never silent. A researcher who wants RM's exact footnote
  wording must re-render it from RM.
- **Note display ids are assigned in first-seen order** (`N0001`,
  `N0002`, …) and are therefore per-export: a subset export numbers
  its notes differently from a full one, and adding a note kind
  renumbers every note after it. The *handle* is content-derived and
  stable across exports — use it, not the display id, to identify a
  note between two files.
- `AddressTable.Note` and `MultimediaTable.Description` do **not**
  become notes. Gramps has `Repository Note` and `Media Note` types for
  them, but the v2.2 decision keeps `MultimediaTable.Description` in
  `<file description>` (a #REQUIRED attribute of `<file>`), and
  `AddressTable.Note` is empty in SampleTree, so the path is exercised
  only by synthetic tests.
- MediaType → MIME is hard-coded for 4 common types; others
  fall back to `application/octet-stream`.
- `<confidence>2</confidence>` is hard-coded (no direct RM
  equivalent).
- Repository `email` is dropped: the schema has no email child on
  `<repository>` (`resemail` belongs to the `<researcher>` header).
- Unknown OwnerType values in `CitationLinkTable` /
  `MediaLinkTable` are warned once and skipped. Owner types 7 and 19
  are **not** unknown — they are person-level citations and are
  exported (see v3.2).
- `SourceTemplateTable` → Gramps name-formats is deferred; so are
  `CitationLinkTable.Quality` →
  `<confidence>` (RM's quality is a per-link scale, Gramps'
  confidence is per-citation — they do not map).

## Install

Standard src-layout package. The CLI entry point
`rm2gramps` is registered via `[project.scripts]` in `pyproject.toml`.

```sh
# from the repository root — resolves the rmread dependency
uv sync --all-extras
uv run rm2gramps --help
```

`rm2gramps` depends on `rmread` for the SQLite open path and the
shared markup dialect, and declares it as a runtime dependency. Both
are stdlib-only Python; no third-party packages.

`rmread` is not yet on PyPI. Until it is, this repository resolves it
from a **sibling checkout** via `[tool.uv.sources]`:

```toml
[tool.uv.sources]
rmread = { path = "../rmread", editable = true }
```

So the two repositories are expected to sit side by side:

```
~/projects/
├── rmread/       ← the read-only RootsMagic reader
└── rm2gramps/    ← this repository
```

Both are on GitHub — `tmills80/rmread` and `tmills80/rm2gramps`:

```sh
git clone https://github.com/tmills80/rmread.git
git clone https://github.com/tmills80/rm2gramps.git
```

Delete that `[tool.uv.sources]` block once `rmread` is published and
`dependencies = ["rmread>=0.0.1"]` can be resolved from an index.

## Usage

```
rm2gramps [-h] [--no-gzip] [--person-ids IDS] [--change-ts TS]
           [--quiet] rmtree out_gramps

positional:
  rmtree         path to input .rmtree (read-only)
  out_gramps     path to output .gramps

options:
  --no-gzip      write raw XML instead of gzipped output
  --person-ids   comma-separated PersonID subset to export
                 (default: export the entire database)
  --change-ts    pin every change="…" attribute to this Unix-seconds
                 value and derive the <created date=…> header from it;
                 makes the export byte-reproducible
                 (overrides SOURCE_DATE_EPOCH)
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

# Byte-reproducible: the same tree and the same timestamp always
# produce the same file, byte for byte
rm2gramps FamilyTree.rmtree out.gramps --change-ts 1700000000

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
minute apart differ (matching Gramps' own behaviour).

The `<created date="…">` header is derived from that same timestamp,
so pinning it pins the whole document. On the command line:

```sh
rm2gramps Tree.rmtree out.gramps --change-ts 1700000000
```

`SOURCE_DATE_EPOCH` does the same job when the environment sets it
(the reproducible-builds convention); `--change-ts` wins if both are
given. The gzip header carries neither the clock nor the output path,
so the **file on disk** is byte-identical between runs too — not just
the XML inside it.

## Identity

| Object | Handle scheme | Display id |
|---|---|---|
| Person | `_g_<rm_uuid>` (lowercased) | `I0001`, `I0002`, … |
| Event | `_g_e<EventID>` | `E0001`, `E0002`, … |
| Family | `_g_f<FamilyID>` | `F0001`, `F0002`, … |
| Place | `_g_p<PlaceID>` | `P0001`, `P0002`, … |
| Source | `_g_s<SourceID>` | `S0001`, `S0002`, … | (v2.1)
| Citation | `_g_c<CitationID>` | `C0001`, `C0002`, … | (v2.1)
| Note | `_g_n<12 hex of the note's content key>` | `N0001`, `N0002`, … | (v3.1)
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
    citations.py         pure <citation> renderer
    sources.py           pure <source> renderer
    notes.py             pure <note> renderer (type + <style>/<range>)
    notes_dedup.py       note collection and (type, text) dedup
    media.py             pure <object> renderer
    repositories.py      pure <repository> renderer
    citationrefs.py      pure <citationref> / <sourceref> helpers
    schema_order.py      DTD child ordering (pure string transform)
    xml.py               <database> skeleton writer
    handles.py           stable handle / display-id derivation
    xmlutil.py           XML escape (the five predefined entities)
```

Pure renderers take dataclasses in, return strings out, and never touch
sqlite3 — keeps them unit-testable without a live DB. `writer.py` is
the SQL-walk layer that opens the `.rmtree`, runs the queries, and
feeds the renderers.

Two things about `writer.py` that are easy to break:

- **The injection passes run in a fixed order** — `citationref`, then
  `noteref`, then `objref`, then `reporef` — and each one seeds from
  the *already-injected* lists, not the pre-injection originals.
  Seeding from the originals silently discards every `<citationref>`.
- **`reorder_children` runs last**, on every element. The DTD's child
  order differs per element (`<person>` wants `objref` before
  `noteref`; `<event>` wants it after), and injection can only ever
  append at the end.

## Tests

199 tests. Pure renderer tests need no fixture; writer and CLI tests
use `SampleTree.rmtree` (RM 11.0, 4.6 MB) at the repo root.

```sh
uv run pytest tests/
```

The integration tests need the `SampleTree.rmtree` sample database. It
is gitignored, so it is absent from a fresh clone; those tests are
**skipped** rather than failed when it is missing. Point `RM_SAMPLE_TREE`
at it to run them:

```sh
RM_SAMPLE_TREE=/path/to/SampleTree.rmtree \
  uv run pytest tests/
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
the order differs by element type and the cross-reference injection
pass could only ever append at the end.

## Schema reference

RM column names, FactType IDs, and link-table semantics live in
`docs/rm11-schema.md` of the **sibling `rmread` repository** — one
source of truth for the RootsMagic schema, not a copy of it. The Gramps
XML format reference is `example.gramps` at this repository's root.

## Licence

The rm2gramps source is MIT — see `LICENSE`.

One file is **not** MIT: `tests/data/grampsxml.dtd` is a verbatim,
unmodified copy of Gramps' own Document Type Definition and carries the
GPL header from the Gramps project. It ships as a test fixture and
contains no genealogy data — only element declarations. `tests/data/README.md`
records where it came from and how to refresh it. The MIT licence covers
the code in `src/`; the DTD stays under the GPL, and the two are kept
separate.

## Roadmap

- Possible: `SourceTemplateTable` → Gramps name-formats.
- Possible: `CitationLinkTable.Quality` → `<confidence>`.
- Possible: handle-based `<eventref role="Primary">` audit — v1
  trusts RM's `IsPrimary` flag.
