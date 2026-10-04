#!/usr/bin/env python3
"""
json2vorlage.py - erzeugt WinCC-Unified-Berichtsvorlagen (.xlsx) fuer den Bericht-Control.

Aufruf:
    python json2vorlage.py                 Variablen direkt aus dem TIA-Projekt (MCP-Server)
    python json2vorlage.py anlage.json     Variablen aus der Offline-Konfiguration (wie bisher)

Alle Einstellungen stehen in json2vorlage.ini neben dem Skript (HMI, Titel, Ausgabedatei,
Filter, nur verwendete Variablen ...). Ohne JSON kommen Variablen, Datentypen, Tabellen und
Verwendung ueber list_hmi_tag_usage aus dem TIA-Projekt - live ueber den MCP-Server oder aus
verwendung_datei. Ist in der Ini keine HMI eingetragen, wird fuer jede Unified-HMI des
Projekts eine eigene Vorlage erzeugt ({hmi} im Dateinamen).

Weitere Aufrufe:
    python json2vorlage.py --list              Variablen nur anzeigen
    python json2vorlage.py --tabellen          Variablentabellen mit Anzahl Variablen anzeigen
    python json2vorlage.py --ini linie2.ini    andere Ini-Datei verwenden

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
def read_tags(json_path, include_system=False, name_filter=None, quiet=False):
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
                if not quiet:
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
                if not quiet:
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


def _name_hit(value, pat):
    """Namens-Semantik: ohne Platzhalter = enthaelt; mit * oder ? = Muster fuer den ganzen Wert.
    [ ] bleiben normaler Text (Array-Index wie Messwerte[3]). Gross-/Kleinschreibung egal."""
    value, pat = value.lower(), pat.lower()
    if any(c in pat for c in "*?"):
        return fnmatch.fnmatchcase(value, pat.replace("[", "[[]"))
    return pat in value


def _table_hit(table, pat):
    """Tabellen: genauer Name oder Muster mit * / ?, verglichen mit vollem Pfad und letztem Teil."""
    table, pat = table.lower(), pat.lower()
    last = re.split(r"[\\/]", table)[-1]
    return fnmatch.fnmatchcase(table, pat) or fnmatch.fnmatchcase(last, pat)


class Filter:
    """Ein Ini-Filtereintrag: Komma oder eine pro Zeile, '!' davor = ausschliessen."""

    def __init__(self, spec, hit=_name_hit):
        entries = [e.strip() for e in re.split(r"[,\n]", spec or "") if e.strip()]
        self.incl = [e for e in entries if not e.startswith("!")]
        self.excl = [e[1:].strip() for e in entries if e.startswith("!") and e[1:].strip()]
        self.hit = hit

    def __bool__(self):
        return bool(self.incl or self.excl)

    def includes(self, value):
        return any(self.hit(value, pt) for pt in self.incl)

    def excludes(self, value):
        return any(self.hit(value, pt) for pt in self.excl)

    def matches(self, value):
        return (not self.incl or self.includes(value)) and not self.excludes(value)


def name_matcher(spec):
    """Kompatibilitaet: Funktion 'passt?' fuer einen namen-Eintrag oder None."""
    flt = Filter(spec)
    return flt.matches if flt else None


class McpError(Exception):
    pass


MCP_PORT = 47823
_server = {"dir": None, "proc": None}     # vom Skript selbst gestarteter MCP-Server


def start_server():
    """TIA-MCP-Server im Hintergrund starten (ohne Fenster) und warten, bis der RPC-Port antwortet."""
    import subprocess, time
    sdir = Path(_server["dir"])
    script = sdir / "server.py"
    if not script.exists():
        raise McpError(f"MCP-Server nicht gefunden: {script} (Ini: [server] mcp_server)")
    py = sdir / ".venv" / "Scripts" / "python.exe"
    print(f"Starte TIA-MCP-Server ({sdir}) ...")
    _server["proc"] = subprocess.Popen(
        [str(py if py.exists() else sys.executable), str(script)], cwd=str(sdir),
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    t0 = time.time()
    while time.time() - t0 < 30:
        if _server["proc"].poll() is not None:
            raise McpError("MCP-Server hat sich sofort beendet (Details in C:/tia-mcp/logs/tia_mcp.log).")
        try:
            socket.create_connection(("127.0.0.1", MCP_PORT), timeout=1).close()
            return
        except OSError:
            time.sleep(0.5)
    stop_server()
    raise McpError("MCP-Server antwortet nach 30 s nicht.")


def stop_server():
    """Selbst gestarteten Server beenden - beendet auch seinen Worker und gibt TIA frei."""
    import subprocess
    proc, _server["proc"] = _server["proc"], None
    if proc is None:
        return
    try:
        proc.stdin.close()              # stdio-Ende -> Server beendet sich und seinen Worker
        proc.wait(timeout=15)
    except Exception:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("TIA-MCP-Server wieder beendet.")


def mcp_call(tool, port=MCP_PORT, **args):
    """Tool des TIA-MCP-Servers aufrufen (lokaler RPC-Port der Primaer-Instanz).
    Laeuft keiner und ist [server] autostart = ja, wird er gestartet."""
    try:
        r = _rpc(tool, port, args)
    except ConnectionRefusedError as e:
        if not _server["dir"] or _server["proc"] is not None:
            raise McpError(f"MCP-Server nicht erreichbar (127.0.0.1:{port}): {e}")
        start_server()
        r = _rpc(tool, port, args)
    except OSError as e:
        raise McpError(f"MCP-Server nicht erreichbar (127.0.0.1:{port}): {e}")
    if not r["ok"]:
        raise McpError(f"MCP-Fehler bei {tool}: {r['error']}")
    return r["result"]


def _rpc(tool, port, args):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=600) as sock:
            sock.sendall((json.dumps({"tool": tool, "args": args}) + "\n").encode())
            return json.loads(sock.makefile("rb").readline())
    except ConnectionRefusedError:
        raise
    except OSError as e:
        raise McpError(f"MCP-Server nicht erreichbar (127.0.0.1:{port}): {e}")



def load_usage(device, include_scripts=True):
    """Verwendung der Variablen live vom MCP-Server (Projekt muss in TIA offen sein)."""
    ensure_connected()
    return mcp_call("list_hmi_tag_usage", device_name=device, include_scripts=include_scripts)


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
                "gruppieren": "ja", "hmi": ""},
    "server": {"mcp_server": r"C:\tia-mcp\mcp-server", "autostart": "ja"},
    "runtime": {"pruefen": "nein", "url": "http://localhost:4000/graphql", "benutzer": "",
                "datei": "runtime_{hmi}.txt"},
    "filter": {"tabellen": "", "namen": "", "datentypen": "", "verknuepfung": "und", "system_tags": "nein",
               "nur_verwendete": "nein", "spalte_verwendet": "nein", "verwendung_datei": "",
               "skripte_auswerten": "ja"},
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


class Abort(Exception):
    """Fehler bei einer HMI - bei mehreren HMIs wird mit der naechsten weitergemacht."""


def ensure_connected():
    status = mcp_call("get_session_status")
    if not status.get("project_open") and not status.get("reconnect_on_next_call"):
        mcp_call("connect_portal")
        mcp_call("attach_project")


def current_project():
    """Name des in TIA offenen Projekts - nur wenn der MCP-Server schon laeuft und verbunden ist
    (startet nichts und verbindet nicht neu). Sonst None."""
    try:
        status = _rpc("get_session_status", MCP_PORT, {})
    except Exception:
        return None
    if status.get("ok"):
        return (status.get("result") or {}).get("project_name") or None
    return None


def list_unified_hmis():
    ensure_connected()
    devs = mcp_call("list_devices")
    return [sw["item"] for d in devs.get("devices", []) for sw in d.get("software", []) if sw.get("type") == "Unified"]


# ------------------------------------------------- Runtime-Pruefung (GraphQL) --
# Unified laedt von Strukturvariablen nur die im HMI verwendeten Elemente (spart PowerTags).
# Alle anderen kann der Bericht nicht lesen: Er bekommt null und bricht mit "Uncaught exception" ab.
# Welche Elemente geladen sind, weiss nur die Runtime - deshalb hier per GraphQL nachfragen.
GQL_READ = "query($n:[String!]!){tagValues(names:$n){name value{value} error{code description}}}"
_rt = {"token": None, "url": None}


class RuntimeError_(Exception):
    pass


def _gql(url, query, variables, token=None):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError_(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except OSError as e:
        raise RuntimeError_(f"Runtime nicht erreichbar ({url}): {e}")
    if res.get("errors") and not res.get("data"):
        raise RuntimeError_(json.dumps(res["errors"], ensure_ascii=False)[:300])
    return res


def runtime_login(url, user):
    """Einmal pro Lauf anmelden; das Passwort wird verdeckt abgefragt und nicht gespeichert."""
    if _rt["token"] and _rt["url"] == url:
        return _rt["token"]
    import getpass
    _gql(url, "{__typename}", {})          # erreichbar? sonst gar nicht erst nach dem Passwort fragen
    user = user or input("Runtime-Benutzer: ")
    pw = getpass.getpass(f"Passwort fuer {user}: ")
    r = _gql(url, "mutation($u:String!,$p:String!){login(username:$u,password:$p){token error{code description}}}",
             {"u": user, "p": pw})
    login = (r.get("data") or {}).get("login") or {}
    if not login.get("token"):
        raise RuntimeError_(f"Anmeldung an der Runtime fehlgeschlagen: {login.get('error') or r}")
    _rt.update(token=login["token"], url=url)
    return _rt["token"]


def runtime_check(names, url, user):
    """Liefert (nicht_geladen, unbekannt, ohne_wert) fuer die Kurznamen."""
    token = runtime_login(url, user)
    results = []

    def read(batch):
        try:
            results.extend(_gql(url, GQL_READ, {"n": batch}, token)["data"]["tagValues"])
        except RuntimeError_:
            if len(batch) == 1:
                results.append({"name": batch[0], "error": {"code": "abgelehnt", "description": "abgelehnt"}})
                return
            read(batch[:len(batch) // 2])
            read(batch[len(batch) // 2:])

    for i in range(0, len(names), 200):
        read(names[i:i + 200])
    missing, unknown, nulls = [], [], []
    for x in results:
        err = x.get("error") or {}
        if err.get("code") not in (None, "0", 0):
            desc = err.get("description") or ""
            (missing if "leaf" in desc.lower() else unknown).append((x["name"], desc))
        elif (x.get("value") or {}).get("value") is None:
            nulls.append(x["name"])
    return missing, unknown, nulls


def runtime_precheck(hmi, rt, ini_dir, names=None):
    """Vor der (langen) Verwendungsabfrage: Ist eine Runtime-Pruefung fuer dieses HMI moeglich?
    Ja, wenn die laufende Runtime die Variablen des HMI kennt oder runtime_{hmi}.txt schon da ist.
    Sonst Abort -> das HMI wird uebersprungen."""
    spec = rt.get("datei", "")
    store = resolve(spec.replace("{hmi}", hmi), ini_dir) if spec else None
    try:
        if names is None:
            ensure_connected()
            names = [t["name"] for t in mcp_call("list_hmi_tags", device_name=hmi).get("tags", [])]
        if not names:
            return
        sample = names[::max(1, len(names) // 40)][:40]
        # Strukturvariablen selbst melden "Only leaf ..." - auch das heisst: Variable ist bekannt
        _missing, unknown, _nulls = runtime_check(sample, rt.get("url"), rt.get("benutzer", "").strip())
        if len(unknown) > len(sample) / 2:
            raise RuntimeError_(f"Die laufende Runtime gehoert nicht zu {hmi} ({len(unknown)} von {len(sample)} "
                                "Stichproben unbekannt)")
        print(f"Runtime laeuft mit {hmi}.")
    except RuntimeError_ as e:
        if store and store.exists():
            print(f"Hinweis: {e} - nehme spaeter die letzte Pruefung aus {store}.")
            return
        raise Abort(f"{e}, und {store or 'runtime_' + hmi + '.txt'} fehlt - {hmi} uebersprungen. "
                    f"Runtime von {hmi} starten (oder simulieren) und nochmal laufen lassen.")


def apply_runtime_check(hmi, tags, rt, ini_dir):
    """Elemente, die die Runtime nicht geladen hat, aus der Liste nehmen. Ergebnis wird in
    rt['datei'] gemerkt und ohne laufende Runtime von dort genommen."""
    import datetime
    spec = rt.get("datei", "")
    store = resolve(spec.replace("{hmi}", hmi), ini_dir) if spec else None
    names = [short for _f, short, _d in tags]
    try:
        print(f"Runtime-Pruefung ({rt.get('url')}) fuer {len(names)} Variablen ...")
        missing, unknown, nulls = runtime_check(names, rt.get("url"), rt.get("benutzer", "").strip())
        if len(unknown) > len(names) / 2:
            raise RuntimeError_(f"{len(unknown)} von {len(names)} Variablen kennt die Runtime nicht "
                                f"(z.B. {unknown[0][0]}: {unknown[0][1]}) - laeuft dort ein anderes HMI als {hmi}?")
        drop = {n for n, _d in missing + unknown}
        if store:
            store.write_text(f"# Runtime-Pruefung {hmi} vom {datetime.datetime.now():%d.%m.%Y %H:%M}: "
                             "in der Runtime nicht vorhanden\n" +
                             "".join(f"{n}\t{d}\n" for n, d in missing + unknown), encoding="utf-8")
        for n, d in unknown[:10]:
            print(f"   unbekannt: {n} ({d})")
        if nulls:
            print(f"Achtung: {len(nulls)} Variablen liefern gerade keinen Wert (Verbindung zur SPS?), "
                  f"z.B. {', '.join(nulls[:5])} - der Bericht bricht dann ab. Sie bleiben in der Vorlage.")
    except RuntimeError_ as e:
        if not (store and store.exists()):
            raise Abort(f"{e}\nOhne Runtime-Pruefung koennte der Bericht abbrechen. Runtime von {hmi} starten "
                        "oder [runtime] pruefen = nein.")
        print(f"Hinweis: {e}\nNehme die letzte Pruefung aus {store}.")
        lines = store.read_text(encoding="utf-8").splitlines()
        print(f"   {lines[0].lstrip('# ')}" if lines else "")
        drop = {ln.split("\t", 1)[0] for ln in lines if ln and not ln.startswith("#")}
    kept = [t for t in tags if t[1] not in drop]
    print(f"Runtime: {len(tags) - len(kept)} Elemente von Unified wegoptimiert (nicht als PowerTag geladen) "
          f"- {len(kept)} bleiben in der Vorlage.")
    by_member = {}
    for n in sorted(drop):
        by_member.setdefault(re.sub(r"^[^.]+\.", "", n), []).append(n)
    for mem, ns in sorted(by_member.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"   {mem:<30} {len(ns)}x")
    if not kept:
        raise Abort("Nach der Runtime-Pruefung bleibt keine Variable uebrig.")
    return kept


def main():
    # Variablennamen mit Zeichen ausserhalb der Konsolen-Codepage (z.B. griechisches mu)
    # duerfen die Ausgabe nicht abbrechen
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="Berichtsvorlagen fuer den WinCC-Unified-Bericht-Control erzeugen. "
                    f"Einstellungen in {INI_NAME} neben dem Skript.")
    ap.add_argument("json", nargs="?", help="optional: Offline-Konfiguration aus dem Bericht-Control (.json); "
                                            "ohne = Variablen aus dem TIA-Projekt")
    ap.add_argument("--ini", help=f"andere Ini-Datei (Standard: {INI_NAME} neben dem Skript)")
    ap.add_argument("--list", action="store_true", help="Variablen nur anzeigen, keine Datei schreiben")
    ap.add_argument("--tabellen", action="store_true", help="Variablentabellen mit Anzahl Variablen anzeigen")
    a = ap.parse_args()

    ini_path = Path(a.ini) if a.ini else Path(__file__).resolve().parent / INI_NAME
    if a.ini and not ini_path.exists():
        sys.exit(f"Ini-Datei nicht gefunden: {ini_path}")
    cp = load_ini(ini_path)
    v, f = cp["vorlage"], cp["filter"]
    ini_dir = ini_path.resolve().parent
    print(f"Einstellungen: {ini_path if ini_path.exists() else 'Standardwerte (keine Ini-Datei)'}")
    if cp["server"].getboolean("autostart"):
        _server["dir"] = cp["server"].get("mcp_server")
    try:
        _main(a, v, f, ini_dir, cp["runtime"])
    finally:
        stop_server()


def _main(a, v, f, ini_dir, rt):
    # Welche HMIs?
    wanted = [h.strip() for h in re.split(r"[,\n]", v.get("hmi", "")) if h.strip()]
    if a.json:
        tags = read_tags(a.json, True, quiet=True)
        if not tags:
            sys.exit("Keine Variablen in der JSON gefunden.")
        json_hmi = tags[0][0].split("::", 1)[0]
        if wanted and wanted != [json_hmi]:
            sys.exit(f"hmi = {', '.join(wanted)} passt nicht zur JSON ({json_hmi}).")
        hmis = [json_hmi]
    elif wanted:
        hmis = wanted
    else:
        try:
            hmis = list_unified_hmis()
            print(f"Unified-HMIs im Projekt: {', '.join(hmis) or '-'}")
        except McpError as e:
            pattern = f.get("verwendung_datei", "")
            if "{hmi}" not in pattern:
                sys.exit(f"{e}\nOhne JSON und ohne hmi in der Ini werden die HMIs aus dem TIA-Projekt "
                         "gelesen (MCP-Server) - oder verwendung_datei mit {hmi} angeben.")
            import glob
            pre, post = pattern.split("{hmi}", 1)
            files = glob.glob(str(resolve(pre + "*" + post, ini_dir) or "")) or glob.glob(pre + "*" + post)
            hmis = sorted({Path(fn).name[len(Path(pre).name):len(Path(fn).name) - len(post)] for fn in files})
            print(f"MCP-Server nicht erreichbar - HMIs aus vorhandenen Verwendungsdateien: {', '.join(hmis) or '-'}")
        if not hmis:
            sys.exit("Keine Unified-HMI gefunden.")

    failed = []
    for hmi in hmis:
        if len(hmis) > 1:
            print(f"\n===== {hmi} =====")
        try:
            run_hmi(hmi, a, v, f, ini_dir, rt, multi=len(hmis) > 1)
        except Abort as e:
            if len(hmis) == 1:
                sys.exit(str(e))
            print(f"FEHLER bei {hmi}: {e}")
            failed.append(hmi)
    if failed:
        sys.exit(f"\nNicht erzeugt: {', '.join(failed)}")


def run_hmi(hmi, a, v, f, ini_dir, rt, multi=False):
    tables = ",".join(t.strip() for t in re.split(r"[,\n]", f.get("tabellen", "")) if t.strip())
    usage_spec = f.get("verwendung_datei", "")
    usage_file = resolve(usage_spec.replace("{hmi}", hmi), ini_dir) if usage_spec else None
    if usage_file and multi and "{hmi}" not in usage_spec:
        raise Abort("Bei mehreren HMIs braucht verwendung_datei den Platzhalter {hmi}.")
    root = lambda short: short.split(".")[0].split("[")[0]

    # Verwendung (Variablenliste, Tabellen, Datentypen, Fundstellen): aus verwendung_datei oder live.
    # Ohne JSON immer noetig; mit JSON nur fuer Filter / Verwendung (fuer "nur gruppieren" optional).
    required = not a.json or a.tabellen or f.getboolean("nur_verwendete") or f.getboolean("spalte_verwendet") \
        or bool(tables) or bool(f.get("datentypen"))
    res = None
    check_rt = rt.getboolean("pruefen") and not a.list and not a.tabellen
    if check_rt and not (usage_file and usage_file.exists()):
        runtime_precheck(hmi, rt, ini_dir)      # vor der langen Verwendungsabfrage
    if usage_file and usage_file.exists():
        res = json.loads(usage_file.read_text(encoding="utf-8"))
        if check_rt:
            runtime_precheck(hmi, rt, ini_dir, [m["name"] for m in res.get("members", [])])
        if not res.get("project"):
            raise Abort(f"{usage_file} enthaelt keine Projektangabe (von vor dieser Version, evtl. aus einem "
                        "anderen Projekt) - Datei loeschen, dann wird sie neu abgefragt.")
        print(f"Verwendung aus {usage_file} (Projekt {res['project']}, abgefragt {res.get('saved', '?')})")
        live = current_project()
        if live and live != res["project"]:
            raise Abort(f"{usage_file} gehoert zum Projekt {res['project']}, in TIA ist aber {live} offen. "
                        "Datei loeschen (wird neu abgefragt) oder das passende Projekt oeffnen.")
    elif required or v.getboolean("gruppieren"):
        print(f"Verwendung live vom TIA-MCP-Server ({hmi}) ... "
              "(Fortschritt: C:\\tia-mcp\\logs\\tia_mcp.log)")
        try:
            res = load_usage(hmi, f.getboolean("skripte_auswerten"))
        except McpError as e:
            if required:
                raise Abort(f"{e}\nGebraucht wird der MCP-Server mit geoeffnetem Projekt oder eine verwendung_datei.")
            print(f"Hinweis: {e} - Ausgabe ohne Gruppierung.")
        if res and usage_file:
            import datetime
            res["saved"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
            if not res.get("project"):
                res["project"] = current_project() or ""
            usage_file.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"Verwendung gespeichert: {usage_file}")
    if res and res.get("device") and res["device"] != hmi:
        raise Abort(f"Die Verwendung in {usage_file} gehoert zu {res['device']}, nicht zu {hmi}.")
    info = res.get("tags", {}) if res else {}
    tag_table = {n: x.get("table", "") for n, x in info.items()}
    tag_type = {n: x.get("datatype", "") for n, x in info.items()}

    if a.tabellen:
        from collections import Counter
        for tbl, n in sorted(Counter(tag_table.values()).items()):
            print(f"  {tbl:<40} {n} Variablen")
        return

    # Variablenliste: aus der JSON oder aus der Verwendung (Deklarationsreihenfolge)
    if a.json:
        tags = read_tags(a.json, f.getboolean("system_tags"))
    else:
        if "members" not in res:
            raise Abort("Die Verwendung enthaelt keine Variablenliste (verwendung_datei von vor dieser Version?) "
                        "- Datei loeschen, dann wird sie neu abgefragt.")
        tags = [(f"{hmi}::{m['name']}", m["name"], m["datatype"]) for m in res["members"]]
        if f.getboolean("system_tags"):
            tags += [(f"{hmi}::{m['name']}", m["name"], m["datatype"]) for m in res.get("system_members", [])]
    if not tags:
        raise Abort("Keine Variablen gefunden.")

    # Filter namen / datentypen / tabellen, verknuepft mit UND (alle muessen passen) oder
    # ODER (einer reicht). Ausschluesse mit ! gelten immer. Danach ggf. nur_verwendete.
    mode = (f.get("verknuepfung") or "und").strip().lower()
    if mode not in ("und", "oder"):
        sys.exit(f"verknuepfung = {mode}: erlaubt sind 'und' oder 'oder'.")
    f_name, f_type, f_table = Filter(f.get("namen")), Filter(f.get("datentypen")), Filter(tables, _table_hit)
    if f_type and not any(tag_type.values()):
        raise Abort("Die Verwendung enthaelt keine Datentypen (alte verwendung_datei?) - Datei loeschen, "
                    "dann wird sie neu abgefragt.")
    active = [(flt, get, label) for flt, get, label in (
        (f_name, lambda t: t[1], "namen"),
        (f_type, lambda t: tag_type.get(root(t[1]), ""), "datentypen"),
        (f_table, lambda t: tag_table.get(root(t[1]), ""), "tabellen")) if flt]
    if active:
        before = len(tags)
        if mode == "und":
            tags = [t for t in tags if all(flt.matches(get(t)) for flt, get, _l in active)]
        else:
            positive = [(flt, get) for flt, get, _l in active if flt.incl]
            tags = [t for t in tags
                    if (not positive or any(flt.includes(get(t)) for flt, get in positive))
                    and not any(flt.excludes(get(t)) for flt, get, _l in active)]
        desc = f" {mode.upper()} ".join(
            f"{label} = {', '.join(flt.incl + ['!' + e for e in flt.excl])}" for flt, _g, label in active)
        print(f"Filter {desc}: {len(tags)} von {before} Eintraegen.")
        if not tags:
            raise Abort("Kein Eintrag passt auf die Filter (namen / datentypen / tabellen, --tabellen zeigt "
                        "die Tabellen).")

    usage_map = None
    if res and (f.getboolean("nur_verwendete") or f.getboolean("spalte_verwendet")):
        usage_map = {short: usage_for(short, res["usages"]) for _f, short, _d in tags}
        if f.getboolean("nur_verwendete"):
            before = len(tags)
            tags = [t for t in tags if usage_map[t[1]]]
            print(f"nur_verwendete: {len(tags)} von {before} Eintraegen werden im HMI verwendet.")
            if not tags:
                raise Abort("Keine verwendeten Variablen gefunden.")

    # Nur Elemente, die die Runtime wirklich geladen hat (Unified optimiert ungenutzte Strukturelemente weg)
    if check_rt:
        tags = apply_runtime_check(hmi, tags, rt, ini_dir)

    # Gruppieren nach Tabelle (Reihenfolge wie unter 'tabellen', sonst alphabetisch)
    groups = None
    if v.getboolean("gruppieren") and tag_table:
        pats = f_table.incl
        def order(tbl):
            idx = next((i for i, pt in enumerate(pats) if _table_hit(tbl, pt)), len(pats))
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
        raise Abort(f"Basis-Datei nicht gefunden: {base} (in der Ini unter basis eintragen)")
    heartbeat = None
    if v.getboolean("erstellt_am"):
        heartbeat = find_heartbeat(a.json) if a.json else f"{hmi}::@Heartbeat"
        if not heartbeat:
            print("Hinweis: @Heartbeat nicht in der JSON - Zeile 'Erstellt am:' entfaellt.")
    out_spec = v.get("ausgabe") or "Vorlage_Variablen.xlsx"
    if multi and "{hmi}" not in out_spec:
        out_spec = str(Path(out_spec).with_name(f"{Path(out_spec).stem}_{{hmi}}{Path(out_spec).suffix}"))
    out = Path(out_spec.replace("{hmi}", hmi))
    build(tags, str(base), str(out), v.get("blatt"), v.get("titel").replace("{hmi}", hmi), v.getint("erste_zeile"),
          heartbeat, v.getboolean("qualitaet"), usage_map if f.getboolean("spalte_verwendet") else None,
          groups)
    print(f"\nBasis: {base}\nVorlage geschrieben: {out.resolve()}")


if __name__ == "__main__":
    main()
