#!/usr/bin/env python3
"""
json2vorlage.py - erzeugt eine WinCC-Unified-Berichtsvorlage (.xlsx) aus der
Offline-Konfiguration (.json) des Bericht-Controls.

Aufruf:
    python json2vorlage.py anlage.json

Alle Einstellungen stehen in json2vorlage.ini neben dem Skript (Titel, Ausgabedatei,
Qualitaetsspalte, Filter nach Variablentabellen, nur verwendete Variablen ...).
Die Ini-Datei ist kommentiert; fehlt sie, gelten die Standardwerte.

Weitere Aufrufe:
    python json2vorlage.py anlage.json --list         Variablen nur anzeigen
    python json2vorlage.py anlage.json --tabellen     Variablentabellen aus der Excel-Datei anzeigen
    python json2vorlage.py anlage.json --ini linie2.ini   andere Ini-Datei verwenden

Ergebnis: Jede Variable steht untereinander (Spalte A Name, Spalte B Wert), UDTs und Arrays
sind in ihre Elemente aufgeloest. Oben stehen Titel und "Erstellt am:" (Zeitpunkt der
Berichtserzeugung), optional rechts der Qualitaetscode und die Fundstellen im HMI.
"""
import argparse
import configparser
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
ST_DEFAULT, ST_BOLD, ST_TITLE, ST_DATETIME, ST_REAL, ST_HIDDEN, ST_QUALITY, ST_GROUP = 0, 1, 2, 3, 4, 5, 6, 7


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
    # hellgraue Fuellung fuer Gruppen-Ueberschriften
    styles = styles.replace("</fills>", '<fill><patternFill patternType="solid"><fgColor rgb="FFD9D9D9"/>'
                                        '<bgColor indexed="64"/></patternFill></fill></fills>', 1)
    nfill = styles.count("<fill>")
    styles = re.sub(r'<fills count="\d+"', f'<fills count="{nfill}"', styles, count=1)
    styles = re.sub(
        r'<cellXfs count="1">(<xf [^>]*/>)</cellXfs>',
        lambda m: '<cellXfs count="8">' + m.group(1)
        + f'<xf numFmtId="0" fontId="{nfont - 2}" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        + f'<xf numFmtId="0" fontId="{nfont - 1}" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        + '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left"/></xf>'
        + '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        + '<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        + '<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left"/></xf>'
        + f'<xf numFmtId="0" fontId="{nfont - 2}" fillId="{nfill - 1}" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>',
        styles, count=1)
    return styles, True


# ------------------------------------------------------------ Vorlage bauen --
def build(tags, base, out, sheet_name, title, first_row, heartbeat=None, quality=False, usage=None,
          groups=None):
    """groups: [(Tabellenname, [tags])] fuer gruppierte Ausgabe, sonst None."""
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

    # Zeilen-Layout: optional je Tabelle eine Ueberschriftzeile, Leerzeile zwischen den Gruppen
    layout, r = [], first_row
    for gi, (gname, gtags) in enumerate(groups or [(None, tags)]):
        if gname is not None:
            if gi:
                r += 1
            layout.append(("group", r, gname))
            r += 1
        for t in gtags:
            layout.append(("tag", r, t))
            r += 1
    tag_rows = [(row, t) for kind, row, t in layout if kind == "tag"]
    last = r - 1

    # Segmente: eins pro Variable
    new_cfg = {}
    for i, (row, (full, _short, dtype)) in enumerate(tag_rows):
        g = copy.deepcopy(sample)
        gid = str(uuid.uuid4())
        g["id"], g["name"], g["selected"] = gid, f"GroupConfiguration{i + 1}", False
        g["indicators"] = [copy.deepcopy(sample["indicators"][0])]
        ind = g["indicators"][0]
        ind.update(id=full, name=full, internalId=str(uuid.uuid4()), selected=False,
                   location=f"{sheet_name}!B{row}", datatype=dtype or ind.get("datatype", ""))
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

    rows = [f'<row r="1">{text_cell("A1", title, st(ST_TITLE))}</row>',
            (f'<row r="2">{text_cell("A2", "Erstellt am:", st(ST_BOLD))}'
             f'<c r="B2" s="{st(ST_DATETIME)}"/><c r="C2" s="{st(ST_HIDDEN)}"/></row>' if heartbeat else ""),
            f'<row r="{first_row - 1}">{text_cell(f"A{first_row - 1}", "Variable", st(ST_BOLD))}'
            f'{text_cell(f"B{first_row - 1}", "Wert", st(ST_BOLD))}'
            + (text_cell(f"C{first_row - 1}", "Qualitaet", st(ST_BOLD)) if quality else "")
            + (text_cell(f"D{first_row - 1}", "Verwendet in", st(ST_BOLD)) if usage is not None else "") + '</row>']
    ncols = 2 + (1 if quality else 0) + (1 if usage is not None else 0)
    for kind, r, item in layout:
        if kind == "group":
            fill = "".join(f'<c r="{c}{r}" s="{st(ST_GROUP)}"/>' for c in "BCD"[:ncols - 1])
            rows.append(f'<row r="{r}">{text_cell(f"A{r}", item, st(ST_GROUP))}{fill}</row>')
            continue
        _full, short, dtype = item
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


INI_NAME = "json2vorlage.ini"
INI_DEFAULTS = {
    "vorlage": {"titel": "Variablenbericht", "ausgabe": "Vorlage_Variablen.xlsx", "basis": "",
                "blatt": "Tabelle1", "erste_zeile": "5", "qualitaet": "ja", "erstellt_am": "ja",
                "gruppieren": "ja"},
    "filter": {"variablen_excel": "", "tabellen": "", "name_filter": "", "system_tags": "nein",
               "nur_verwendete": "nein", "spalte_verwendet": "nein", "verwendung_datei": ""},
}


def load_ini(path):
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    cp.BOOLEAN_STATES = {**configparser.ConfigParser.BOOLEAN_STATES, "ja": True, "nein": False,
                         "j": True, "n": False}
    cp.read_dict(INI_DEFAULTS)
    if path.exists():
        cp.read(path, encoding="utf-8-sig")
    return cp


def resolve(value, ini_dir):
    """Relative Pfade: zuerst im aktuellen Ordner, sonst neben der Ini-Datei suchen."""
    if not value:
        return None
    pth = Path(value)
    if pth.is_absolute() or pth.exists():
        return pth
    beside = ini_dir / pth
    return beside if beside.exists() else pth


def main():
    ap = argparse.ArgumentParser(
        description="Berichtsvorlage aus der Offline-Konfiguration erzeugen. "
                    f"Einstellungen in {INI_NAME} neben dem Skript.")
    ap.add_argument("json", help="Offline-Konfiguration aus dem Bericht-Control (.json)")
    ap.add_argument("--ini", help=f"andere Ini-Datei (Standard: {INI_NAME} neben dem Skript)")
    ap.add_argument("--list", action="store_true", help="Variablen nur anzeigen, keine Datei schreiben")
    ap.add_argument("--tabellen", action="store_true", help="Variablentabellen aus der Excel-Datei anzeigen")
    a = ap.parse_args()

    ini_path = Path(a.ini) if a.ini else Path(__file__).resolve().parent / INI_NAME
    if a.ini and not ini_path.exists():
        sys.exit(f"Ini-Datei nicht gefunden: {ini_path}")
    cp = load_ini(ini_path)
    v, f = cp["vorlage"], cp["filter"]
    ini_dir = ini_path.resolve().parent
    print(f"Einstellungen: {ini_path if ini_path.exists() else 'Standardwerte (keine Ini-Datei)'}")

    tags_xlsx = resolve(f.get("variablen_excel"), ini_dir)
    if tags_xlsx and not tags_xlsx.exists():
        sys.exit(f"variablen_excel nicht gefunden: {tags_xlsx}")
    tables = ",".join(t.strip() for t in re.split(r"[,\n]", f.get("tabellen", "")) if t.strip())

    if a.tabellen:
        if not tags_xlsx:
            sys.exit("In der Ini-Datei ist keine variablen_excel eingetragen.")
        from collections import Counter
        for tbl, n in sorted(Counter(read_tag_tables(tags_xlsx).values()).items()):
            print(f"  {tbl:<40} {n} Variablen")
        return

    tags = read_tags(a.json, f.getboolean("system_tags"), f.get("name_filter") or None)
    if not tags:
        sys.exit("Keine Variablen gefunden (name_filter / system_tags pruefen).")
    root = lambda short: short.split(".")[0].split("[")[0]
    device = tags[0][0].split("::", 1)[0]

    # Verwendung: aus verwendung_datei oder live vom MCP-Server (dann ggf. in die Datei speichern)
    usage_file = resolve(f.get("verwendung_datei"), ini_dir)
    need_usage = f.getboolean("nur_verwendete") or f.getboolean("spalte_verwendet") \
        or (tables and not tags_xlsx)
    res = None
    if need_usage or (usage_file and usage_file.exists()):
        if usage_file and usage_file.exists():
            res = json.loads(usage_file.read_text(encoding="utf-8"))
            print(f"Verwendung aus {usage_file}")
        else:
            print(f"Verwendung live vom TIA-MCP-Server ({device}) ...")
            res = load_usage(device)
            if usage_file:
                usage_file.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"Verwendung gespeichert: {usage_file}")

    # Tabellenzuordnung: aus der Excel-Datei, sonst aus dem Verwendungs-Ergebnis
    if tags_xlsx:
        tag_table = read_tag_tables(tags_xlsx)
    elif res:
        tag_table = {n: v.get("table", "") for n, v in res.get("tags", {}).items()}
    else:
        tag_table = None

    if tables:
        if tag_table is None:
            sys.exit("Fuer 'tabellen' wird variablen_excel oder die Verwendung (MCP-Server / "
                     "verwendung_datei) gebraucht.")
        pats = [t.strip() for t in tables.split(",")]
        def table_ok(tbl):
            last_part = re.split(r"[\\/]", tbl)[-1]
            return any(fnmatch.fnmatchcase(tbl, pt) or fnmatch.fnmatchcase(last_part, pt) for pt in pats)
        before = len(tags)
        tags = [t for t in tags if table_ok(tag_table.get(root(t[1]), ""))]
        print(f"tabellen = {tables}: {len(tags)} von {before} Eintraegen.")
    elif tags_xlsx:
        before = len(tags)
        tags = [t for t in tags if root(t[1]) in tag_table]
        print(f"Variablen aus {tags_xlsx.name}: {len(tags)} von {before} Eintraegen.")
    if not tags:
        sys.exit("Nach dem Tabellenfilter bleibt nichts uebrig (--tabellen zeigt die Tabellen).")

    usage_map = None
    if res and (f.getboolean("nur_verwendete") or f.getboolean("spalte_verwendet")):
        usage_map = {short: usage_for(short, res["usages"]) for _f, short, _d in tags}
        if f.getboolean("nur_verwendete"):
            before = len(tags)
            tags = [t for t in tags if usage_map[t[1]]]
            print(f"nur_verwendete: {len(tags)} von {before} Eintraegen werden im HMI verwendet.")
            if not tags:
                sys.exit("Keine verwendeten Variablen gefunden.")

    # Gruppieren nach Tabelle (Reihenfolge wie unter 'tabellen', sonst alphabetisch)
    groups = None
    if v.getboolean("gruppieren"):
        if tag_table is None:
            print("Hinweis: gruppieren braucht variablen_excel oder die Verwendung - Ausgabe ohne Gruppen.")
        else:
            pats = [t.strip() for t in tables.split(",")] if tables else []
            def order(tbl):
                last_part = re.split(r"[\\/]", tbl)[-1]
                idx = next((i for i, pt in enumerate(pats)
                            if fnmatch.fnmatchcase(tbl, pt) or fnmatch.fnmatchcase(last_part, pt)), len(pats))
                return (idx, tbl.lower())
            by_table = {}
            for t in tags:
                by_table.setdefault(tag_table.get(root(t[1]), "") or "(ohne Tabelle)", []).append(t)
            groups = [(tbl, by_table[tbl]) for tbl in sorted(by_table, key=order)]
            tags = [t for _g, gt in groups for t in gt]

    print(f"{len(tags)} Variablen:")
    for gname, gtags in groups or [(None, tags)]:
        if gname is not None:
            print(f"  [{gname}]")
        for full, _s, dt in gtags:
            print(f"  {full:<45} {dt}")
    if a.list:
        return

    base = resolve(v.get("basis"), ini_dir)
    if not base:
        beside = Path(__file__).resolve().parent / "basis_vorlage.xlsx"
        base = beside if beside.exists() else Path("test.xlsx")
    if not base.exists():
        sys.exit(f"Basis-Datei nicht gefunden: {base} (in der Ini unter basis eintragen)")
    heartbeat = find_heartbeat(a.json) if v.getboolean("erstellt_am") else None
    if v.getboolean("erstellt_am") and not heartbeat:
        print("Hinweis: @Heartbeat nicht in der JSON - Zeile 'Erstellt am:' entfaellt.")
    out = Path(v.get("ausgabe") or "Vorlage_Variablen.xlsx")
    build(tags, str(base), str(out), v.get("blatt"), v.get("titel"), v.getint("erste_zeile"),
          heartbeat, v.getboolean("qualitaet"), usage_map if f.getboolean("spalte_verwendet") else None,
          groups)
    print(f"\nBasis: {base}\nVorlage geschrieben: {out.resolve()}")


if __name__ == "__main__":
    main()
