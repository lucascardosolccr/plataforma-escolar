"""Planilha Excel (.xlsx) mínima, só com a biblioteca padrão.

Um .xlsx é um ZIP com alguns XML (Office Open XML). Gerar aqui evita uma
dependência nova (o projeto mantém quatro) e basta para tabelas: várias
abas, cabeçalho em negrito, números como números e texto como texto.

Texto que começa com =, +, - ou @ recebe um apóstrofo, como no CSV: sem isso
o Excel o executaria como fórmula (injeção de fórmula).
"""

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

_FORMULA_START = ("=", "+", "-", "@")


def _col(i):
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return name


def _cell(ref, value, style=0):
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>'
    if isinstance(value, bool):
        value = "Sim" if value else "Não"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    if isinstance(value, (date, datetime)):
        value = value.strftime("%d/%m/%Y")
    text = str(value)
    if text.startswith(_FORMULA_START):
        text = "'" + text
    return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet(rows):
    out = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(
            _cell(f"{_col(c)}{r}", v, style=1 if r == 1 else 0) for c, v in enumerate(row)
        )
        out.append(f'<row r="{r}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews>'
        f'<sheetData>{"".join(out)}</sheetData></worksheet>'
    )


def build(sheets):
    """``sheets``: lista de (nome da aba, linhas). A 1ª linha é o cabeçalho."""
    buf = io.BytesIO()
    names = []
    for name, _ in sheets:
        clean = "".join(ch for ch in name if ch not in '[]:*?/\\')[:31] or "Planilha"
        base, n = clean, 2
        while clean in names:
            clean = f"{base[:28]} {n}"
            n += 1
        names.append(clean)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + "</Types>"
        ))
        z.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ))
        z.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(
                f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, start=1)
            )
            + "</sheets></workbook>"
        ))
        z.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ))
        z.writestr("xl/styles.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            "</styleSheet>"
        ))
        for i, (_, rows) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet(rows))
    return buf.getvalue()
