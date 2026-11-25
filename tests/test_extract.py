import csv
import io
import json

import pytest

from datasheet2json import extract, parse_number
from datasheet2json.cli import main


@pytest.fixture(scope="module")
def ds(fake_datasheet):
    return extract(fake_datasheet)


def section(ds, name):
    return next(t for t in ds.tables if name.lower() in t.section.lower())


def test_part_number(ds):
    assert ds.part == "XYZ1234"


def test_pin_table_is_ignored(ds):
    assert not any("pin" in t.section.lower() for t in ds.tables)
    assert not any(s.parameter in ("IN", "GND") for s in ds.specs)


def test_absolute_max(ds):
    t = section(ds, "Absolute Maximum")
    vin = t.specs[0]
    assert vin.parameter == "Input voltage, VIN"
    assert (vin.min, vin.max, vin.unit) == ("-0.3", "6.5", "V")  # en dash normalised
    assert vin.numbers() == {"min": -0.3, "max": 6.5}


def test_electrical_characteristics(ds):
    t = section(ds, "Electrical Characteristics")
    by_param = {}
    for s in t.specs:
        by_param.setdefault(s.parameter, []).append(s)
    iq = by_param["Quiescent current"][0]
    assert iq.symbol == "IQ"  # subscript joined
    assert (iq.typ, iq.max, iq.unit) == ("35", "60", "µA")
    assert iq.conditions == "IOUT = 0 mA"
    assert iq.category == "POWER SUPPLY"


def test_merged_cells_fill_both_rows(ds):
    t = section(ds, "Electrical Characteristics")
    drop = [s for s in t.specs if s.parameter == "Dropout voltage"]
    assert len(drop) == 2
    assert {s.conditions for s in drop} == {"IOUT = 150 mA", "IOUT = 300 mA"}
    assert all(s.symbol == "VDO" for s in drop)
    assert drop[1].max == "400"


def test_two_level_header(ds):
    t = section(ds, "Timing")
    assert "standard_min" in t.columns and "fast_max" in t.columns
    f = next(s for s in t.specs if s.symbol == "fSCL")
    assert f.extra == {"standard_max": "100", "fast_max": "400"}
    assert f.numbers() == {"standard_max": 100.0, "fast_max": 400.0}


def test_find(ds):
    hits = ds.find("quiescent")
    assert len(hits) == 1 and hits[0][1].typ == "35"


@pytest.mark.parametrize(
    "text, expected",
    [("-0.3", -0.3), ("–0.3", -0.3), ("1,000,000", 1e6), ("5.5V", 5.5), ("±2000", 2000), ("VCC + 0.3", None), ("", None)],
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_cli_json(fake_datasheet, capsys):
    main([str(fake_datasheet)])
    data = json.loads(capsys.readouterr().out)
    assert data["part"] == "XYZ1234"
    assert len(data["tables"]) == 3


def test_cli_find_csv(fake_datasheet, capsys):
    main([str(fake_datasheet), "--find", "dropout", "--csv"])
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert [r["conditions"] for r in rows] == ["IOUT = 150 mA", "IOUT = 300 mA"]
