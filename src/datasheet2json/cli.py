"""datasheet2json part.pdf [-o out.json] [--csv] [--find "supply voltage"] [--pages 4-6]"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from .extract import extract

_CSV_FIELDS = ["section", "page", "category", "parameter", "symbol", "conditions", "min", "typ", "max", "value", "unit", "extra"]


def _pages(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="datasheet2json", description="Extract spec tables from a datasheet PDF.")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--output", help="write to a file instead of stdout")
    ap.add_argument("--csv", action="store_true", help="flat CSV, one row per spec")
    ap.add_argument("--find", metavar="TEXT", help="only specs whose parameter/symbol contains TEXT")
    ap.add_argument("--pages", help="pages to scan, e.g. 3-6 or 4,5,9")
    ap.add_argument("--indent", type=int, default=2)
    a = ap.parse_args(argv)

    try:
        ds = extract(a.pdf, _pages(a.pages) if a.pages else None)
    except FileNotFoundError:
        sys.exit(f"error: no such file: {a.pdf}")

    pairs = ds.find(a.find) if a.find else [(t, s) for t in ds.tables for s in t.specs]
    out = open(a.output, "w", newline="", encoding="utf-8") if a.output else sys.stdout
    try:
        if a.csv:
            w = csv.DictWriter(out, fieldnames=_CSV_FIELDS)
            w.writeheader()
            for t, s in pairs:
                d = s.to_dict()
                d.pop("numeric", None)
                if "extra" in d:
                    d["extra"] = json.dumps(d["extra"], ensure_ascii=False)
                w.writerow({"section": t.section, "page": t.page, **d})
        elif a.find:
            rows = [{"section": t.section, "page": t.page, **s.to_dict()} for t, s in pairs]
            json.dump(rows, out, indent=a.indent, ensure_ascii=False)
            out.write("\n")
        else:
            json.dump(ds.to_dict(), out, indent=a.indent, ensure_ascii=False)
            out.write("\n")
    finally:
        if a.output:
            out.close()
    if not ds.tables:
        print("warning: no spec tables found (scanned PDFs without a text layer aren't supported)", file=sys.stderr)


if __name__ == "__main__":
    main()
