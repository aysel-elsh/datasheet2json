"""Pull specification tables (absolute max, electrical characteristics, ...) out of datasheet PDFs.

How it works
------------
1. pdfplumber finds ruled tables on each page.
2. A table is kept only if one of its first rows looks like a spec header
   (MIN / TYP / MAX / UNIT / VALUE / RATING ...). Pin tables, register maps and
   ordering tables are skipped.
3. Words are placed into columns by where they sit under the header words, not
   by the drawn cell borders. Vendors (TI especially) right-align numbers past
   the cell lines, so cell borders alone give wrong columns.
4. The nearest heading above the table ("Absolute Maximum Ratings", ...) names
   the section. Category rows like "POWER SUPPLY" are attached to the rows below.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pdfplumber

__all__ = ["Spec", "Table", "Datasheet", "extract", "parse_number"]

# ---------------------------------------------------------------- vocab ----

_CANON = {
    "parameter": "parameter",
    "parameters": "parameter",
    "characteristic": "parameter",
    "characteristics": "parameter",
    "description": "parameter",
    "item": "parameter",
    "symbol": "symbol",
    "sym": "symbol",
    "condition": "conditions",
    "conditions": "conditions",
    "test condition": "conditions",
    "test conditions": "conditions",
    "min": "min",
    "minimum": "min",
    "typ": "typ",
    "typical": "typ",
    "nom": "typ",
    "max": "max",
    "maximum": "max",
    "unit": "unit",
    "units": "unit",
    "value": "value",
    "values": "value",
    "rating": "value",
    "ratings": "value",
    "limit": "value",
    "limits": "value",
}
_NUMERIC_KEYS = {"min", "typ", "max", "unit", "value"}
_SPEC_KEYS = {"min", "typ", "max", "value"}

_SECTION_HINTS = [
    "absolute maximum",
    "recommended operating",
    "operating conditions",
    "electrical characteristics",
    "electrical specifications",
    "dc characteristics",
    "ac characteristics",
    "dc electrical",
    "ac electrical",
    "switching characteristics",
    "timing",
    "thermal",
    "esd",
    "reliability",
    "capacitance",
    "characteristics",
    "specifications",
    "ratings",
]

_DASHES = str.maketrans({"–": "-", "−": "-", "—": "-", "‒": "-", "­": "-"})


def _norm_label(text: str) -> str:
    t = re.sub(r"\(\d+\)|\[\d+\]", "", text)  # footnote markers like (1)
    t = re.sub(r"[^a-z ]", "", t.lower().replace(".", "")).strip()
    return re.sub(r"\s+", " ", t)


def _canon(text: str) -> str | None:
    return _CANON.get(_norm_label(text))


# ------------------------------------------------------------- numbers ----

_NUM_RE = re.compile(r"^\s*([+-]?±?\s*\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?)\s*([a-zA-Zµμ°Ω%/]*)\s*$")


def parse_number(text: str | None) -> float | None:
    """``"-0.3"`` -> -0.3, ``"1,000,000"`` -> 1e6, ``"5.5V"`` -> 5.5, ``"VCC + 0.3"`` -> None."""
    if not text:
        return None
    t = text.translate(_DASHES).replace("±", "")
    m = _NUM_RE.match(t)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


# --------------------------------------------------------------- model ----


@dataclass
class Spec:
    parameter: str
    symbol: str | None = None
    conditions: str | None = None
    min: str | None = None
    typ: str | None = None
    max: str | None = None
    value: str | None = None
    unit: str | None = None
    category: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def numbers(self) -> dict[str, float]:
        """The min/typ/max/value fields that parse as plain numbers."""
        out = {}
        for k in ("min", "typ", "max", "value"):
            n = parse_number(getattr(self, k))
            if n is not None:
                out[k] = n
        for k, v in self.extra.items():  # grouped columns like "fast_min"
            if k.rsplit("_", 1)[-1] in _SPEC_KEYS:
                n = parse_number(v)
                if n is not None:
                    out[k] = n
        return out

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if v not in (None, "", {})}
        nums = self.numbers()
        if nums:
            d["numeric"] = nums
        return d


@dataclass
class Table:
    section: str
    page: int
    columns: list[str]
    specs: list[Spec]

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "page": self.page,
            "columns": self.columns,
            "specs": [s.to_dict() for s in self.specs],
        }


@dataclass
class Datasheet:
    source: str
    part: str | None
    pages: int
    tables: list[Table]

    @property
    def specs(self) -> list[Spec]:
        return [s for t in self.tables for s in t.specs]

    def find(self, query: str) -> list[tuple[Table, Spec]]:
        """Case-insensitive search over parameter, symbol and category."""
        q = query.lower()
        hits = []
        for t in self.tables:
            for s in t.specs:
                hay = " ".join(x or "" for x in (s.parameter, s.symbol, s.category)).lower()
                if q in hay:
                    hits.append((t, s))
        return hits

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "part": self.part,
            "pages": self.pages,
            "tables": [t.to_dict() for t in self.tables],
        }


# ------------------------------------------------------------ helpers -----


@dataclass
class _Anchor:
    key: str  # canonical key or raw label
    label: str
    x0: float
    x1: float
    numeric: bool

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


def _words(page, bbox):
    crop = page.crop(bbox, strict=False)
    return crop.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False, extra_attrs=["size"])


def _phrases(words, gap=6.0):
    """Merge header words that sit next to each other ("TEST" "CONDITIONS")."""
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    out = []
    for w in words:
        if (
            out
            and abs(w["top"] - out[-1]["top"]) < 3
            and w["x0"] - out[-1]["x1"] < gap
            and _canon(w["text"]) not in _NUMERIC_KEYS
            and _canon(out[-1]["text"]) not in _NUMERIC_KEYS
        ):
            prev = out[-1]
            out[-1] = {**prev, "text": prev["text"] + " " + w["text"], "x1": w["x1"]}
        else:
            out.append(dict(w))
    # header cells sometimes wrap onto two lines ("TEST" / "CONDITIONS"): merge vertically
    merged = []
    for p in sorted(out, key=lambda w: w["x0"]):
        for m in merged:
            if p["x0"] < m["x1"] + 2 and p["x1"] > m["x0"] - 2 and _canon(p["text"]) not in _NUMERIC_KEYS and _canon(m["text"]) not in _NUMERIC_KEYS:
                m["text"] += " " + p["text"]
                m["x0"], m["x1"] = min(m["x0"], p["x0"]), max(m["x1"], p["x1"])
                break
        else:
            merged.append(p)
    return merged


def _group_phrases(words, min_x):
    """Phrases on the first text line of a group row, right of ``min_x``."""
    # group names are words ("Standard", "Fast-Plus"); skip conditions like "VCC = 2.5 V"
    line = sorted(
        (w for w in words if w["x1"] > min_x - 25 and re.fullmatch(r"[A-Za-z][A-Za-z+\-−]{2,}", w["text"]) and w["text"].lower() not in {"to", "and", "for"}),
        key=lambda w: w["x0"],
    )
    out = []
    for w in line:
        if out and w["x0"] - out[-1]["x1"] < 6 and abs(w["top"] - out[-1]["top"]) < 3:
            out[-1] = {**out[-1], "text": out[-1]["text"] + " " + w["text"], "x1": w["x1"]}
        else:
            out.append(dict(w))
    return out


def _header_score(text_words) -> int:
    keys = {_canon(w) for w in text_words}
    keys |= {_canon(a + " " + b) for a, b in zip(text_words, text_words[1:])}
    keys.discard(None)
    spec = len(keys & _SPEC_KEYS)
    label = bool(keys & {"parameter", "symbol", "conditions"})
    unit = "unit" in keys
    if not spec or not (label or unit):
        return 0
    return spec + label + unit


def _section_title(page, table_top, page_no, last):
    """Nearest heading above the table; else a "Table N." caption; else a continuation."""
    above = page.crop((0, max(0, table_top - 90), page.width, table_top), strict=False)
    lines: dict[int, list] = {}
    for w in above.extract_words(x_tolerance=1.5, y_tolerance=2):
        lines.setdefault(round(w["top"] / 3), []).append(w)
    caption = None
    for _, ws in sorted(lines.items(), reverse=True):
        text = " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])).strip()
        low = text.lower()
        if len(text) < 90 and any(h in low for h in _SECTION_HINTS):
            text = re.sub(r"^\s*(table\s*)?[\d.]+\s*", "", text, flags=re.I)
            return text.rstrip(":").strip()
        if caption is None and re.match(r"^table\s*\d+[.:]", low):
            caption = re.sub(r"^table\s*\d+[.:]\s*", "", text, flags=re.I).strip()
    if caption:
        return caption
    if last and (page_no == last[1] or (page_no == last[1] + 1 and table_top < page.height * 0.3)):
        return last[0]
    return "Specifications"


def _guess_part(pdf) -> str | None:
    if not pdf.pages:
        return None
    words = pdf.pages[0].extract_words(extra_attrs=["size"])
    cands = [w for w in words if re.search(r"[A-Z]{2,}\d{2,}|\d{2,}[A-Z]{2,}", w["text"])]
    if not cands:
        return None
    best = max(cands, key=lambda w: (w["size"], -w["top"]))
    return best["text"].strip(",;:")


# ------------------------------------------------------------ the core ----


def _bands(table):
    """Row bands from the distinct horizontal lines, so merged cells don't swallow rows."""
    ys = sorted({round(c[1], 1) for c in table.cells} | {round(c[3], 1) for c in table.cells})
    bands = []
    for a, b in zip(ys, ys[1:]):
        if b - a > 2:
            bands.append((a, b))
    return bands


def _band_of(w, bands):
    mid = (w["top"] + w["bottom"]) / 2
    for i, (a, b) in enumerate(bands):
        if a - 0.5 <= mid <= b + 0.5:
            return i
    return None


def _join_words(ws):
    """Join words into text, keeping subscripts attached: V + small "IN" -> "VIN"."""
    if not ws:
        return ""
    ws = sorted(ws, key=lambda w: w["top"])
    lines: list[list[dict]] = []
    for w in ws:
        if lines:
            ref = max(lines[-1], key=lambda x: x.get("size", 0))
            if w["top"] < ref["top"] + 0.7 * (ref["bottom"] - ref["top"]):
                lines[-1].append(w)
                continue
        lines.append([w])
    out_lines = []
    for line in lines:
        line.sort(key=lambda w: w["x0"])
        big = max(w.get("size", 0) for w in line)
        text, prev = "", None
        for w in line:
            small = big and w.get("size", big) < 0.85 * big
            tight = prev is not None and w["x0"] - prev["x1"] < 1.2
            if prev is None:
                text = w["text"]
            elif small and tight:
                text += w["text"]
            else:
                text += " " + w["text"]
            prev = w
        out_lines.append(text)
    return " ".join(out_lines).translate(_DASHES).strip()


def _table_from(page, table, page_no, last) -> Table | None:
    bands = _bands(table)
    if len(bands) < 2:
        return None
    words = _words(page, table.bbox)
    if not words:
        return None
    for w in words:
        w["band"] = _band_of(w, bands)

    def band_words(i):
        return [w for w in words if w["band"] == i]

    # header row: best-scoring band among the first three
    def only_spec_keys(ws):
        return len(ws) >= 2 and all(_canon(w["text"]) in _NUMERIC_KEYS for w in ws)

    header_i, best = None, 0
    for i in range(min(3, len(bands))):
        ws = band_words(i)
        if i + 1 < len(bands) and only_spec_keys(band_words(i + 1)) and not only_spec_keys(ws):
            ws = ws + band_words(i + 1)  # "Symbol | Standard | Units" over "Min Max"
        sc = _header_score([w["text"] for w in ws])
        if sc > best:
            header_i, best = i, sc
    if header_i is None or best < 2:
        return None
    hdr_words = band_words(header_i)
    body_start = header_i + 1

    # Two-level headers: a group row ("Standard | Fast | Fast-Plus") over "Min Max Min Max".
    # The group row is either the band above the header or the header band itself
    # (when the Min/Max row comes right after it).
    groups = []
    if body_start < len(bands):
        sub = band_words(body_start)
        if sub and len(sub) >= 2 and all(_canon(w["text"]) in _NUMERIC_KEYS for w in sub):
            groups = _group_phrases([w for w in hdr_words if _canon(w["text"]) is None], min(x["x0"] for x in sub))
            hdr_words = [w for w in hdr_words if _canon(w["text"]) is not None or w["x1"] < min(x["x0"] for x in sub) - 20] + sub
            body_start += 1
    if not groups and header_i > 0:
        nums_here = [w for w in hdr_words if _canon(w["text"]) in _SPEC_KEYS]
        keys_here = [_canon(w["text"]) for w in nums_here]
        if len(keys_here) != len(set(keys_here)) and nums_here:  # repeated Min/Max -> grouped
            groups = _group_phrases(band_words(header_i - 1), min(w["x0"] for w in nums_here))

    anchors: list[_Anchor] = []
    for ph in _phrases(hdr_words):
        key = _canon(ph["text"])
        label = ph["text"]
        if key in _NUMERIC_KEYS and key != "unit" and groups:
            cx = (ph["x0"] + ph["x1"]) / 2
            left = [g for g in groups if g["x0"] - 25 <= cx] or groups
            g = max(left, key=lambda g: g["x0"])
            gname = re.sub(r"[^a-z0-9]+", "_", g["text"].lower()).strip("_")
            key, label = f"{gname}_{key}", f"{g['text']} {label}"
        numeric = (key or "").split("_")[-1] in _NUMERIC_KEYS
        anchors.append(_Anchor(key or "", label, ph["x0"], ph["x1"], numeric))

    num = [a for a in anchors if a.numeric]
    if not num:
        return None
    first_num_x = min(a.x0 for a in num)
    # labeled columns right of the numbers (a part number heading a thermal table, ...)
    for a in anchors:
        if not a.numeric and a.x0 >= first_num_x:
            a.numeric = True
            a.key = a.key or ("value" if not any(n.key == "value" for n in num) else _norm_label(a.label))
            num.append(a)

    # Left of the numbers: left-aligned text. Split it at the drawn cell edges.
    xs = sorted({round(c[0], 1) for c in table.cells})
    seg_edges = [x for x in xs if x < first_num_x - 6]
    if not seg_edges:
        seg_edges = [table.bbox[0]]
    segs = []
    for i, x0 in enumerate(seg_edges):
        x1 = seg_edges[i + 1] if i + 1 < len(seg_edges) else first_num_x
        if x1 - x0 > 4:
            segs.append(_Anchor("", "", x0, x1, False))
    # name segments from header phrases; a phrase spanning several segments names the last one
    for a in anchors:
        if a.numeric:
            continue
        covered = [sg for sg in segs if a.x0 < sg.x1 - 2 and a.x1 > sg.x0 + 2]
        if not covered:
            continue
        target = covered[-1] if len(covered) > 1 else covered[0]
        target.key = a.key or _norm_label(a.label)
        target.label = a.label

    def column_of(w):
        if w["x1"] > first_num_x - 2 or not segs:
            over = [(min(w["x1"], a.x1 + 3) - max(w["x0"], a.x0 - 3), a) for a in num]
            over = [o for o in over if o[0] > 0]
            if over:
                return max(over, key=lambda o: o[0])[1]
            cx = (w["x0"] + w["x1"]) / 2
            return min(num, key=lambda a: abs(a.cx - cx))
        cands = [sg for sg in segs if sg.x0 <= w["x0"] + 2]
        return cands[-1] if cands else segs[0]

    # Merged text cells spanning several bands: copy their words into every band they span.
    spans = []
    for c in table.cells:
        top, bottom = c[1], c[3]
        covered = [i for i, (a, b) in enumerate(bands) if a >= top - 1 and b <= bottom + 1]
        if len(covered) > 1:
            spans.append((c, covered))

    rows: dict[int, dict[int, list]] = {}
    for w in words:
        if w["band"] is None or w["band"] < body_start:
            continue
        col = column_of(w)
        targets = [w["band"]]
        spannable = not col.numeric or col.key.endswith("unit")
        for c, covered in (spans if spannable else []):
            if c[0] - 1 <= w["x0"] and w["x1"] <= c[2] + 1 and c[1] - 1 <= w["top"] and w["bottom"] <= c[3] + 1:
                targets = covered
                break
        for b in targets:
            rows.setdefault(b, {}).setdefault(id(col), []).append(w)
    if not rows:
        return None

    # name unlabeled text segments: short -> symbol, then parameter, conditions
    by_id = {id(a): a for a in segs + num}
    live = [sg for sg in segs if any(id(sg) in r for r in rows.values())]
    named = {sg.key for sg in live if sg.key}

    def avg_len(sg):
        vals = [_join_words(r[id(sg)]) for r in rows.values() if id(sg) in r]
        return statistics.mean(map(len, vals)) if vals else 0

    todo = [k for k in ("symbol", "parameter", "conditions") if k not in named]
    for sg in live:
        if sg.key:
            continue
        if "symbol" in todo and avg_len(sg) <= 8 and len(live) > 1:
            sg.key = "symbol"
            todo.remove("symbol")
        else:
            rest = [k for k in todo if k != "symbol"]
            sg.key = rest[0] if rest else "notes"
            if rest:
                todo.remove(rest[0])

    columns = [a.key for a in sorted(live + num, key=lambda a: a.x0)]
    specs: list[Spec] = []
    category, prev = None, None
    fields = set(Spec.__dataclass_fields__) - {"extra", "category"}
    for b in sorted(rows):
        rec = {}
        for cid, ws in rows[b].items():
            a = by_id[cid]
            rec[a.key] = (rec.get(a.key, "") + " " + _join_words(ws)).strip()
        if rec.get("unit"):
            rec["unit"] = re.sub(r"\(cid:\d+\)(?=[AsFHVWm]\b|[AsFHVW]$)", "µ", rec["unit"])
        num_vals = {a.key: rec.get(a.key) for a in num if rec.get(a.key) and a.key != "unit"}
        text_vals = {k: v for k, v in rec.items() if v and k not in {a.key for a in num}}
        if not num_vals:
            if len(text_vals) == 1 and next(iter(text_vals.values())).replace(" ", "").isupper():
                category = next(iter(text_vals.values()))
            elif prev is not None:  # wrapped continuation of the previous row's text
                for k, v in text_vals.items():
                    if k in fields:
                        setattr(prev, k, f"{getattr(prev, k) or ''} {v}".strip())
                    else:
                        prev.extra[k] = f"{prev.extra.get(k, '')} {v}".strip()
            continue
        param = rec.pop("parameter", "")
        same_as_prev = False
        if not param and prev is not None:
            param, same_as_prev = prev.parameter, True
        if not param:
            param = rec.get("symbol", "")
        kw = {k: v for k, v in rec.items() if v and k in fields and k != "parameter"}
        extra = {k: v for k, v in rec.items() if v and k not in fields}
        if same_as_prev and prev is not None:
            kw.setdefault("symbol", prev.symbol)
            kw.setdefault("unit", prev.unit)
        spec = Spec(parameter=param, category=category, extra=extra, **{k: v for k, v in kw.items() if v})
        specs.append(spec)
        prev = spec
    if not specs:
        return None

    section = _section_title(page, table.bbox[1], page_no, last)
    return Table(section, page_no, columns, specs)


def extract(path: str | Path, pages: list[int] | None = None) -> Datasheet:
    """Extract every spec table from a datasheet PDF.

    ``pages`` is an optional list of 1-based page numbers to look at.
    """
    path = Path(path)
    tables: list[Table] = []
    with pdfplumber.open(path) as pdf:
        last = None  # (section, page) of the previous spec table
        for i, page in enumerate(pdf.pages, start=1):
            if pages and i not in pages:
                continue
            for t in page.find_tables():
                try:
                    tbl = _table_from(page, t, i, last)
                except Exception:  # one odd table shouldn't sink the whole file
                    continue
                if tbl:
                    tables.append(tbl)
                    last = (tbl.section, i)
        return Datasheet(str(path.name), _guess_part(pdf), len(pdf.pages), tables)
