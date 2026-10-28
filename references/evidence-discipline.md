# Evidence discipline

This file is the *sourcing* reference for everything in this repository.
Code that touches a record follows these rules. Code that does not touch a
record does not need them.

## 1. Name the copy

Before any analysis on an England & Wales vital record (birth / marriage /
death registration after 1 July 1837), decide which kind of copy is in
front of you:

| Copy type | Where held | Hand(s) present | Informant signature | Marginalia | Handwriting tests |
|---|---|---|---|---|---|
| **Local register copy** | County record office (CRO / NRO / LRO / DRO) | Registrar + informant | Yes | Yes (corrections, later notes) | Meaningful |
| **GRO register copy** | GRO indexes reference these; the *digitised* books are on GRO indexes | Uniform GRO clerk hand | **No** | Minimal | Meaningless |
| **Certified copy certificate** | Issued by GRO on request | Pre-printed form, typeset | **No** (unless older form) | Minimal | Meaningless |

**Why this matters:** handwriting comparison, signature checks, and any
analysis that depends on "who filled in this form" only make sense on a
local register copy. A GRO copy or a modern certified certificate looks
authoritative but is a transcribed artefact; treating it as primary
evidence is a category error.

**How a tool should handle this:**

- Every script that processes vital records takes a `--copy-type` flag
  with at least the three values above.
- The default assumes *unknown* and refuses to run record-graphy tests on
  it, not silently passing them.
- The output header states the copy type it was run against.

## 2. Cite, don't summarise

Output that quotes a date, name, or place **carries the source citation
inline**, not at the end. The reader should never have to chase a footnote
to check whether the claim is supported.

Minimum inline citation shape:

```
Staines, Thomas, b. 1840 Q4, Aston. [GRO index, vol. XVI, p. 211]
```

Acceptable citation sources (in order of strength):

1. The original record image (archive + series + volume + folio / image ref).
2. A local register copy transcription by a named researcher with date.
3. A GRO index entry (indexes are derivative, not original).
4. A published transcript (Iyerson / MIs / parish register series).

A claim with no citation is **not a finding**. It is a draft that has not
yet been checked.

## 3. GEDCOM is not kinship

A `.ged` file (or any researcher export) is one researcher's working
hypothesis encoded in a quasi-standard format. Treat it as:

- **Authoritative on what it claims** (this @I…@ exists, was named X,
  has these children).
- **Suspect on what it implies** (that two same-surname individuals are
  the same person, that proximity in a vault means kinship).

**Rules when working across researcher GEDCOMs:**

- Never infer kinship from shared surname or shared parish in the same
  vault. `William PlaceholderSurname` in Yarmouth ≠ `William PlaceholderSurname` in PlaceholderPlace; even
  two `William PlaceholderSurname` in Yarmouth a generation apart need verification.
- Cite the `@I…@` pointer next to any extracted fact: `@I1234 (PlaceholderSurnameTwo
  Family Tree, exported 2024-06-12 by J. PlaceholderSurnameTwo)`.
- Verify `FAMS` (spouse-in) and `FAMC` (child-of) links before merging two
  records. A missing `FAMC` does not mean "no parents known" — it can mean
  "researcher had not got that far when the export was made."

## 4. Provenance over polish

The right answer from a tool looks like:

> *Occupation recorded in 1851 census entry for household at 14 Castle
> Street, PlaceholderPlace: " Brass Founder." (TNA HO107/2063, folio 24r,
> enumerated 1851-03-30 by Thomas Oakley.) Note: image legibility at
> marginalia marginal — see also TNA RG09 piece 2444 if seeking
> later-life occupation.*

The wrong answer looks like:

> *He was a brass founder.*  *(footnote: census, 1851)*

The difference is not length — it is whether another researcher, six
months from now, can find and check the source without going through you.

## 5. Anonymisation for public commits

Do not commit:

- Records of anyone born **after 1906** whose death has not been
  registered (UK data-protection practice; treat as living).
- Full dates of birth / marriage / death for living individuals. Year
  only, or omit.
- Anything under a `RESEARCHER_PRIVATE.md` flag without explicit consent.

If a script needs to handle personal data, it **hashes** identifiers
before write and never logs raw names.

## 6. When you are unsure

Ask. The cost of a clarifying question is small; the cost of a tool that
silently mangles an 1841 census page is large. One short question beats
guessing.
