# datasheet2json

**Get the spec tables out of a component datasheet PDF as clean JSON or CSV.**

Copying absolute max ratings and electrical characteristics out of datasheets by hand is slow
and error-prone. `datasheet2json` finds those tables, works out which column is MIN / TYP / MAX /
UNIT, and gives you one record per spec. It runs offline, needs no API key, and gives the same
output every time.

```bash
pip install git+https://github.com/aysel-elsh/datasheet2json
datasheet2json TLV61048.pdf > tlv61048.json
```

## Example

From TI's TLV61048 boost converter datasheet, *Recommended Operating Conditions*:

```json
{
  "section": "Recommended Operating Conditions",
  "page": 4,
  "columns": ["symbol", "parameter", "min", "typ", "max", "unit"],
  "specs": [
    { "parameter": "Input voltage range", "symbol": "VIN", "min": "2.65", "max": "5.5", "unit": "V",
      "numeric": { "min": 2.65, "max": 5.5 } },
    { "parameter": "Effective inductance range", "symbol": "L", "min": "2.2", "typ": "4.7", "max": "10", "unit": "µH",
      "numeric": { "min": 2.2, "typ": 4.7, "max": 10.0 } }
  ]
}
```

Search for one spec:

```console
$ datasheet2json IS31FL3731.pdf --find "supply voltage"
[{"section": "ELECTRICAL CHARACTERISTICS", "page": 5, "parameter": "Supply voltage",
  "symbol": "VCC", "min": "2.7", "max": "5.5", "unit": "V", ...}]
```

Or get a flat CSV for a spreadsheet or BOM tool:

```bash
datasheet2json CAT24C256.pdf --csv -o cat24c256.csv
```

## What it handles

- **Column detection by position, not by drawn lines.** Many vendors right-align numbers past
  the cell borders, so reading cells directly puts values in the wrong column.
- **Subscripts**: `V` + small `IN` becomes `VIN`, and `T` + `A` becomes `TA`.
- **Merged cells**: a parameter or unit spanning several condition rows is copied to each row.
- **Category rows** such as `POWER SUPPLY` and `OUTPUT` become a `category` field.
- **Two-level headers** like `Standard | Fast | Fast-Plus` over `Min Max` become
  `standard_min`, `fast_max`, ...
- **Section names** come from the nearest heading or table caption.
- Unicode minus signs and en dashes are normalised, `(cid:N)` glyphs before units become `µ`,
  and every min/typ/max/value that is a plain number is also given as a float in `numeric`.
- Pin tables, register maps and ordering tables are skipped.

Tested on datasheets from TI, onsemi and ISSI.

## Python

```python
from datasheet2json import extract

ds = extract("TLV61048.pdf")
ds.part                       # 'TLV61048'
for table, spec in ds.find("quiescent"):
    print(table.section, spec.typ, spec.unit, spec.conditions)
ds.to_dict()                  # plain JSON-ready dict
```

## Limitations (good first issues)

- Tables need a text layer. Scanned PDFs need OCR first (e.g. `ocrmypdf`).
- Tables without ruling lines aren't detected yet.
- Header-less two-column tables (`Supply voltage | -0.3 V ~ 6 V`) are skipped.
- A table that continues onto the next page without repeating its header loses the second half.
- Values such as `VCC + 0.3` stay as text, with no float in `numeric`.

If a datasheet comes out wrong, open an issue with a link to the PDF and the table name.

## Develop

```bash
pip install -e ".[test]" && pytest
```

Tests build a small fake datasheet with reportlab, so no vendor PDFs are stored in the repo.

MIT License.
