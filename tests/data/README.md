# Test data

## `grampsxml.dtd`

Verbatim copy of Gramps' own Document Type Definition, from the
Gramps source tree:

    https://raw.githubusercontent.com/gramps-project/gramps/master/data/grampsxml.dtd

It is the authority for every element name, content model, and
required attribute in rm2gramps' output, and the schema tests check
the export against it rather than against the tool's own assumptions.
The upstream URL is Cloudflare-walled, which is why a copy lives here.

**Licence: GPL** (Copyright the Gramps contributors; the full header
is at the top of the file). It ships as a test fixture, unmodified.
It contains no genealogy data — only element declarations.

Note the copy is from Gramps master and self-identifies as v1.8.0,
while rm2gramps declares 1.7.2 in its DOCTYPE. Every element name and
content model rm2gramps emits is identical across the two; the
`<database>` child order checked here (`citations` before `sources`,
`objects` before `repositories`) is also the same.

To refresh: re-download the URL above into this directory, then run

    python -m pytest tests/test_grampsdtd.py tests/test_schema.py

`test_child_order_table_matches_the_dtd` will fail if a content model
has changed and `src/rm2gramps/schema_order.py` needs updating.

## `example.gramps` — NOT COMMITTED

A real Gramps 6.0.8 export. It is real research data and must not be
committed to this repository. When present locally,
`test_real_gramps_export_declares_no_unknown_elements` uses it as a
control for the DTD matcher; without it that single test skips and the
hand-built control document in `test_grampsdtd.py` is used instead.
