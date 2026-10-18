"""``rm2gramps`` CLI entry point.

Thin shim over :func:`rm2gramps.writer.export_database` plus
optional gzip wrapping and disk IO. All real work happens in the
writer module.

Usage::

    rm2gramps Tree.rmtree out.gramps             # gzipped
    rm2gramps Tree.rmtree out.gramps --no-gzip   # raw XML
    rm2gramps Tree.rmtree out.gramps --person-ids 1,2,3

Exit codes follow rm-cite / rm-dump convention:
- 0: success
- 1: not really used; reserved for future "partial success"
- 2: input / IO error (file missing, schema rejection, write fail)
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

from rmread import SchemaError

from ..writer import export_database


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rm2gramps",
        description=(
            "Convert a RootsMagic (.rmtree) SQLite database into a "
            "Gramps XML (.gramps) file. Read-only on the input."
        ),
    )
    p.add_argument("rmtree", help="Path to the input .rmtree file.")
    p.add_argument("out_gramps", help="Path to write the output .gramps file.")
    p.add_argument(
        "--no-gzip",
        action="store_true",
        help="Write raw XML instead of gzipped output.",
    )
    p.add_argument(
        "--person-ids",
        help=(
            "Comma-separated PersonID subset to export. When supplied, "
            "families and family events are narrowed to those that "
            "reference any of the given persons. Default: export the "
            "entire database."
        ),
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output to stderr.",
    )
    return p


def _parse_person_ids(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    out: list[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(int(tok))
    return out or None


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    rmtree_path = Path(args.rmtree)
    out_path = Path(args.out_gramps)

    try:
        person_ids = _parse_person_ids(args.person_ids)
    except ValueError as e:
        print(f"error: --person-ids: {e}", file=sys.stderr)
        return 2

    if not args.quiet:
        ids_msg = (
            f"({len(person_ids)} persons) " if person_ids is not None else ""
        )
        print(
            f"# reading {rmtree_path} {ids_msg}…",
            file=sys.stderr,
            end="",
            flush=True,
        )

    try:
        payload = export_database(rmtree_path, person_ids=person_ids)
    except FileNotFoundError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 2
    except SchemaError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 2

    try:
        if args.no_gzip:
            out_path.write_bytes(payload)
        else:
            with gzip.open(out_path, "wb") as f:
                f.write(payload)
    except OSError as e:
        print(f"\nerror: could not write {out_path}: {e}", file=sys.stderr)
        return 2

    if not args.quiet:
        size = out_path.stat().st_size
        kind = "xml" if args.no_gzip else "gzipped xml"
        print(f"\n# wrote {size} bytes ({kind}) to {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":                  # pragma: no cover
    raise SystemExit(main())