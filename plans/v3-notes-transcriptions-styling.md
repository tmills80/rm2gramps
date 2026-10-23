# `rm2gramps` v3 — Note types, transcriptions, styling

> **For Hermes:** Work this plan task-by-task, one RED→GREEN cycle per
> task, committing after each green cycle. Tests before code, always.

**Goal:** make exported notes mean what Gramps means by a note — right
type, real transcriptions, and RootsMagic's bold/italic markup carried
across as Gramps style ranges.

v2.2 shipped notes as an afterthought: every note came out
`type="general"` with the text flattened. Three defects follow, and v3
fixes all three.

1. **Wrong type.** `type="general"` is not a Gramps type name.
   Gramps' `GrampsType.set_from_xml_str` looks the string up in
   `_E2IMAP`, keyed on the exact English type name
   (`gramps/gen/lib/grampstype.py`). `"general"` is not a key, so
   Gramps imports every rm2gramps note as a **custom** type literally
   named "general" instead of the built-in "General". The lookup is
   case-sensitive: the key is `"General"`.
2. **Lost transcriptions.** `SourceTable.ActualText` (47 non-empty rows
   in SampleTree) and `CitationTable.ActualText` (31 rows) are the
   researcher's verbatim transcription of the source and of the
   specific citation. rm2gramps exports none of it.
3. **Lost styling.** RM note text carries `<b>` and `<i>`; rm2gramps
   escapes them into the note text as literal markup.

**v3 emits:** typed notes (one Gramps type per RM column),
`Source text` notes carrying source and citation transcriptions,
`<style>`/`<range>` children carrying RM's bold and italic.

**v3 explicitly defers:** `SourceTemplateTable` → Gramps name-formats;
RM-internal owner types 7 and 19; `CitationLinkTable.Quality` →
Gramps `<confidence>` (RM's quality is a per-link scale, Gramps'
confidence is per-citation — they do not map).

**Tradeoff accepted:** RM's `ShortFootnote` / `Footnote` /
`Bibliography` (31 rows each) are not exported. They are RootsMagic's
*rendered* citation strings, not source text; Gramps renders its own
footnotes from the citation's own fields. A researcher who wants RM's
exact footnote wording must re-render it from RM.

## Where the markup dialect lives

**The RootsMagic HTML-ish dialect is shared code, and it lives in
`rmread`.** `rmread` is the stdlib-only leaf both `rmcite` and
`rm2gramps` already sit downstream of, and the dialect is a fact about
the RootsMagic file format — `rmread`'s subject.

New module `tools/rmread/src/rmread/rmtext.py`:

| Function | Purpose | Consumer |
|---|---|---|
| `tokenize(markup)` | split markup into text / style / link / break / unknown-tag chunks | both |
| `plain_text(markup)` | plain text plus style ranges over it | `rm2gramps` |
| `normalize_newlines(s)` | CRLF → LF | both |

`rmcite` keeps its own AST (`rmcite/richtext.py`) and its own rendering
policy (strip unknown tags, decode entities); it rebuilds its parser on
top of `rmread.rmtext.tokenize`. `rm2gramps` uses `plain_text()`.

**Consequence, accepted deliberately:** `rmcite` gains a *runtime*
dependency on `rmread`. `rmread` is stdlib-only, so the dependency is
cheap, and `rmread` must be published before `rmcite` installs
standalone — already true of `rm2gramps`, which depends on `rmread` at
runtime today. `plans/repo-split.md` §2 records the dependency graph
and needs updating, as do `tools/cite/README.org`,
`tools/cite/DEVELOPMENT.org` and `tools/cite/src/rmcite/contract.py`
(which says "it never imports rmread" — true of the *version constant*,
which stays a deliberate copy; no longer true of the package).

**The rm-dump version copy stays a copy.** `rmcite.contract`'s
`SUPPORTED_SCHEMA_VERSION` remains a literal, not an import, so a newer
`rmread` cannot silently widen what `rmcite` accepts. The guard test in
`tools/cite/tests/test_contract.py` keeps doing that job.

## Six locked decisions

1. **One Gramps type per RM column, using Gramps' English type names
   verbatim.** Gramps matches the `type` attribute case-sensitively
   against `_E2IMAP`, built from the English strings in
   `gramps/gen/lib/notetype.py` (`_DATAMAPREAL` + `_DATAMAPIGNORE`).
   These are the strings Gramps itself writes, and the types Gramps'
   own UI assigns by owner — confirmed by the user's `example.gramps`,
   whose notes carry exactly these.

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
   | `AddressTable.Note` | `Repository Note` | 0 |
   | `MultimediaTable.Description` | `Media Note` | 16 |

2. **Transcriptions become notes, attached to their owner.**
   `SourceTable.ActualText` → a `Source text` note referenced from
   `<source>`; `CitationTable.ActualText` → a `Source text` note
   referenced from `<citation>`. Both element types already allow
   `noteref*` in the DTD, and the user's own tree does exactly this:
   47 `Source text` notes on `<source>`, 51 on `<citation>`.

3. **Style ranges are computed over LF-normalised text, and the
   exported text is LF.** XML line-end normalisation is mandatory: a
   parser converts `\r\n` to `\n` in content, and Gramps' importer
   stores what the parser hands it. RM's note text is CRLF (45 of 47
   `SourceTable.ActualText` rows). Ranges computed over raw CRLF text
   would be off by one after every line break. Normalise first, then
   compute ranges, then emit the normalised text.

4. **Unknown tags are preserved verbatim by rm2gramps; rmcite keeps
   stripping them.** SampleTree contains exactly one `<...>` construct
   in a note-bearing column that is not `<b>` or `<i>`: `<assistant
   curate>`, in the marriage-register transcription in
   `SourceTable.ActualText` (SourceID 18). RM stores note text raw —
   no entity escaping at all. So `<` in RM text is ambiguous between
   "markup I know" and "text the researcher typed". rm2gramps must not
   guess: it consumes the tags it knows and keeps everything else as
   literal text, because deleting transcription text is evidence loss.
   rmcite renders for a human reader and keeps stripping unknown tags.

5. **rm2gramps does not decode entities; rmcite keeps decoding.** RM
   writes raw text, so decoding `&amp;` would corrupt a literal
   `&amp;` the researcher typed. The shared tokenizer emits text chunks
   raw; each consumer decides.

6. **Dedup key is `(type, text)`.** Type is part of a note's identity:
   the same words as a `Person Note` and as a `Source text` are two
   different notes in Gramps, and collapsing them would give one of
   them the wrong type.

   *Suggested, and a change worth making in the same slice: derive the
   note handle from that key* (`_g_n` + 12 hex of sha256 of
   `type \0 text`) instead of assigning `_g_n1`, `_g_n2` … in first-seen
   order. First-seen order is not stable: adding a note kind renumbers
   every note after it, and a subset export renumbers differently from
   a full one. A content-derived handle is the same in every export
   that contains the note, which is what lets a researcher re-import a
   later export and have Gramps match the note to the one they already
   have. **Cost, stated plainly:** the handle format changes, so a
   re-import of a v2.2 export will not match its notes by handle.
   Display ids stay sequential (`N0001`), matching Gramps' convention.

## Schema reference

`tools/rmread/docs/rm11-schema.md` — notes are inline columns, not a
table; `SourceTable` / `CitationTable` carry `ActualText` (the
transcription) alongside `Comments` (the researcher's comment);
`MultimediaTable` carries `Description` and `Caption`; `AddressTable`
carries `Note`.

Gramps 1.7.2 DTD (`tools/rm2gramps/tests/data/grampsxml.dtd`):

```
<!ELEMENT note (text, style*, tagref*)>
<!ELEMENT style (range+)>
<!ATTLIST style name (bold|italic|underline|fontface|fontsize|
                      fontcolor|highlight|superscript|link) #REQUIRED
                value CDATA #IMPLIED>
<!ELEMENT range EMPTY>
<!ATTLIST range start CDATA #REQUIRED end CDATA #REQUIRED>
```

Nine permitted `style` names is the whole vocabulary; `bold`, `italic`
and `link` are the only ones in scope here.

## Output shape (Gramps 1.7.2)

```xml
<note handle="_g_n1a2b3c4d5e6f" change="1700000000" id="N0001"
      type="Event Note">
  <text>Married in the parish church after Banns by me J A Leug</text>
</note>

<!-- a note carrying RootsMagic's bold markup -->
<note handle="_g_n7f8e9d0c1b2a" change="1700000000" id="N0002"
      type="Source text">
  <text>Surname District Page</text>
  <style name="bold" value="True">
    <range start="0" end="7"/>
  </style>
</note>

<!-- a transcription, referenced from its source -->
<source handle="_g_s12" change="1700000000" id="S0012">
  <stitle>Marriage register</stitle>
  <noteref hlink="_g_n3c4b5a6978"/>
</source>
```

**Range ends are half-open** — `text[start:end]` is the styled run.
Gramps' `StyledText.split` treats them that way
(`gramps/gen/lib/styledtext.py`: `end = min(end_string, end_tag)`), and
the user's own export agrees: `<range start="0" end="1043"/>` on a
1043-character string.

`value="True"` on a boolean style is what Gramps' own exporter writes
(`exportxml.py`: `value = style.value; if value:`) and its importer
reads it back as `bool("True")`. A `link` style carries the URL as its
`value`, as in the user's tree.

**One `<style>` element per style name.** Gramps' importer appends
each `<range>` to the *last* `<style>` element
(`importxml.py`: `self.note_tags[-1].ranges.append(...)`), so grouping
all of a style's ranges under one `<style>` element is the only shape
that round-trips.

## Architecture

| Module | Change |
|---|---|
| `tools/rmread/src/rmread/rmtext.py` | **new** — shared dialect: `tokenize`, `plain_text`, `normalize_newlines` |
| `tools/rmread/tests/test_rmtext.py` | **new** — dialect tests |
| `tools/cite/src/rmcite/parser.py` | rebuild on `rmread.rmtext.tokenize`; keeps AST and policy |
| `tools/cite/pyproject.toml` | `rmread` moves from the `test` extra to runtime `dependencies` |
| `tools/rm2gramps/src/rm2gramps/notes.py` | type vocabulary; `<style>`/`<range>` rendering |
| `tools/rm2gramps/src/rm2gramps/notes_dedup.py` | dedup key `(type, text)`; transcriptions as notes |
| `tools/rm2gramps/src/rm2gramps/writer.py` | attach transcription noterefs to `<source>` / `<citation>` |

`rmread`'s layout stays flat (`db`, `event`, `family`, `person`,
`format`, `linktables`); `rmtext` joins them.

## Tasks

### T40. `rmread.rmtext` (test-first)

New module `tools/rmread/src/rmread/rmtext.py`, new test file
`tools/rmread/tests/test_rmtext.py`. One RED→GREEN cycle per test
below; run `pytest tools/rmread/tests/test_rmtext.py -v` after each.

- `tokenize` splits text, `<b>`/`<i>` (and `<strong>`/`<em>`), `<br>`,
  `<a href>`; an unknown `<assistant curate>` comes back as a `tag`
  chunk carrying its source text.
- `tokenize` does not decode entities and does not touch line endings.
- `plain_text` returns the text with known markup removed and unknown
  tags kept verbatim.
- `plain_text` returns style ranges over the *plain text*, half-open.
- `plain_text` normalises CRLF to LF, and the ranges are computed over
  the normalised string.
- Nested styles (`<b><i>x</i></b>`) yield a range for each style.

### T41. `rmcite` on the shared tokenizer

`rmcite/parser.py` rebuilds its AST from `rmread.rmtext.tokenize`:
unknown tags still stripped (contents kept), entities still decoded,
paragraphs still split on blank lines. `rmcite/richtext.py` and
`rmcite/__init__.py` keep their public shape, so `from rmcite import
parse` and `from rmcite.richtext import Document` are unchanged.
`tools/cite/pyproject.toml` declares the runtime dependency;
`tools/cite/README.org`, `DEVELOPMENT.org`, `contract.py` and
`plans/repo-split.md` are updated to say rmcite now imports rmread for
the shared dialect while still pinning the rm-dump version by copy.

### T42. `rm2gramps` note types

`notes.py` gains the type vocabulary; `notes_dedup.py` keys on
`(type, text)`. Every note the writer emits carries a Gramps type name
that appears in `notetype.py`'s `_DATAMAP` — no custom "general".

### T43. `rm2gramps` transcriptions

`notes_dedup.py` also loads `SourceTable.ActualText` and
`CitationTable.ActualText` as `Source text` notes; the writer attaches
them to `<source>` / `<citation>` with `<noteref>`. The stderr count
narrows to the three genuinely-dropped columns (`ShortFootnote` /
`Footnote` / `Bibliography`).

### T44. `rm2gramps` styling

`notes.py` renders `<style>`/`<range>` children from the shared
parser's ranges, in DTD order (`text` then `style`), and emits the
LF-normalised text the ranges index into.

### T45. Integration

Full `rm2gramps` export of `SampleTree.rmtree`, validated against the
vendored DTD, then shape checks: every `<noteref>` resolves, every
`<style>` has at least one `<range>`, every range lies within its
note's text length, every `<note>` type is a known Gramps type.

## Risks / open decisions

- **`<style>` requires at least one `<range>`** (`(range+)`), and
  `name` is restricted to nine values. A note whose only markup is an
  unknown tag gets no `<style>` at all — correct, since there is
  nothing to range.
- **`MultimediaTable.Description` stays in `<file description>`**, per
  the v2.2 decision that it is a `#REQUIRED` attribute of `<file>`.
  Gramps' own GEDCOM import of this tree *also* produced a `Media Note`
  for the same text (10 of 16 SampleTree descriptions match a
  `Media Note` verbatim), so Gramps shows it twice there. rm2gramps
  will not duplicate the text; the divergence is deliberate.
- **`AddressTable.Note` → `Repository Note`**: the column is empty in
  SampleTree, so this path is exercised only by synthetic tests.
- **Handle format change** — see decision 6; stated above with its
  cost.

## Source

- `SampleTree.rmtree` — RM 11.0, the dev tree. Every count in this
  plan is measured against it.
- `example.gramps` — the user's real Gramps export: 425 notes, the
  type vocabulary, the `<style>`/`<range>` shape, the range-end
  convention, and which types attach to which owner.
- `gramps-example-db/sqlite.db` — the same tree's Gramps database:
  numeric type values behind the XML type strings.
- Gramps upstream `gramps/gen/lib/notetype.py`, `styledtext.py`,
  `styledtexttagtype.py`, `grampstype.py`, `note.py`;
  `gramps/plugins/export/exportxml.py`;
  `gramps/plugins/importer/importxml.py`.
- `tools/rmread/docs/rm11-schema.md` — the RM11 schema reference.

## Done means

- Every exported `<note>` carries a Gramps type name that appears in
  `notetype.py`'s `_DATAMAP` — no custom "general".
- Every non-empty `SourceTable.ActualText` and `CitationTable.ActualText`
  is exported as a `Source text` note referenced from its owner.
- RootsMagic's `<b>`/`<i>` survive as `<style>`/`<range>`, and the
  ranges index the LF-normalised text Gramps will hold.
- The exported XML validates against the vendored Gramps DTD.
- `rmcite`'s public API and its test suite are unchanged.
- The rm-dump version constant stays a copy, and its guard test still
  fails when `rmread` bumps the version.
