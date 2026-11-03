from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SHARED_STRINGS = "xl/sharedStrings.xml"
FIRST_SHEET = "xl/worksheets/sheet1.xml"

Row = list[str | None]


def read_rows(data: bytes) -> list[Row]:
    book = zipfile.ZipFile(io.BytesIO(data))
    shared = _shared_strings(book)
    return [_row(row, shared) for row in ET.fromstring(book.read(FIRST_SHEET)).iter(f"{NS}row")]


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if SHARED_STRINGS not in book.namelist():
        return []
    root = ET.fromstring(book.read(SHARED_STRINGS))
    return ["".join(t.text or "" for t in si.iter(f"{NS}t")) for si in root.iter(f"{NS}si")]


def _row(row: ET.Element, shared: list[str]) -> Row:
    cells: dict[int, str | None] = {}
    for cell in row.iter(f"{NS}c"):
        index = _column_index(cell.get("r", "A"))
        value, inline = cell.find(f"{NS}v"), cell.find(f"{NS}is")
        if value is not None and value.text is not None:
            cells[index] = shared[int(value.text)] if cell.get("t") == "s" else value.text
        elif inline is not None:
            cells[index] = "".join(t.text or "" for t in inline.iter(f"{NS}t"))
    width = max(cells) + 1 if cells else 0
    return [cells.get(i) for i in range(width)]


def _column_index(ref: str) -> int:
    index = 0
    for letter in re.match(r"[A-Z]+", ref).group():
        index = index * 26 + ord(letter) - 64
    return index - 1
