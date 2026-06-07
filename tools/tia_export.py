"""
tia_export.py — TIA Portal Projektübersicht nach Excel exportieren

Liest aus dem geöffneten TIA Portal Projekt:
  - Alle PLC-Bausteine (mit Typ, Nummer, Sprache, Ordnerpfad)
  - Alle PLC-Tag-Tabellen (mit Tags, Typ, Adresse, Kommentar)
  - Alle DB-Variablen (aus XML-Export, mit Typ und Kommentar)
  - Alle HMI-Tags (falls HMI bereits vorhanden)

Ausgabe: Excel-Datei mit vier Sheets — bereit für HMI-Planung.
Spalten Hi/Lo/Einheit/HMI bleiben leer → manuell ausfüllen.

Voraussetzungen:
  pip install openpyxl
  TIA Portal muss offen sein, Projekt muss geladen sein.

Start:
  .venv\\Scripts\\python.exe tia_export.py
  .venv\\Scripts\\python.exe tia_export.py --output C:\\tia-mcp\\export\\meinprojekt.xlsx
  .venv\\Scripts\\python.exe tia_export.py --plc PLC_2 --hmi HMI_1
"""

import sys
import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

# openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# tia.py im selben Verzeichnis
sys.path.insert(0, str(Path(__file__).parent))
import tia

# ── Konstanten ─────────────────────────────────────────────────────────────────

DEFAULT_OUTPUT  = r"C:\tia-mcp\export\tia_export.xlsx"
TEMP_EXPORT_DIR = r"C:\tia-mcp\export\temp_xml"

# Farben
COLOR_HEADER      = "1F4E79"   # Dunkelblau
COLOR_SHEET_TAB   = "2E75B6"   # Mittelblau
COLOR_ALT_ROW     = "DEEAF1"   # Hellblau (alternierende Zeilen)
COLOR_EMPTY_HINT  = "FFF2CC"   # Gelb — Spalten die manuell gefüllt werden sollen
COLOR_WHITE       = "FFFFFF"

FONT_HEADER = Font(name="Arial", bold=True, color="FFFFFF", size=10)
FONT_NORMAL = Font(name="Arial", size=10)
FONT_HINT   = Font(name="Arial", size=9, italic=True, color="7F7F7F")

# ── Excel-Hilfsfunktionen ──────────────────────────────────────────────────────

def _header_row(ws, cols: list[tuple[str, int]], color=COLOR_HEADER):
    """Kopfzeile schreiben und formatieren. cols = [(Name, Breite), ...]"""
    fill   = PatternFill("solid", start_color=color)
    border = Border(
        bottom=Side(style="thin", color="FFFFFF"),
        right= Side(style="thin", color="FFFFFF"),
    )
    for i, (name, width) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=i, value=name)
        cell.font      = FONT_HEADER
        cell.fill      = fill
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
        cell.border    = border
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[1].height = 18
    ws.freeze_panes = "A2"

def _write_rows(ws, rows: list[list], hint_cols: set[int] = None):
    """Datenzeilen schreiben mit alternierenden Farben."""
    hint_cols = hint_cols or set()
    fill_alt  = PatternFill("solid", start_color=COLOR_ALT_ROW)
    fill_hint = PatternFill("solid", start_color=COLOR_EMPTY_HINT)
    fill_none = PatternFill(fill_type=None)

    for r_idx, row in enumerate(rows, 2):
        is_alt = (r_idx % 2 == 0)
        for c_idx, value in enumerate(row, 1):
            cell       = ws.cell(row=r_idx, column=c_idx, value=value)
            cell.font  = FONT_NORMAL
            cell.alignment = Alignment(vertical="center")
            if c_idx in hint_cols:
                cell.fill = fill_hint
            elif is_alt:
                cell.fill = fill_alt
            else:
                cell.fill = fill_none

def _info_sheet(wb, project_name, plc_name, hmi_name, counts):
    """Info-Sheet als erstes Sheet."""
    ws = wb.active
    ws.title = "Info"
    ws.sheet_properties.tabColor = "375623"

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 45

    def row(label, value, bold=False):
        r = ws.max_row + 1
        a = ws.cell(row=r, column=1, value=label)
        b = ws.cell(row=r, column=2, value=value)
        a.font = Font(name="Arial", bold=bold, size=10)
        b.font = Font(name="Arial", bold=bold, size=10)
        a.fill = PatternFill("solid", start_color="D9E1F2")

    ws.append([])
    row("TIA Portal MCP Export", "", bold=True)
    row("Exportdatum",   datetime.now().strftime("%d.%m.%Y %H:%M"))
    row("Projekt",       project_name)
    row("PLC",           plc_name or "—")
    row("HMI",           hmi_name or "—")
    ws.append([])
    row("Bausteine",     counts.get("blocks", 0))
    row("PLC-Tags",      counts.get("plc_tags", 0))
    row("DB-Variablen",  counts.get("db_vars", 0))
    row("HMI-Tags",      counts.get("hmi_tags", 0))
    ws.append([])
    hint = ws.cell(row=ws.max_row + 1, column=1,
                   value="Gelb markierte Spalten → manuell ausfüllen")
    hint.font = FONT_HINT
    hint2 = ws.cell(row=ws.max_row, column=2,
                    value="(Hi-Limit, Lo-Limit, Einheit, ins HMI?)")
    hint2.font = FONT_HINT

# ── TIA-Daten lesen ────────────────────────────────────────────────────────────

def _read_blocks(plc_name: str) -> list[dict]:
    """Alle Bausteine iterativ lesen."""
    code = """
plc = find_software(plc_name, "PlcSoftware")
if not plc:
    result = []
else:
    stack = [(plc.BlockGroup, "")]
    result = []
    while stack:
        group, path = stack.pop()
        for block in group.Blocks:
            lang = str(getattr(block, "ProgrammingLanguage", "?"))
            result.append({
                "name":   block.Name,
                "number": getattr(block, "Number", None),
                "type":   type(block).__name__.replace("Plc","").replace("Block",""),
                "lang":   lang,
                "path":   path or "/",
            })
        for sub in group.Groups:
            stack.append((sub, (path + "/" + sub.Name).lstrip("/")))
""".replace("plc_name", repr(plc_name))
    r = tia.execute_openness(code, mode="read")
    return r.get("result") or []


def _read_plc_tags(plc_name: str) -> list[dict]:
    """Alle PLC-Tag-Tabellen lesen."""
    code = """
plc = find_software(plc_name, "PlcSoftware")
if not plc:
    result = []
else:
    result = []
    for table in plc.TagTableGroup.TagTables:
        for tag in table.Tags:
            comment = ""
            try:
                items = tag.Comment.Items
                if items and items.Count > 0:
                    comment = str(items[0].Text)
            except Exception:
                pass
            result.append({
                "table":   table.Name,
                "name":    tag.Name,
                "type":    str(getattr(tag, "DataTypeName", "?")),
                "address": str(getattr(tag, "LogicalAddress", "")),
                "comment": comment,
            })
""".replace("plc_name", repr(plc_name))
    r = tia.execute_openness(code, mode="read")
    return r.get("result") or []


def _read_db_vars(plc_name: str, export_dir: str) -> list[dict]:
    """
    Alle DBs exportieren und DB-Variablen aus XML parsen.
    Gibt Liste mit DB-Name, Variable, Typ, Startadresse, Kommentar zurück.
    """
    # 1. DB-Namen sammeln
    code = """
plc = find_software(plc_name, "PlcSoftware")
if not plc:
    result = []
else:
    result = []
    stack = [(plc.BlockGroup, "")]
    while stack:
        group, path = stack.pop()
        for block in group.Blocks:
            if "Db" in type(block).__name__ or "DataBlock" in type(block).__name__:
                result.append(block.Name)
        for sub in group.Groups:
            stack.append((sub, path))
""".replace("plc_name", repr(plc_name))
    r   = tia.execute_openness(code, mode="read")
    dbs = r.get("result") or []

    if not dbs:
        return []

    # 2. Jeden DB exportieren und parsen
    Path(export_dir).mkdir(parents=True, exist_ok=True)
    all_vars = []

    for db_name in dbs:
        try:
            res = tia.export_plc_block(plc_name, db_name, export_dir)
            xml_path = res.get("xml_path")
            if xml_path and Path(xml_path).exists():
                vars_ = _parse_db_xml(db_name, xml_path)
                all_vars.extend(vars_)
        except Exception as e:
            print(f"  ⚠  DB '{db_name}' konnte nicht exportiert werden: {e}")

    return all_vars


def _parse_db_xml(db_name: str, xml_path: str) -> list[dict]:
    """TIA-DB-XML parsen → Variablenliste."""
    vars_ = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Namespace ermitteln
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        def tag(name): return f"{ns}{name}"

        # Alle Member-Elemente suchen (DB-Variablen)
        for member in root.iter(tag("Member")):
            name    = member.get("Name", "")
            dtype   = member.get("Datatype", "")
            version = member.get("Version", "")
            # Startoffset aus AttributeList
            offset  = ""
            comment = ""
            attr    = member.find(tag("AttributeList"))
            if attr is not None:
                off_el = attr.find(tag("StartValue"))
                if off_el is not None:
                    offset = off_el.text or ""
            # Kommentar
            comment_el = member.find(f".//{tag('MultiLanguageText')}")
            if comment_el is not None:
                comment = comment_el.text or ""

            if name and dtype:
                vars_.append({
                    "db":      db_name,
                    "name":    name,
                    "type":    dtype,
                    "version": version,
                    "comment": comment.strip(),
                })
    except Exception as e:
        print(f"  ⚠  XML-Parse-Fehler {db_name}: {e}")
    return vars_


def _read_hmi_tags(hmi_name: str) -> list[dict]:
    """HMI-Tags lesen — leer falls HMI noch nicht existiert."""
    if not hmi_name:
        return []
    try:
        r = tia.list_hmi_tags(hmi_name)
        return r.get("tags") or []
    except Exception:
        return []

# ── Excel schreiben ────────────────────────────────────────────────────────────

def _sheet_blocks(wb, blocks: list[dict]):
    ws = wb.create_sheet("Bausteine")
    ws.sheet_properties.tabColor = COLOR_SHEET_TAB
    cols = [
        ("Name",        28),
        ("Typ",         10),
        ("Nummer",       9),
        ("Sprache",     14),
        ("Ordner",      35),
    ]
    _header_row(ws, cols)
    rows = [
        [b["name"], b["type"], b["number"], b["lang"], b["path"]]
        for b in sorted(blocks, key=lambda x: (x["path"], x["name"]))
    ]
    _write_rows(ws, rows)
    ws.auto_filter.ref = f"A1:E{len(rows)+1}"


def _sheet_plc_tags(wb, tags: list[dict]):
    ws = wb.create_sheet("PLC_Tags")
    ws.sheet_properties.tabColor = COLOR_SHEET_TAB
    cols = [
        ("Tag-Tabelle",  22),
        ("Name",         30),
        ("Datentyp",     14),
        ("Adresse",      14),
        ("Kommentar",    40),
        ("Hi-Limit",     12),   # manuell
        ("Lo-Limit",     12),   # manuell
        ("Einheit",      12),   # manuell
        ("Ins HMI?",     10),   # manuell
    ]
    _header_row(ws, cols)
    rows = [
        [t["table"], t["name"], t["type"], t["address"], t["comment"],
         None, None, None, None]
        for t in tags
    ]
    # Spalten 6-9 gelb (Hi, Lo, Einheit, Ins HMI)
    _write_rows(ws, rows, hint_cols={6, 7, 8, 9})
    ws.auto_filter.ref = f"A1:I{len(rows)+1}"


def _sheet_db_vars(wb, vars_: list[dict]):
    ws = wb.create_sheet("DB_Variablen")
    ws.sheet_properties.tabColor = COLOR_SHEET_TAB
    cols = [
        ("DB",           22),
        ("Variable",     30),
        ("Datentyp",     18),
        ("Kommentar",    40),
        ("Hi-Limit",     12),   # manuell
        ("Lo-Limit",     12),   # manuell
        ("Einheit",      12),   # manuell
        ("Ins HMI?",     10),   # manuell
        ("HMI-Tagname",  28),   # manuell / generiert
    ]
    _header_row(ws, cols)
    rows = [
        [v["db"], v["name"], v["type"], v["comment"],
         None, None, None, None, None]
        for v in vars_
    ]
    _write_rows(ws, rows, hint_cols={5, 6, 7, 8, 9})
    ws.auto_filter.ref = f"A1:I{len(rows)+1}"


def _sheet_hmi_tags(wb, tags: list[dict]):
    ws = wb.create_sheet("HMI_Tags")
    ws.sheet_properties.tabColor = COLOR_SHEET_TAB
    if not tags:
        ws["A1"] = "Noch keine HMI-Tags vorhanden — wird nach HMI-Erstellung befüllt."
        ws["A1"].font = FONT_HINT
        ws.column_dimensions["A"].width = 60
        return
    cols = [
        ("Tag-Tabelle",  22),
        ("Name",         30),
        ("Datentyp",     14),
        ("Hi-Limit",     12),
        ("Lo-Limit",     12),
        ("Archiv",       10),
    ]
    _header_row(ws, cols)
    rows = [
        [t.get("table",""), t.get("name",""), t.get("type",""),
         t.get("high",""), t.get("low",""), t.get("archive","")]
        for t in tags
    ]
    _write_rows(ws, rows)
    ws.auto_filter.ref = f"A1:F{len(rows)+1}"


def _sheet_screens(wb):
    """Leeres Screen-Planungs-Sheet."""
    ws = wb.create_sheet("Screens_Planung")
    ws.sheet_properties.tabColor = "7030A0"
    cols = [
        ("Screenname",    25),
        ("Vorlage",       18),
        ("Titel",         30),
        ("Zugeordnete DBs", 35),
        ("Auflösung",     14),
        ("Bemerkung",     35),
    ]
    _header_row(ws, cols, color="7030A0")
    # Hinweiszeile
    hints = [
        ["Startbild",          "Start",    "Anlage XY",       "",          "1280x1024", "Hauptnavigation"],
        ["Antriebe_Uebersicht","Uebersicht","Antriebe",       "DB_Motor*", "1280x1024", ""],
        ["Motor1",             "Antrieb",  "Motor 1",         "DB_Motor1", "1280x1024", ""],
    ]
    fill_hint = PatternFill("solid", start_color=COLOR_EMPTY_HINT)
    for r_idx, row in enumerate(hints, 2):
        for c_idx, val in enumerate(row, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = Font(name="Arial", size=10, italic=True, color="7F7F7F")
            cell.fill = fill_hint
    note = ws.cell(row=ws.max_row + 2, column=1,
                   value="↑ Beispielzeilen — ersetzen oder ergänzen")
    note.font = FONT_HINT

# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TIA Portal → Excel Export")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Ausgabepfad (Standard: {DEFAULT_OUTPUT})")
    parser.add_argument("--plc",    default="PLC_1",
                        help="DeviceItem-Name der SPS (Standard: PLC_1)")
    parser.add_argument("--hmi",    default="",
                        help="DeviceItem-Name des HMI (leer = kein HMI)")
    parser.add_argument("--no-db-export", action="store_true",
                        help="DB-Variablen-Export überspringen (schneller)")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("═" * 60)
    print("  TIA Portal → Excel Export")
    print("═" * 60)

    # ── TIA verbinden ──────────────────────────────────────────────────────────
    print("\n[1/6] TIA Portal verbinden ...")
    tia.setup()
    tia.connect_portal("attach")
    proj_info = tia.attach_project()
    project_name = proj_info.get("project", "Unbekannt")
    print(f"      Projekt: {project_name}")

    # ── Bausteine lesen ────────────────────────────────────────────────────────
    print(f"\n[2/6] Bausteine lesen ({args.plc}) ...")
    blocks = _read_blocks(args.plc)
    print(f"      {len(blocks)} Bausteine gefunden")

    # ── PLC-Tags lesen ─────────────────────────────────────────────────────────
    print(f"\n[3/6] PLC-Tags lesen ...")
    plc_tags = _read_plc_tags(args.plc)
    print(f"      {len(plc_tags)} Tags gefunden")

    # ── DB-Variablen lesen ─────────────────────────────────────────────────────
    db_vars = []
    if not args.no_db_export:
        print(f"\n[4/6] DB-Variablen exportieren und lesen ...")
        db_vars = _read_db_vars(args.plc, TEMP_EXPORT_DIR)
        print(f"      {len(db_vars)} DB-Variablen gefunden")
    else:
        print(f"\n[4/6] DB-Export übersprungen (--no-db-export)")

    # ── HMI-Tags lesen ─────────────────────────────────────────────────────────
    print(f"\n[5/6] HMI-Tags lesen ({args.hmi or 'kein HMI angegeben'}) ...")
    hmi_tags = _read_hmi_tags(args.hmi)
    print(f"      {len(hmi_tags)} HMI-Tags gefunden")

    # ── Excel schreiben ────────────────────────────────────────────────────────
    print(f"\n[6/6] Excel schreiben → {output_path} ...")
    wb = Workbook()

    counts = {
        "blocks":   len(blocks),
        "plc_tags": len(plc_tags),
        "db_vars":  len(db_vars),
        "hmi_tags": len(hmi_tags),
    }
    _info_sheet(wb, project_name, args.plc, args.hmi or None, counts)
    _sheet_blocks(wb, blocks)
    _sheet_plc_tags(wb, plc_tags)
    _sheet_db_vars(wb, db_vars)
    _sheet_hmi_tags(wb, hmi_tags)
    _sheet_screens(wb)

    wb.save(str(output_path))
    tia.teardown()

    print("\n" + "═" * 60)
    print(f"  Fertig: {output_path}")
    print(f"  Bausteine:     {counts['blocks']}")
    print(f"  PLC-Tags:      {counts['plc_tags']}")
    print(f"  DB-Variablen:  {counts['db_vars']}")
    print(f"  HMI-Tags:      {counts['hmi_tags']}")
    print("═" * 60)
    print("\n  Nächster Schritt:")
    print("  → Sheet 'DB_Variablen': Hi/Lo-Limits und Einheiten eintragen")
    print("  → Sheet 'Screens_Planung': gewünschte Screens definieren")
    print("  → 'Ins HMI?' Spalte: 'ja' für relevante Tags eintragen")


if __name__ == "__main__":
    main()
