"""Build a small fake datasheet PDF at test time (real vendor PDFs can't be redistributed)."""

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GRID = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
)


def _p(text, style):
    return Paragraph(text, style)


@pytest.fixture(scope="session")
def fake_datasheet(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "XYZ1234.pdf"
    ss = getSampleStyleSheet()
    cell = ss["BodyText"].clone("cell", fontSize=8, leading=10)
    story = [
        Paragraph("XYZ1234 Low-Noise 300-mA LDO Regulator", ss["Title"]),
        Spacer(1, 12),
        Paragraph("6 Pin Functions", ss["Heading2"]),
        Table([["PIN", "NAME", "DESCRIPTION"], ["1", "IN", "Input supply"], ["2", "GND", "Ground"]], style=GRID),
        Spacer(1, 12),
        Paragraph("7.1 Absolute Maximum Ratings", ss["Heading2"]),
        Table(
            [
                ["", "MIN", "MAX", "UNIT"],
                ["Input voltage, VIN", "–0.3", "6.5", "V"],
                ["Junction temperature, TJ", "–40", "150", "°C"],
            ],
            colWidths=[200, 50, 50, 50],
            style=GRID,
        ),
        Spacer(1, 12),
        Paragraph("7.5 Electrical Characteristics", ss["Heading2"]),
        Table(
            [
                ["SYMBOL", "PARAMETER", "TEST CONDITIONS", "MIN", "TYP", "MAX", "UNIT"],
                ["POWER SUPPLY", "", "", "", "", "", ""],
                [_p("V<sub>IN</sub>", cell), "Input voltage range", "", "1.8", "", "5.5", "V"],
                [_p("I<sub>Q</sub>", cell), "Quiescent current", "IOUT = 0 mA", "", "35", "60", "µA"],
                [_p("V<sub>DO</sub>", cell), "Dropout voltage", "IOUT = 150 mA", "", "120", "", "mV"],
                ["", "", "IOUT = 300 mA", "", "250", "400", "mV"],
            ],
            colWidths=[50, 110, 110, 40, 40, 40, 40],
            style=TableStyle(list(GRID.getCommands()) + [("SPAN", (0, 1), (-1, 1)), ("SPAN", (0, 4), (0, 5)), ("SPAN", (1, 4), (1, 5))]),
        ),
        Spacer(1, 12),
        Paragraph("7.6 Timing Requirements", ss["Heading2"]),
        Table(
            [
                ["Symbol", "Parameter", "Standard", "", "Fast", "", "Units"],
                ["", "", "Min", "Max", "Min", "Max", ""],
                ["fSCL", "Clock frequency", "", "100", "", "400", "kHz"],
                ["tLOW", "Low period", "4.7", "", "1.3", "", "µs"],
            ],
            colWidths=[50, 110, 40, 40, 40, 40, 40],
            style=TableStyle(
                list(GRID.getCommands())
                + [("SPAN", (2, 0), (3, 0)), ("SPAN", (4, 0), (5, 0)), ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)), ("SPAN", (6, 0), (6, 1))]
            ),
        ),
    ]
    SimpleDocTemplate(str(path), pagesize=letter).build(story)
    return path
