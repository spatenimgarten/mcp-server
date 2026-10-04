#!/usr/bin/env python3
"""
json2vorlage.py - erzeugt eine WinCC-Unified-Berichtsvorlage (.xlsx) aus einer
Offline-Konfigurationsdatei (.json) des Bericht-Controls.

Jede Variable aus der JSON wird untereinander eingetragen:
    Spalte A = Variablenname, Spalte B = Wert (Einzelwert-Segment)
Oben im Blatt stehen Titel und "Erstellt am:" (Zeitstempel von @Heartbeat, also der
Moment der Berichtserzeugung), in der Druck-Kopfzeile Titel sowie Datum/Uhrzeit.
Mit --quality wird zu jedem Wert der Qualitaetscode ausgegeben (z.B. BAD bei fehlender
Verbindung - sonst steht dort einfach 0).

Basis-Datei: eine einmal mit dem Excel-Add-in angelegte .xlsx, die mindestens ein
Einzelwert-Segment mit einer Variable enthaelt (z.B. test.xlsx). Daraus werden die
Add-in-Verknuepfung und die Segment-Konfiguration uebernommen.

Beispiele:
    python json2vorlage.py "test (1).json"
    python json2vorlage.py "test (1).json" --base test.xlsx --out Bericht.xlsx --title "Linie 1"
    python json2vorlage.py "test (1).json" --system           # auch @System-Tags
    python json2vorlage.py "test (1).json" --filter "^Test_"  # nur passende Namen
    python json2vorlage.py "test (1).json" --list             # nur anzeigen
    python json2vorlage.py anlage.json --tags-xlsx HMITags.xlsx --tables "SPS_*"   # nur bestimmte Tabellen
    python json2vorlage.py anlage.json --tags-xlsx HMITags.xlsx --list-tables      # Tabellen anzeigen
    python json2vorlage.py anlage.json --tags-xlsx HMITags.xlsx    # Tabellen aus tabellen.txt neben dem Skript
"""
import argparse
import copy
import fnmatch
import html
import json
import re
import socket
import sys
import uuid
import zipfile
from pathlib import Path

PROP_RE = r'(<we:property name="sheet_configurations" value=")([^"]*)(")'
REAL_TYPES = {"Real", "LReal", "Float", "Double"}


# ---------------------------------------------------------------- JSON lesen --
def read_tags(json_path, include_system=False, name_filter=None):
    """Liefert [(voller_name, kurzname, datentyp)] aus der Tag-Option der Offline-JSON."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8-sig"))
    tag_opt = next((o for o in data["options"].values()
                    if o["option"]["name"] == "Tag.Option_Name"), None)
    if tag_opt is None:
        sys.exit("Keine Tag-Option in der JSON gefunden.")
    lists = tag_opt["indicatorLists"]
    items = lists.get("notype", {}).get("items") or []

    def expand(it, depth=0):
        """Strukturen (UDT/Struct) rekursiv in ihre Elemente aufloesen.
        Die Elemente stehen in der Unterliste 'tag-<voller Name>'."""
        full = it.get("name") or it.get("id")
        if it.get("hasChildren") or it.get("datatype") == "Struct":
            sub = (lists.get(f"tag-{full}") or {}).get("items")
            if sub and depth < 20:
                # Array-Indizes numerisch sortieren ([1] vor [10]); die JSON sortiert alphabetisch
                if it.get("datatype") == "Array":
                    sub = sorted(sub, key=lambda c: [int(x) if x.isdigit() else x
                                                     for x in re.split(r"(\d+)", c.get("name", ""))])
                for child in sub:
                    yield from expand(child, depth + 1)
            else:
                print(f"Hinweis: Struktur ohne Elemente in der JSON uebersprungen: {full}")
            return
        yield it

    tags, seen = [], set()
    for top in items:
        top_short = (top.get("name") or "").split("::", 1)[-1]
        if not include_system and (top_short.startswith("@") or top_short in {
                "MemoryLimitAlarm", "MemoryLimitWarning", "UPSSTriggerTag", "UnsupportedClientVersion"}):
            continue
        for it in expand(top):
            full = it.get("name") or it.get("id")
            if not full or full in seen:
                continue
            short = full.split("::", 1)[-1]
            if name_filter and not re.search(name_filter, short):
                continue
            if it.get("datatype") in (None, "", "Unknown"):
                print(f"Hinweis: Datentyp unbekannt (Array?), uebersprungen: {full}")
                continue
            seen.add(full)
            tags.append((full, short, it.get("datatype", "")))
    return tags


def find_heartbeat(json_path):
    """Vollen Namen von @Heartbeat aus der JSON holen (z.B. 'HMI_RT_1::@Heartbeat')."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8-sig"))
    for o in data["options"].values():
        for lst in o["indicatorLists"].values():
            for it in (lst or {}).get("items") or []:
                if (it.get("name") or "").endswith("::@Heartbeat"):
                    return it["name"]
    return None


def read_tag_tables(xlsx_path):
    """TIA-Variablenexport (HMITags.xlsx) lesen -> {Variablenname: Tabellenpfad}.
    Ohne Zusatzpakete (nur zipfile/xml), damit das Skript an der Anlage ohne pip laeuft."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    z = zipfile.ZipFile(xlsx_path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    sheets = {sh.get("name"): sh.get(f"{{{ns['r']}}}id") for sh in wb.find("m:sheets", ns)}
    rid = sheets.get("Hmi Tags") or next(iter(sheets.values()))
    target = next(r.get("Target") for r in rels if r.get("Id") == rid)
    sheet = ET.fromstring(z.read("xl/" + target.lstrip("/").removeprefix("xl/")))

    def cell_value(c):
        v = c.find("m:v", ns)
        if c.get("t") == "s" and v is not None:
            return shared[int(v.text)]
        if c.get("t") == "inlineStr":
            return "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
        return v.text if v is not None else ""

    def col(ref):
        return re.match(r"[A-Z]+", ref).group(0)

    rows = sheet.find("m:sheetData", ns).findall("m:row", ns)
    header = {col(c.get("r")): cell_value(c) for c in rows[0].findall("m:c", ns)}
    by_name = {v: k for k, v in header.items()}
    if "Name" not in by_name or "Path" not in by_name:
        sys.exit(f"{xlsx_path}: Spalten 'Name' und 'Path' nicht gefunden (TIA-Export der HMI-Variablen?).")
    result = {}
    for r in rows[1:]:
        cells = {col(c.get("r")): cell_value(c) for c in r.findall("m:c", ns)}
        name = cells.get(by_name["Name"], "")
        if name:
            result[name] = cells.get(by_name["Path"], "")
    return result


def table_filter(xlsx_path, tables=None):
    """Erlaubte Variablen (oberste Ebene) aus dem Export, optional nur bestimmte Tabellen.
    tables: Kommaliste, Platzhalter erlaubt (SPS_*); verglichen mit vollem Pfad und letztem Teil."""
    tag_tables = read_tag_tables(xlsx_path)
    if not tables:
        return set(tag_tables), tag_tables
    pats = [t.strip() for t in tables.split(",") if t.strip()]

    def match(path):
        last = re.split(r"[\\/]", path)[-1]
        return any(fnmatch.fnmatchcase(path, pt) or fnmatch.fnmatchcase(last, pt) for pt in pats)
    allowed = {n for n, pth in tag_tables.items() if match(pth)}
    return allowed, tag_tables


DEFAULT_TABLES_FILE = "tabellen.txt"


def read_tables_file(path):
    """Tabellennamen aus Textdatei: eine pro Zeile, '#' = Kommentar, Platzhalter erlaubt."""
    names = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    if not names:
        sys.exit(f"{path}: keine Tabellennamen gefunden.")
    return ",".join(names)


def mcp_call(tool, port=47823, **args):
    """Tool des laufenden TIA-MCP-Servers aufrufen (lokaler RPC-Port der Primaer-Instanz)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=600) as sock:
            sock.sendall((json.dumps({"tool": tool, "args": args}) + "\n").encode())
            r = json.loads(sock.makefile("rb").readline())
    except OSError as e:
        sys.exit(f"MCP-Server nicht erreichbar (127.0.0.1:{port}): {e}")
    if not r["ok"]:
        sys.exit(f"MCP-Fehler bei {tool}: {r['error']}")
    return r["result"]


def load_usage(device, usage_json=None):
    """Verwendung der Variablen: aus Datei (--usage-json) oder live vom MCP-Server."""
    if usage_json:
        return json.loads(Path(usage_json).read_text(encoding="utf-8"))
    status = mcp_call("get_session_status")
    if not status.get("project_open") and not status.get("auto_reconnect"):
        mcp_call("connect_portal")
        mcp_call("attach_project")
    return mcp_call("list_hmi_tag_usage", device_name=device)


def usage_for(short, usages):
    """Fundstellen fuer einen aufgeloesten Namen. Treffer, wenn die Referenz genau der Name ist,
    ein uebergeordnetes Element (ganzer UDT, z.B. an ein Faceplate) oder ein Unterelement."""
    hits = []
    for ref, where in usages.items():
        if ref == short or short.startswith(ref + ".") or short.startswith(ref + "[") \
                or ref.startswith(short + ".") or ref.startswith(short + "["):
            hits.extend(where)
    return sorted(set(hits))


# ------------------------------------------------------------- XML-Helfer --
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def dumps(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def text_cell(ref, text, style=0):
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{esc(text)}</t></is></c>'


# Stil-Indizes, die patch_styles anlegt
ST_DEFAULT, ST_BOLD, ST_TITLE, ST_DATETIME, ST_REAL, ST_HIDDEN, ST_QUALITY = 0, 1, 2, 3, 4, 5, 6


def patch_styles(styles):
    """Ergaenzt fett/Titel/Datum/0,0 - nur fuer die vom Add-in erzeugte Standard-styles.xml."""
    if 'cellXfs count="1"' not in styles:
        print("Hinweis: styles.xml der Basis ist nicht Standard - Formatierung wird uebersprungen.")
        return styles, False
    font_close = styles.index("</fonts>")
    base_font = re.search(r"<font>(.*?)</font>", styles).group(1)
    styles = (styles[:font_close]
              + f"<font><b/>{base_font}</font>"
              + "<font><b/>" + re.sub(r'<sz val="[^"]+"/>', '<sz val="14"/>', base_font) + "</font>"
              + styles[font_close:])
    styles = re.sub(r'<fonts count="\d+"', lambda m: f'<fonts count="{styles.count("<font>")}"', styles, count=1)
    numfmts = ('<numFmts count="4"><numFmt numFmtId="164" formatCode="dd/mm/yyyy\\ hh:mm:ss"/>'
               '<numFmt numFmtId="165" formatCode="0.0"/>'
               '<numFmt numFmtId="166" formatCode=";;;"/>'
               '<numFmt numFmtId="167" formatCode="[&gt;=192]&quot;GOOD (&quot;0&quot;)&quot;;'
               '[&lt;64]&quot;BAD (&quot;0&quot;)&quot;;&quot;UNCERTAIN (&quot;0&quot;)&quot;"/></numFmts>')
    if "<numFmts" not in styles:
        styles = styles.replace("<fonts ", numfmts + "<fonts ", 1)
    nfont = styles.count("<font>")
    styles = re.sub(
        r'<cellXfs count="1">(<xf [^>]*/>)</cellXfs>',
        lambda m: '<cellXfs count="7">' + m.group(1)
        + f'<xf numFmtId="0" fontId="{nfont - 2}" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        + f'<xf numFmtId="0" fontId="{nfont - 1}" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        + '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left"/></xf>'
        + '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        + '<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        + '<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left"/></xf></cellXfs>',
        styles, count=1)
    return styles, True


# ------------------------------------------------------------ Vorlage bauen --
def build(tags, base, out, sheet_name, title, first_row, heartbeat=None, quality=False, usage=None):
    zin = zipfile.ZipFile(base)
    names = zin.namelist()
    if "xl/webextensions/webextension1.xml" not in names:
        sys.exit("Basis-Datei enthaelt keine Add-in-Daten (xl/webextensions/webextension1.xml).")

    wx = zin.read("xl/webextensions/webextension1.xml").decode("utf-8")
    m = re.search(PROP_RE, wx)
    if not m:
        sys.exit("Basis-Datei enthaelt keine Segmente (sheet_configurations).")
    cfg = json.loads(html.unescape(m.group(2)))
    sample = next((g for g in cfg.values()
                   if g.get("indicators") and g["indicators"][0].get("type") == "Tag"), None)
    if sample is None:
        sys.exit("Basis-Datei braucht mindestens ein Einzelwert-Segment mit einer Variable (Tag).")

    # Lokale Einzelwert-Konfiguration (wie vom Add-in angelegt): id = internalId des Elements
    def local_config(ind, timestamp="noLabel", qual="noLabel"):
        return {"id": ind["internalId"], "name": ind["name"], "configPath": "singleConfigDescription",
                "captions": "noLabel", "timestampLabel": timestamp, "indicatorLabel": "noLabel",
                "qualityCodeLabel": qual, "valueList": {"id": "none", "type": "Text"},
                "useAsLocal": False, "type": "TagSingleConfiguration", "isLocal": True,
                "isDefault": False, "indicatorType": "Tag", "optionId": ind["optionId"]}
    ind_cfgs = {}

    # Standard-Konfiguration fuer Einzelwerte (isDefault) aus der eingebetteten Tag-Option.
    # Das Muster-Element kann auf eine lokale Konfiguration der Basis zeigen, die hier nicht mitkommt.
    default_cfg_id = "105cc6bf-423e-4b1c-9b57-12fba6e0ffef"
    om = re.search(r'<we:property name="options" value="([^"]*)"', wx)
    if om:
        for o in json.loads(html.unescape(om.group(1))):
            sc = ((o.get("indicators") or {}).get("Tag") or {}).get("singleConfig")
            if o.get("name") == "Tag.Option_Name" and sc and sc.get("id"):
                default_cfg_id = sc["id"]

    # Segmente: eins pro Variable
    new_cfg = {}
    for i, (full, _short, dtype) in enumerate(tags):
        g = copy.deepcopy(sample)
        gid = str(uuid.uuid4())
        g["id"], g["name"], g["selected"] = gid, f"GroupConfiguration{i + 1}", False
        g["indicators"] = [copy.deepcopy(sample["indicators"][0])]
        ind = g["indicators"][0]
        ind.update(id=full, name=full, internalId=str(uuid.uuid4()), selected=False,
                   location=f"{sheet_name}!B{first_row + i}", datatype=dtype or ind.get("datatype", ""))
        ind["displayname"] = [{"lcid": "127", "text": full}]
        if quality:
            ind["configurationId"] = ind["internalId"]
            ind_cfgs[ind["internalId"]] = local_config(ind, qual="right")
        else:
            ind["configurationId"] = default_cfg_id
        new_cfg[gid] = g

    # Erstellungszeitpunkt: Zeitstempel von @Heartbeat (aendert sich jede Sekunde)
    if heartbeat:
        g = copy.deepcopy(sample)
        gid = str(uuid.uuid4())
        g["id"], g["name"], g["selected"] = gid, "Erstellt_am", False
        g["indicators"] = [copy.deepcopy(sample["indicators"][0])]
        ind = g["indicators"][0]
        ind.update(id=heartbeat, name=heartbeat, internalId=str(uuid.uuid4()), selected=False,
                   location=f"{sheet_name}!C2", datatype="UInt32")
        ind["displayname"] = [{"lcid": "127", "text": heartbeat}]
        ind["configurationId"] = ind["internalId"]
        ind_cfgs[ind["internalId"]] = local_config(ind, timestamp="left")   # Zeitstempel -> B2
        new_cfg[gid] = g

    wx_new = re.sub(PROP_RE, lambda mm: mm.group(1) + esc(dumps(new_cfg)) + mm.group(3), wx)
    icfg_re = r'(<we:property name="indicator_configurations" value=")([^"]*)(")'
    if re.search(icfg_re, wx_new):
        wx_new = re.sub(icfg_re, lambda mm: mm.group(1) + esc(dumps(ind_cfgs)) + mm.group(3), wx_new)
    else:
        wx_new = wx_new.replace(
            "</we:properties>",
            f'<we:property name="indicator_configurations" value="{esc(dumps(ind_cfgs))}"/></we:properties>', 1)

    # Blatt finden (Name -> sheetN.xml)
    wb = zin.read("xl/workbook.xml").decode("utf-8")
    rels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    sm = re.search(rf'<sheet name="{re.escape(sheet_name)}" sheetId="\d+" r:id="(rId\d+)"', wb)
    if not sm:
        sys.exit(f"Blatt '{sheet_name}' nicht in der Basis-Datei.")
    target = re.search(rf'Id="{sm.group(1)}"[^>]*Target="([^"]+)"|Target="([^"]+)"[^>]*Id="{sm.group(1)}"', rels)
    sheet_path = "xl/" + (target.group(1) or target.group(2)).lstrip("/").removeprefix("xl/")

    styles, styled = patch_styles(zin.read("xl/styles.xml").decode("utf-8"))
    st = (lambda s: s) if styled else (lambda s: ST_DEFAULT)

    last = first_row + len(tags) - 1
    rows = [f'<row r="1">{text_cell("A1", title, st(ST_TITLE))}</row>',
            (f'<row r="2">{text_cell("A2", "Erstellt am:", st(ST_BOLD))}'
             f'<c r="B2" s="{st(ST_DATETIME)}"/><c r="C2" s="{st(ST_HIDDEN)}"/></row>' if heartbeat else ""),
            f'<row r="{first_row - 1}">{text_cell(f"A{first_row - 1}", "Variable", st(ST_BOLD))}'
            f'{text_cell(f"B{first_row - 1}", "Wert", st(ST_BOLD))}'
            + (text_cell(f"C{first_row - 1}", "Qualitaet", st(ST_BOLD)) if quality else "")
            + (text_cell(f"D{first_row - 1}", "Verwendet in", st(ST_BOLD)) if usage is not None else "") + '</row>']
    for i, (_full, short, dtype) in enumerate(tags):
        r = first_row + i
        b = f'<c r="B{r}" s="{st(ST_REAL)}"/>' if dtype in REAL_TYPES and styled else ""
        q = f'<c r="C{r}" s="{st(ST_QUALITY)}"/>' if quality and styled else ""
        u = text_cell(f"D{r}", "; ".join(usage.get(short, [])) or "-") if usage is not None else ""
        rows.append(f'<row r="{r}">{text_cell(f"A{r}", short)}{b}{q}{u}</row>')

    sheet = zin.read(sheet_path).decode("utf-8")
    if not re.search(r"<sheetData\s*/>", sheet):
        sys.exit(f"Blatt '{sheet_name}' der Basis-Datei ist nicht leer - bitte leeres Blatt verwenden.")
    width_a = max([len(t[1]) for t in tags] + [12]) + 2
    sheet = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="A1:D{last}"/>', sheet)
    sheet = re.sub(r"<sheetData\s*/>",
                   f'<cols><col min="1" max="1" width="{width_a}" customWidth="1"/>'
                   '<col min="2" max="2" width="30" customWidth="1"/>'
                   '<col min="3" max="3" width="18" customWidth="1"/>'
                   '<col min="4" max="4" width="60" customWidth="1"/></cols>'
                   "<sheetData>" + "".join(rows) + "</sheetData>", sheet, count=1)
    header = '<headerFooter><oddHeader>&amp;L&amp;"-,Fett"' + esc(title) + '&amp;R&amp;D &amp;T</oddHeader></headerFooter>'
    sheet = re.sub(r"<headerFooter>.*?</headerFooter>", "", sheet)
    sheet = re.sub(r"(<pageMargins [^>]*/>)", lambda mm: mm.group(1) + header, sheet, count=1)

    replace = {"xl/webextensions/webextension1.xml": wx_new, sheet_path: sheet,
               "xl/styles.xml": styles}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = replace.get(item.filename)
            zout.writestr(item, data.encode("utf-8") if data is not None else zin.read(item.filename))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", help="Offline-Konfiguration aus dem Bericht-Control (.json)")
    ap.add_argument("--base", help="vom Add-in angelegte Basis-.xlsx (Standard: basis_vorlage.xlsx neben dem "
                                   "Skript, sonst test.xlsx im aktuellen Ordner)")
    ap.add_argument("--out", default="Vorlage_Variablen.xlsx", help="Ausgabedatei")
    ap.add_argument("--sheet", default="Tabelle1", help="Blattname in der Basis-Datei")
    ap.add_argument("--title", default="Variablenbericht", help="Titel oben und in der Kopfzeile")
    ap.add_argument("--first-row", type=int, default=5, help="erste Zeile der Variablenliste")
    ap.add_argument("--system", action="store_true", help="auch System-Tags (@...) aufnehmen")
    ap.add_argument("--filter", help="Regex auf den Kurznamen, z.B. '^Test_'")
    ap.add_argument("--list", action="store_true", help="nur Variablen anzeigen, keine Datei schreiben")
    ap.add_argument("--quality", action="store_true", help="Qualitaetscode rechts neben jedem Wert ausgeben")
    ap.add_argument("--no-created", action="store_true", help="keine Zeile 'Erstellt am:' (Zeitstempel von @Heartbeat)")
    ap.add_argument("--used-only", action="store_true",
                    help="nur Variablen, die im HMI verwendet werden (Bilder, Alarme, Archiv, Skripte) - "
                         "fragt den TIA-MCP-Server (Projekt muss in TIA offen sein) oder --usage-json")
    ap.add_argument("--usage-column", action="store_true", help="Spalte D 'Verwendet in' mit den Fundstellen")
    ap.add_argument("--usage-json", help="gespeichertes Ergebnis von list_hmi_tag_usage statt Live-Abfrage")
    ap.add_argument("--save-usage", help="Ergebnis von list_hmi_tag_usage zusaetzlich als JSON speichern")
    ap.add_argument("--tags-xlsx", help="TIA-Export der HMI-Variablen (HMITags.xlsx) als Filter: "
                                        "nur Variablen, die darin stehen")
    ap.add_argument("--tables", help="mit --tags-xlsx: nur diese Variablentabellen (Komma, Platzhalter "
                                     "erlaubt, z.B. 'SPS_*,Antriebe')")
    ap.add_argument("--tables-file",
                    help=f"Datei mit Tabellennamen (eine pro Zeile). Ohne Angabe wird {DEFAULT_TABLES_FILE} "
                         "im Ordner des Skripts verwendet, falls vorhanden.")
    ap.add_argument("--list-tables", action="store_true", help="Tabellen aus --tags-xlsx anzeigen und beenden")
    a = ap.parse_args()

    if a.list_tables:
        if not a.tags_xlsx:
            sys.exit("--list-tables braucht --tags-xlsx.")
        from collections import Counter
        for tbl, n in sorted(Counter(read_tag_tables(a.tags_xlsx).values()).items()):
            print(f"  {tbl:<40} {n} Variablen")
        return

    tags = read_tags(a.json, a.system, a.filter)
    if not tags:
        sys.exit("Keine Variablen gefunden (Filter/--system pruefen).")

    if a.tags_xlsx and not a.tables:
        tables_file = Path(a.tables_file) if a.tables_file else Path(__file__).resolve().parent / DEFAULT_TABLES_FILE
        if a.tables_file and not tables_file.exists():
            sys.exit(f"Tabellendatei nicht gefunden: {tables_file}")
        if tables_file.exists():
            a.tables = read_tables_file(tables_file)
            print(f"Tabellen aus {tables_file}: {a.tables}")
    elif a.tables_file and not a.tags_xlsx:
        sys.exit("--tables-file braucht --tags-xlsx.")

    if a.tags_xlsx:
        allowed, tag_tables = table_filter(a.tags_xlsx, a.tables)
        if not allowed:
            sys.exit(f"Keine Variablen fuer Tabellen '{a.tables}' in {a.tags_xlsx} (--list-tables zeigt die Tabellen).")
        before = len(tags)
        tags = [t for t in tags if t[1].split("::")[-1].split(".")[0].split("[")[0] in allowed]
        missing = sorted(allowed - {t[1].split(".")[0].split("[")[0] for t in tags})
        print(f"--tags-xlsx{' --tables ' + a.tables if a.tables else ''}: {len(tags)} von {before} Eintraegen.")
        if missing:
            print(f"Hinweis: {len(missing)} Variable(n) aus der Excel-Datei fehlen in der JSON: {', '.join(missing[:10])}")
        if not tags:
            sys.exit("Nach dem Tabellenfilter bleibt nichts uebrig.")

    usage_map = None
    if a.used_only or a.usage_column:
        device = tags[0][0].split("::", 1)[0]
        res = load_usage(device, a.usage_json)
        if a.save_usage:
            Path(a.save_usage).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"Verwendung gespeichert: {a.save_usage}")
        usage_map = {short: usage_for(short, res["usages"]) for _f, short, _d in tags}
        if a.used_only:
            before = len(tags)
            tags = [t for t in tags if usage_map[t[1]]]
            print(f"--used-only: {len(tags)} von {before} Variablen werden verwendet.")
            if not tags:
                sys.exit("Keine verwendeten Variablen gefunden.")
    print(f"{len(tags)} Variablen:")
    for full, _s, dt in tags:
        print(f"  {full:<45} {dt}")
    if a.list:
        return
    heartbeat = None if a.no_created else find_heartbeat(a.json)
    if not a.no_created and not heartbeat:
        print("Hinweis: @Heartbeat nicht in der JSON - Zeile 'Erstellt am:' entfaellt.")
    if not a.base:
        beside = Path(__file__).resolve().parent / "basis_vorlage.xlsx"
        a.base = str(beside) if beside.exists() else "test.xlsx"
    if not Path(a.base).exists():
        sys.exit(f"Basis-Datei nicht gefunden: {a.base} (mit --base angeben oder basis_vorlage.xlsx "
                 "neben das Skript legen)")
    print(f"Basis: {a.base}")
    build(tags, a.base, a.out, a.sheet, a.title, a.first_row, heartbeat, a.quality,
          usage_map if a.usage_column else None)
    print(f"\nVorlage geschrieben: {Path(a.out).resolve()}")


if __name__ == "__main__":
    main()
