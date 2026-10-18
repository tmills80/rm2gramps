# `rm2gramps` — RM 11 `.rmtree` → Gramps XML `.gramps`

> **For Hermes:** Use the `plan` skill and `test-driven-development` skill to
> implement this plan task-by-task. Each task is one bounded change with a
> failing test first, a green commit second.

**Goal:** convert a RootsMagic 11 SQLite database into a Gramps XML 1.7.2
`.gramps` file (gzipped by default, matching how Gramps itself writes them).

**Why this exists:** RM only exports to GEDCOM, not to Gramps XML.
The Gramps XML `.gramps` format is a Gramps-side format — Gramps
itself imports GEDCOM and can re-export as `.gramps`. So the
round-trip path today is `rmtree → GEDCOM → Gramps import → Gramps
export → .gramps`. That route loses information we already have in
the SQLite DB: precise fact-type vocabulary, full citation detail,
multimedia links, the full place hierarchy with master / associated
records, and the difference between primary and non-primary events.
A direct `rmtree → .gramps` tool preserves all of that and is also
scriptable, version-stable, and runnable in CI / from the command
line for batch research pipelines.

**Why not script Gramps' Python API:** the Gramps API operates on a live
on-disk database (a directory of B-tree files via the `sqlite` backend,
see `tools/gramps-schema-doc/docs/01-quickstart.md`). Producing a `.gramps`
file is an XML-serialisation problem, and emitting XML directly lets us
(a) have no runtime Gramps dependency, (b) keep round-trip output
deterministic (same handle scheme across runs), and (c) keep the tool
testable with stdlib `xml.etree.ElementTree` rather than a Gramps install.

**Tech stack:** Python 3.12+, standard library only.
- `sqlite3` (with `RMNOCASE` collation registered — see `tools/rmread/docs/rm11-schema.md` § "The `RMNOCASE` collation")
- `xml.etree.ElementTree` (writer + reader for round-trip tests)
- `gzip`
- `dataclasses`, `argparse`, `pathlib`

No third-party packages. Same house style as `rmread` and `cite`.

## Slice decision (locked in)

**v1 emits:** `<header>`, `<events>`, `<people>`, `<families>`, `<places>`.

**v1 explicitly defers:** citations, sources, notes, media, repositories,
addresses, URLs, DNA, FAN, witnesses, tasks, exclusions, health, ancestry,
familysearch-sync, payloads, group ranges.

**Reasoning:** a `.gramps` that imports cleanly into Gramps needs the core
4 (people, events, families, places). The deferred items all live in
RM's link-table polymorphism (`*LinkTable` with `(OwnerType, OwnerID)`)
and getting them right requires per-link, per-`OwnerType` semantics
(see `tools/rmread/docs/rm11-schema.md` § "Conventions every `*LinkTable`
shares"). That's a follow-up commit with its own slice decision; v1
should not block on it.

**Tradeoff accepted:** opening a v1 export in Gramps will show a coherent
tree but no source citations or media. Researchers who need those use
RM's own GEDCOM exporter for now and the v2 tool once it lands. The
fact-type vocabulary *is* preserved (v1 walks `FactTypeTable`), so
census / residence / probate / occupation events survive correctly.

## Architecture

```
src/rm2gramps/
    cli/export.py        # argparse entry point
    db.py                # sqlite3 open + RMNOCASE registration + query helpers
    handles.py           # stable handle/id derivation (RM UUID → Gramps handle)
    events.py            # EventTable rows → <event> elements
    people.py            # PersonTable + NameTable rows → <person> elements
    families.py          # FamilyTable + ChildTable rows → <family> elements
    places.py            # PlaceTable rows → <placeobj> elements (deduped)
    xml.py               # the top-level writer producing the full <database>

tests/                  # pytest, one file per module
docs/README.md          # one-page usage guide
pyproject.toml
```

Single-import boundary: nothing in `rm2gramps/` imports from `rmread/`.
We depend on `rmread`'s *schema knowledge* (column names, FactType IDs)
but query SQLite ourselves so a future refactor of `rmread` doesn't
silently break the export.

## Identity stability

A `.gramps` file references objects via **handles** (string ids). For
deterministic output across runs:

- Handle scheme: `"_g_" + lowercased RM UniqueID` for objects that have
  one (Person uses `PersonTable.UniqueID`); `"_g_p" + str(PlaceID)` for
  places; `"_g_e" + str(EventID)` for events; `"_g_f" + str(FamilyID)`
  for families.
- Display id scheme: zero-padded 4-digit decimal — `"I%04d"` for
  PersonID, `"F%04d"` for FamilyID, `"E%04d"` for EventID, `"P%04d"`
  for PlaceID.
- This mirrors the format Gramps itself emits (compare `example.gramps`,
  which uses `"I0001"`, `"F0002"`, `"E0000"`, `"P0001"`).
- Same input DB → same output `.gramps` bytes (modulo gzip header
  timestamp). Test asserts byte-equality of two writes.

## Output shape

Top-level element: `<database xmlns="http://gramps-project.org/xml/1.7.2/">`.

Inside:
```xml
<header>
  <created date="YYYY-MM-DD" version="rm2gramps/0.0.1"/>
  <researcher/>
</header>
<events>...</events>
<people>...</people>
<families>...</families>
<places>...</places>
```

Element order matches Gramps' own exports (events first, then people,
then families, then places). Gramps is tolerant about ordering in
practice, but matching its convention makes diffing against an
RM-produced export easier.

### `<event>` shape

```xml
<event handle="_g_e123" change="<unix-seconds>" id="E0123">
  <type>Birth</type>                  <!-- mapped via FactTypeTable.Name -->
  <dateval val="1840-06-12"/>         <!-- ISO from RM SortDate -->
  <place hlink="_g_p456"/>
  <description>...</description>      <!-- from EventTable.Details if set -->
</event>
```

RM's `Date TEXT` ("12 JUN 1840") gets converted to ISO date form when
`SortDate` is non-zero; otherwise we omit `dateval` entirely. (See
Risks.)

### `<person>` shape

```xml
<person handle="_g_<uuid>" change="<unix-seconds>" id="I0001">
  <gender>M</gender>                  <!-- M/F/U from PersonTable.Sex -->
  <name type="Birth Name">
    <first>Given</first>
    <surname>Surname</surname>
  </name>
  <eventref hlink="_g_e1" role="Primary"/>     <!-- primary events -->
  <attribute type="_UID" value="<rm uuid>"/>   <!-- round-trip marker -->
  <childof hlink="_g_f12"/>           <!-- one per parent family -->
  <parentin hlink="_g_f13"/>          <!-- one per family as parent -->
</person>
```

`role="Primary"` matches the `IsPrimary` flag on EventTable. Non-primary
events emit `<eventref>` without `role`.

### `<family>` shape

```xml
<family handle="_g_f12" change="<unix-seconds>" id="F0012">
  <rel type="Married"/>
  <father hlink="_g_<uuid>"/>
  <mother hlink="_g_<uuid>"/>
  <childref hlink="_g_<uuid>"/>
</family>
```

`<rel>` defaults to `type="Married"`; if neither spouse is recorded,
emit `<rel type="Unknown"/>`. (RM has no equivalent field; we choose
"Unknown" as the safest default and let the researcher override in
Gramps.)

### `<placeobj>` shape

```xml
<placeobj handle="_g_p45" change="<unix-seconds>" id="P0045" type="Unknown">
  <ptitle>Name</ptitle>
  <pname value="Name"/>
</placeobj>
```

Deduplicate by `PlaceID`. `type` defaults to `Unknown` (Gramps-controlled
vocabulary that RM does not map).

## CLI

```
rm2gramps [-h] [--no-gzip] [--person-ids IDS] rmtree out_gramps

positional:
  rmtree         path to input .rmtree (read-only)
  out_gramps     path to output .gramps

options:
  --no-gzip      write raw XML (Gramps accepts both)
  --person-ids   comma-separated PersonID subset to export (default: all)
  --quiet        suppress progress output to stderr
```

Defaults to gzip (matches what `example.gramps` in the repo uses).

## Tasks

Task order is dependency-driven: handles before XML helpers; XML
helpers before events; events before people; families and places can be
parallelised after events.

### T1. Scaffolding

- Create `tools/rm2gramps/` with `pyproject.toml`, `src/rm2gramps/`,
  `tests/`, `docs/`. Mirror `tools/rmread/` layout exactly.
- `pyproject.toml`: `name = "rm2gramps"`, `version = "0.0.1"`,
  `requires-python = ">=3.12"`, `dependencies = []`,
  entry point `rm2gramps = "rm2gramps.cli.export:main"`.
- `tests/__init__.py`, `tests/conftest.py` with a fixture that copies
  `SampleTree.rmtree` to a temp file (so we don't hold the real one
  open across tests).

### T2. Handles (test-first)

Tests in `tests/test_handles.py`:
- `test_person_handle_from_uuid` — given `UniqueID="abc"`, handle is
  `"_g_abc"`.
- `test_event_handle_from_id` — given `EventID=123`, handle is
  `"_g_e123"`.
- `test_display_id_format` — `format_display_id(123, "I") == "I0123"`.

Then write `src/rm2gramps/handles.py`.

### T3. db.py (test-first)

Tests in `tests/test_db.py`:
- `test_rmnocase_registered` — open `SampleTree.rmtree`, run a query
  that hits a `RMNOCASE`-collated column (`AddressTable` COUNT), no
  error. This is the regression test for the bug noted in
  `tools/rmread/docs/rm11-schema.md` § "Verified-in-this-DB caveats"
  item 3.
- `test_open_rejects_non_rmtree` — feeding a random SQLite file
  raises `SchemaError`.
- `test_query_only_enforced` — opening a DB and trying to run an
  `INSERT` raises `sqlite3.OperationalError` (belt-and-braces alongside
  rmread's `mode=ro` URI).

Then write `src/rm2gramps/db.py`. Reuse the same `RMNOCASE` registration
code as `rmread` — copy, don't import (deliberate; see Architecture).

### T4. events.py (test-first)

Tests in `tests/test_events.py`:
- `test_birth_event_minimum` — synthetic Event row with `EventType=1`,
  `Date="1840-06-12"`, `SortDate=18400612`, `PlaceID=5` →
  `<event handle="_g_e5" change="..." id="E0005"><type>Birth</type>
  <dateval val="1840-06-12"/><place hlink="_g_p5"/></event>`.
- `test_unknown_fact_type_renders_as_unknown` — synthetic `EventType=9999`
  → `<type>Unknown(9999)</type>`.
- `test_event_without_place_omits_place_ref` — `PlaceID=0` →
  no `<place>` child.
- `test_event_without_date_omits_dateval` — empty `Date` and
  `SortDate=0` → no `<dateval>`.
- `test_iso_date_from_sort_date` — `Date="12 JUN 1840"`,
  `SortDate=18400612` → `dateval val="1840-06-12"`.

Then write `src/rm2gramps/events.py`.

### T5. places.py (test-first)

Tests in `tests/test_places.py`:
- `test_placeobj_minimum` — `PlaceID=5`, `Name="Foo"` →
  `<placeobj ... id="P0005"><ptitle>Foo</ptitle><pname value="Foo"/></placeobj>`.
- `test_placeobj_empty_name` — `Name=""` → emits `id="P0005"` but
  no `<ptitle>` / `<pname>` (placeholder for the researcher to fix
  in Gramps).

Then write `src/rm2gramps/places.py`.

### T6. families.py (test-first)

Tests in `tests/test_families.py`:
- `test_family_with_both_parents` — FamilyTable row with FatherID
  and MotherID set → `<family>` with both `<father>` / `<mother>` and
  `<rel type="Married"/>`.
- `test_family_single_parent` — only `FatherID` set →
  `<rel type="Unknown"/>`, no `<mother>`.
- `test_family_with_no_parents` — both 0 → `<rel type="Unknown"/>`,
  no `<father>` or `<mother>`.
- `test_family_children_from_child_table` — ChildTable rows for the
  FamilyID ordered by `ChildOrder` → `<childref>` list in that order.
- `test_family_event_refs` — `OwnerType=1` events for the FamilyID
  → `<eventref role="Family">` list.

Then write `src/rm2gramps/families.py`.

### T7. people.py (test-first)

Tests in `tests/test_people.py`:
- `test_person_minimum` — PersonTable + primary NameTable row →
  `<person>` with `<gender>` (from `Sex` 0/1/2 → U/M/F),
  `<name type="Birth Name">` with `<first>` and `<surname>`,
  `<attribute type="_UID" value="...">` for round-trip.
- `test_person_eventrefs_chronological` — events for the PersonID
  ordered by `SortDate` → `<eventref>` list in that order.
- `test_person_childof_and_parentin` — ChildTable → FamilyTable walks
  produce one `<childof>` per parent family, one `<parentin>` per
  family-as-parent.
- `test_person_gender_unknown` — `Sex=0` → `<gender>U</gender>`.
- `test_person_alt_names` — multiple NameTable rows → multiple
  `<name>` elements; the `NameType=0` row stays `<name type="Birth Name">`,
  others get `<name type="Married Name">` / etc., mapped from
  NameType int to Gramps name type strings.

Then write `src/rm2gramps/people.py`.

### T8. xml.py — top-level writer (test-first)

Tests in `tests/test_xml.py`:
- `test_writer_emits_required_root_attributes` — output has
  `<database xmlns="http://gramps-project.org/xml/1.7.2/">` with
  `<header>` containing `<created>` and empty `<researcher>`.
- `test_writer_emits_empty_database` — empty DB → file with header
  and four empty child sections (no `<event>`, `<person>`, etc.).
- `test_writer_orders_sections` — events before people before
  families before places.

Then write `src/rm2gramps/xml.py`.

### T9. CLI (test-first)

Tests in `tests/test_cli.py`:
- `test_cli_writes_gzipped_file` — `rm2gramps SampleTree.rmtree
  /tmp/out.gramps` → file exists, magic bytes `\x1f\x8b` (gzip).
- `test_cli_no_gzip` — same with `--no-gzip` → file starts with
  `<?xml`.
- `test_cli_person_ids_subset` — `--person-ids 1` → output XML
  contains exactly one `<person>` element.
- `test_cli_missing_input` — non-existent path → exit code 2, error
  on stderr.
- `test_cli_invalid_rmtree` — garbage SQLite file → exit code 2,
  "not a RootsMagic database" on stderr.

Then write `src/rm2gramps/cli/export.py`.

### T10. Integration test

`tests/test_integration.py`:
- Open `SampleTree.rmtree`, run the full export pipeline, gunzip,
  parse with `xml.etree.ElementTree`, assert:
  - root tag is `{http://gramps-project.org/xml/1.7.2/}database`
  - at least 1 person, 1 event, 1 family, 1 place (sanity)
  - every `<person handle="...">` has a matching `eventref` set
    where the `hlink` resolves to an existing `<event handle>`
  - every `<childof hlink="...">` resolves to a `<family handle>`
  - every `<parentin hlink="...">` resolves to a `<family handle>`
  - handles are stable across two runs (byte-equal XML output)

This is the round-trip test. If this passes, the v1 tool is shippable.

## Risks / open decisions to call out before coding

1. **RM date strings that won't parse.** RM accepts fuzzy dates like
   "BEF 1840", "ABT JUN 1840", "BET 1840 AND 1845". `SortDate` may
   still be set. For v1 we trust `SortDate` (ISO format) and drop the
   raw string when we can't use it. If `SortDate=0` we omit `dateval`.
   Researchers will see dates with reduced precision; v2 can render
   the raw string via `<datespan>`.

2. **Gender mapping.** RM has 0/1/2 (unknown/male/female); Gramps has
   M/F/U. Straight map. **Decision: M=1, F=2, U=0.**

3. **Living/privacy.** AGENTS.md and `references/evidence-discipline.md`
   § "Anonymisation for public commits" says don't commit records of
   anyone born after 1906 whose death isn't registered. v1 does NOT
   anonymise — that's the researcher's responsibility when they
   commit the output. We surface `--person-ids` so a researcher can
   subset the export to a known-safe cohort for testing.
   **Documented limitation, not a v1 fix.**

5. **Citation map.** `example.gramps` has `<citationref hlink="...">`
   on most events, pointing to `<citation>` objects. RM has
   `CitationLinkTable` joining events to citations via
   `(OwnerType, OwnerID)` (and the right `OwnerType` for event→citation
   is event-dependent — see `tools/rmread/docs/rm11-schema.md` §
   "Citation, source, multimedia, address, URL"). **v1 drops
   citations;** v2 walks `CitationLinkTable` per `OwnerType`.

## Source

Mirrors the structure of `tools/rmread/docs/rm11-schema.md`. That doc
is the schema reference; this one is the *tool* reference.

The example XML output (`example.gramps` at repo root) is the format
reference. Re-read it before emitting any element type — Gramps has
quirks (e.g. `<eventref role="Primary">` for events on persons vs.
`<eventref role="Family">` for events on families) that a guess would
miss.

## Done means

- `python -m pytest tools/rm2gramps/tests/` is green.
- `rm2gramps SampleTree.rmtree /tmp/SampleTree.gramps` produces a
  valid `.gramps` that opens in Gramps without error.
- Two consecutive runs produce byte-equal (after gunzip) XML.
- `tools/rm2gramps/docs/README.md` exists with a one-page usage guide.
- `tools/rm2gramps/pyproject.toml` entry-point installs cleanly into
  the rmread venv (it's the same Python; both use stdlib-only).