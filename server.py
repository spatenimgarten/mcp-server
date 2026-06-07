"""
server.py — TIA Portal MCP Server
Einstiegspunkt. Startet mit: python server.py
Claude Desktop: %APPDATA%\Claude\claude_desktop_config.json
  { "mcpServers": { "tia-portal": { "command":"python",
    "args":["C:/tia-mcp/server.py"], "cwd":"C:/tia-mcp" } } }
"""

import json, asyncio, socket, sys
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import tia
from tia import TiaError, _DEFAULT_EXPORT
import base64

# ── Singleton-Lock ─────────────────────────────────────────────────────────────
# Verhindert, dass server.py doppelt laeuft (z.B. Claude Desktop + bridge.py).
# Ein zweiter Start gibt eine klare Fehlermeldung und beendet sich sofort.

_LOCK_PORT = 47823          # Beliebiger freier lokaler Port
_lock_socket = None         # Wird beim Start belegt, beim Beenden automatisch freigegeben

def _acquire_lock():
    global _lock_socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", _LOCK_PORT))
        sock.listen(1)
        _lock_socket = sock          # Referenz halten damit GC den Socket nicht schliesst
    except OSError:
        sock.close()
        print(
            "\n" + "=" * 60 + "\n"
            "FEHLER: TIA Portal MCP Server laeuft bereits!\n"
            "\n"
            "Nur eine Instanz ist erlaubt — sonst gibt es\n"
            "Konflikte auf der TIA Openness COM-Schnittstelle.\n"
            "\n"
            "Loesung: Claude Desktop oder bridge.py beenden,\n"
            "dann erneut starten.\n"
            + "=" * 60 + "\n",
            file=sys.stderr
        )
        sys.exit(1)

def _release_lock():
    global _lock_socket
    if _lock_socket:
        try:
            _lock_socket.close()
        except Exception:
            pass
        _lock_socket = None

server = Server("tia-portal")

# ── System Prompt ──────────────────────────────────────────────────────────────

_PROMPT = """
Du bist ein TIA Portal Engineering-Assistent mit direktem Zugriff auf
TIA Portal V21 ueber die Openness API. Du kannst Projekte lesen, analysieren
und Standardstrukturen anlegen (PLC, HMI Advanced/Unified, Bibliotheken).

# Verfuegbare Tools

## Session (immer zuerst)
  connect_portal(mode)     → Portal verbinden: attach (laufend) / headless / gui
  open_project(path)       → Projekt oeffnen (.ap21 Pfad)
  get_session_status()     → Verbindungs- und Projektstatus pruefen

## Projekt lesen
  get_project_info()       → Name, Pfad, Geraete
  list_devices()           → Alle Geraete mit erkanntem Typ (PLC / Advanced / Unified)

## HMI lesen
  list_hmi_screens(device)            → Alle Bilder mit Groesse und Elementanzahl
  list_hmi_tags(device, table?)       → Tags mit Datentyp, High/Low-Limit, Archivierung
  list_hmi_alarms(device)             → Diskrete und analoge Alarme mit Alarmklasse
  list_hmi_textlists(device)          → Textlisten mit Eintraegen
  export_hmi_screen(device, screen, path)  → Bild als XML exportieren
  export_hmi_tags(device, path)            → Alle Tags als XML exportieren

## Bibliothek lesen
  list_libraries()                         → Projekt- und globale Bibliotheken
  list_library_types(lib)                  → Typen mit allen Versionen und Standardversion
  list_master_copies(lib)                  → Master Copies (rekursiv)
  get_library_type_versions(lib, type)     → Versionen eines einzelnen Typs

## PLC lesen (JSON, kein Export noetig)
  list_plc_blocks(device, group?)      → Bausteine als JSON: name/number/type/language/path
  list_plc_tag_tables(device)          → Tag-Tabellen mit Namen und Tag-Anzahl
  list_plc_tags(device, table?)        → PLC-Tags als JSON: name/data_type/address/comment

## PLC schreiben
  save_project()                       → Projekt speichern — nach jeder Aenderung aufrufen!
  compile_plc(device)                  → Kompilieren vor Export / bei inkonsistenten Bloecken

## Generisch (lesen und schreiben)
  execute_openness(code, mode)
    mode='read'  → nur lesend, schreibende Methoden gesperrt (Standard)
    mode='write' → auch schreibend, explizit angeben
  get_standard_template()   → Vorlage fuer Standardprojektstruktur abrufen

# execute_openness: Kontext und Hilfsfunktionen

Verfuegbare Variablen im Code:
  portal              TiaPortal-Instanz
  project             Aktuelles Projekt (None wenn keins offen)
  eng                 Siemens.Engineering Namespace
  hmi                 Siemens.Engineering.Hmi (Advanced)
  unified             Siemens.Engineering.HmiUnified
  find_software(name, hint)   Software-Objekt eines Geraets suchen
  safe_str(obj)       .NET-Objekt sicher in String umwandeln
  collect(collection) .NET-Collection in Python-Liste umwandeln
  result              Hier das Ergebnis hineinschreiben

Beispiel:
  result = [d.Name for d in project.Devices]

Wichtige Einschraenkungen:
- Kein import erlaubt — alle Namespaces sind bereits vorgeladen
- Keine rekursiven Funktionen — exec() hat eigenen Scope, Funktionen sehen
  keine lokalen Variablen. Stattdessen iterativen Stack verwenden:
    stack = list(project.Devices)
    while stack:
        item = stack.pop()
        result.append(item.Name)
        for sub in item.DeviceItems: stack.append(sub)
- SoftwareContainer holen (V21):
    swc = item.GetService[SoftwareContainer]()   # SoftwareContainer direkt verfuegbar!
    if swc: plc = swc.Software
- find_software immer zuerst versuchen, Fallback:
    plc = find_software("PLC_1", "PlcSoftware")
    if not plc: plc = find_software("", "PlcSoftware")  # erstes PLC

# Objektmodell

## Geraet und Software finden
  # name = DeviceItem-Name (z.B. "PLC_1"), hint = Software-Typ
  # WICHTIG: name ist der DeviceItem-Name, nicht der Device/Station-Name!
  # Bei Unklarheit: erst list_devices() aufrufen um Namen zu sehen.
  plc = find_software("PLC_1", "PlcSoftware")   # S7-1500 CPU
  hmi = find_software("HMI_1", "Hmi")           # WinCC Advanced
  hmi = find_software("HMI_1", "Unified")       # WinCC Unified
  # Erstes PLC/HMI ohne Namen suchen:
  plc = find_software("", "PlcSoftware")
  hmi = find_software("", "Hmi")

## PLC
  # Bausteine iterativ lesen
  stack = [(plc.BlockGroup, "")]
  result = []
  while stack:
      group, path = stack.pop()
      for block in group.Blocks:
          result.append({"path": path, "name": block.Name,
                         "type": type(block).__name__,
                         "number": getattr(block, "Number", None)})
      for sub in group.Groups:
          stack.append((sub, f"{path}/{sub.Name}".lstrip("/")))

  # SPS kompilieren (z.B. vor Export bei inkonsistenten Bloecken)
  # ICompilable per Reflection laden:
  stack2 = list(project.Devices)
  while stack2:
      item = stack2.pop() if hasattr(stack2[0], "DeviceItems") else stack2.pop()
      try:
          swc = item.GetService[SoftwareContainer]()
          if swc:
              compilable_type = swc.Software.GetType().Assembly.GetType(
                  "Siemens.Engineering.Compiler.ICompilable")
              if compilable_type:
                  compiler = swc.Software.GetService[compilable_type]()
                  if compiler:
                      res = compiler.Compile()
                      result = {"errors": res.ErrorCount, "warnings": res.WarningCount}
      except Exception: pass
      try:
          for sub in item.DeviceItems: stack2.append(sub)
      except Exception: pass

  # HINWEIS: Vor Export immer pruefen ob Block konsistent ist.
  # Bei Fehler "Block is inconsistent": erst kompilieren, dann exportieren.
  # OB1 heisst in neuen Projekten oft "Main" — bei Suche beide Namen probieren.

  # Schreiben (mode='write')
  group = plc.BlockGroup.Groups.Create("Antriebe")
  table = plc.TagTableGroup.TagTables.Create("Standard_Tags")
  tag   = table.Tags.Create("Motor1_Start", "Bool")
  tag.LogicalAddress = "%M0.0"
  tag.Comment.Items[0].Text = "Startbefehl Motor 1"

## HMI Advanced (WinCC Advanced / Comfort)
  # Lesen
  for s in hmi.Screens: s.Name, s.Width, s.Height
  for table in hmi.TagTableGroup.TagTables:
      for tag in table.Tags:
          tag.Name, tag.DataTypeName, tag.HighLimit, tag.LowLimit, tag.LoggingEnabled
  for alarm in hmi.DiscreteAlarms: alarm.Name, alarm.AlarmClass, alarm.TriggerTag
  for alarm in hmi.AnalogAlarms:   alarm.Name, alarm.AlarmClass
  for tl in hmi.TextLists:
      for e in tl.TextListEntries: e.Value, e.Text

  # Schreiben (mode='write')
  table  = hmi.TagTableGroup.TagTables.Create("Antriebe")
  tag    = table.Tags.Create("Motor1_Drehzahl", "Int")
  tag.HighLimit      = 3000
  tag.LowLimit       = 0
  tag.LoggingEnabled = True
  tag.Comment        = "Drehzahl Motor 1 in U/min"
  screen = hmi.Screens.Create("Startbild")
  screen.Width = 1280;  screen.Height = 1024
  alarm_class = hmi.AlarmClasses.Create("Stoerung")
  alarm = hmi.DiscreteAlarms.Create("Motor1_Ueberlast")

## HMI Unified (WinCC Unified)
  # Struktur aehnlich Advanced, andere Namespaces
  for table in hmi.TagTableGroup.TagTables:
      for tag in table.Tags: tag.Name, tag.DataTypeName
  for s in hmi.Screens: s.Name

  # Schreiben (mode='write')
  table = hmi.TagTableGroup.TagTables.Create("Antriebe")
  tag   = table.Tags.Create("Motor1_Drehzahl", "Int")
  screen = hmi.Screens.Create("Startbild")

## Projektbibliothek
  lib = project.ProjectLibrary
  for t in lib.TypeFolder.Types:
      t.Name
      t.DefaultVersion.VersionNumber
      for v in t.Versions: v.VersionNumber, v.State  # InWork / Released
  for mc in lib.MasterCopyFolder.MasterCopies: mc.Name

  # Schreiben (mode='write')
  folder   = lib.TypeFolder.Folders.Create("Antriebe")
  new_type = lib.TypeFolder.Types.Create("FB_Antrieb")

## Projekt speichern
  project.Save()
  result = {"status": "ok", "saved": project.Name}

## Hardware-Katalog (V21)
  # WICHTIG: project.HwCatalog existiert in V21 nicht!
  # Korrekter Zugriffspfad:
  entries = portal.HardwareCatalog.Find("IPC277")   # Suche nach Begriff
  for e in entries:
      ti  = e.GetAttribute("TypeIdentifier")
      name = e.GetAttribute("TypeName")
      ver  = e.GetAttribute("Version")

  # Geraet anlegen
  device = project.Devices.CreateWithItem(typeIdentifier, deviceName, stationName)
  # Beispiel IPC277G Advanced:
  # typeIdentifier = "OrderNumber:6AV7886-vvxxx-xxxx//12inch"
  # Beispiel MTP1200 Unified Comfort V21:
  # typeIdentifier = "OrderNumber:6AV2 128-3MB06-0AXx/21.0.1.0"

# Regeln

1. Reihenfolge: connect_portal → open_project → dann alle anderen Tools
2. HMI-Typ: "Unified" in type(sw).__name__ → Unified, sonst Advanced
3. Ergebnis immer setzen: result = {"status": "ok", ...}
4. Attribute absichern: value = getattr(obj, "attr", None)
5. Nach schreibenden Operationen project.Save() empfehlen
6. Bei Unklarheit (Geraetename?) nachfragen bevor ausfuehren

# Workflow: Standardstruktur anlegen

  get_standard_template()         → Vorlage anzeigen und Platzhalter ersetzen
  list_devices()                  → vorhandene Geraete und Typen pruefen
  execute_openness(mode='write')  → Struktur schrittweise anlegen
  execute_openness(mode='write')  → project.Save()
"""

_STANDARD_TEMPLATE = """
Lege folgende Standardstruktur im geoeffneten Projekt an:

## PLC: [PLC_NAME]

### Bausteinordner
- Antriebe
- Pumpen
- Allgemein

### Tag-Tabellen
- Standard_Tags
- Merker

---

## HMI: [HMI_NAME]

### Tag-Tabellen
Tabelle: Antriebe
  - Motor1_Drehzahl  | Int  | High: 3000 | Low: 0    | Archiv: ja
  - Motor1_Temp      | Real | High: 120  | Low: 0    | Archiv: ja
  - Motor1_Status    | Bool |            |           | Archiv: nein

Tabelle: Pumpen
  - Pumpe1_Druck     | Real | High: 10   | Low: 0    | Archiv: ja
  - Pumpe1_Laufzeit  | DWord|            |           | Archiv: nein

### Screens
- Startbild   (1280x1024)
- Antriebe    (1280x1024)
- Pumpen      (1280x1024)
- Alarme      (1280x1024)

### Alarmklassen
- Stoerung
- Warnung

---

## Projektbibliothek

### Ordner
- Antriebe
- Pumpen
- Allgemein

---

Danach Projekt speichern.
"""

# ── Prompt Resource ────────────────────────────────────────────────────────────

@server.list_prompts()
async def list_prompts():
    return [types.Prompt(name="tia-assistant",
                         description="TIA Portal Openness Assistent V21")]

@server.get_prompt()
async def get_prompt(name, arguments=None):
    return types.GetPromptResult(
        description="TIA Portal Openness Assistent",
        messages=[types.PromptMessage(role="user",
            content=types.TextContent(type="text", text=_PROMPT))])

# ── Tools ──────────────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools():
    def T(name, desc, props=None, req=None):
        schema = {"type":"object","properties":props or {}}
        if req: schema["required"] = req
        return types.Tool(name=name, description=desc, inputSchema=schema)

    return [
        T("connect_portal",  "TIA Portal verbinden.",
          {"mode":{"type":"string","enum":["attach","headless","gui"],"default":"attach"}}),
        T("attach_project",  "Bereits in TIA Portal geoeffnetes Projekt uebernehmen. Kein Pfad noetig."),
        T("open_project",    "Projekt oeffnen (.ap21).",
          {"path":{"type":"string"}}, ["path"]),
        T("get_session_status", "Verbindungsstatus."),
        T("get_project_info",   "Projektinfo und Geraete."),
        T("list_devices",       "Alle Geraete mit HMI-Typ."),
        T("list_hmi_screens",   "Screens eines HMI.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_tags",      "Tags eines HMI, optional nach Tabelle.",
          {"device_name":{"type":"string"},"table_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_alarms",    "Alarme eines HMI.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_textlists", "Textlisten eines HMI.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("export_hmi_screen",  "Screen als XML exportieren.",
          {"device_name":{"type":"string"},"screen_name":{"type":"string"},
           "output_path":{"type":"string"}}, ["device_name","screen_name","output_path"]),
        T("export_hmi_tags",    "Alle HMI-Tags als XML exportieren.",
          {"device_name":{"type":"string"},"output_path":{"type":"string"}},
          ["device_name","output_path"]),
        T("list_libraries",     "Alle Bibliotheken im Projekt."),
        T("list_library_types", "Typen einer Bibliothek mit Versionen.",
          {"library_name":{"type":"string"}}, ["library_name"]),
        T("list_master_copies", "Master Copies einer Bibliothek.",
          {"library_name":{"type":"string"}}, ["library_name"]),
        T("get_library_type_versions", "Versionen eines Bibliothekstyps.",
          {"library_name":{"type":"string"},"type_name":{"type":"string"}},
          ["library_name","type_name"]),
        T("execute_openness",
          "Python-Code direkt gegen TIA Openness ausfuehren.\n"
          "Kontext: portal, project, eng, find_software(name,hint), safe_str, collect\n"
          "Ergebnis in 'result' schreiben. mode='read'|'write'",
          {"code":{"type":"string"},"mode":{"type":"string","enum":["read","write"],"default":"read"}},
          ["code"]),
        T("get_standard_template",
          "Vorlage fuer Standardstruktur (PLC, HMI, Bibliothek). "
          "Namen anpassen und ausfuehren lassen."),

        # PLC KOMPILIEREN
        T("compile_plc",
          "SPS kompilieren. Behebt inkonsistente Bausteine vor dem Export. "
          "Bei Fehler 'Block is inconsistent' zuerst compile_plc aufrufen.",
          {"device_name":{"type":"string"}}, ["device_name"]),

        # PLC EXPORT / IMPORT
        T("export_plc_block",
          f"Baustein als XML exportieren. Standard-Exportpfad: {_DEFAULT_EXPORT}",
          {"device_name":{"type":"string"},"block_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: anderer Exportpfad"}},
          ["device_name","block_name"]),
        T("import_plc_block",
          "Baustein aus XML-Datei importieren (Override).",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),
        T("get_plc_block_source",
          "Baustein exportieren und Quellcode anzeigen. "
          "SCL-Bloecke: lesbarer SCL-Code + .scl Datei. LAD/FBD: XML.",
          {"device_name":{"type":"string"},"block_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: anderer Exportpfad"}},
          ["device_name","block_name"]),

        # PLC TAG-TABELLEN
        T("export_plc_tagtable",
          f"PLC Tag-Tabelle als XML exportieren. Standard: {_DEFAULT_EXPORT}",
          {"device_name":{"type":"string"},"table_name":{"type":"string"},
           "output_path":{"type":"string"}},
          ["device_name","table_name"]),
        T("import_plc_tagtable",
          "PLC Tag-Tabelle aus XML importieren.",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),

        # HMI EXPORT / IMPORT
        T("export_hmi_tagtable",
          f"HMI Tag-Tabelle als XML exportieren. Standard: {_DEFAULT_EXPORT}",
          {"device_name":{"type":"string"},"table_name":{"type":"string"},
           "output_path":{"type":"string"}},
          ["device_name","table_name"]),
        T("import_hmi_tagtable",
          "HMI Tag-Tabelle aus XML importieren.",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),
        T("import_hmi_screen",
          "HMI Screen aus XML importieren.",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),

        # DATEI-HILFSFUNKTIONEN
        T("write_import_file",
          "Schreibt Dateiinhalt in den Import-Ordner. "
          "Verwenden wenn der Nutzer eine XML-Datei hochgeladen hat "
          "und sie importiert werden soll. "
          f"Zielordner: {_DEFAULT_EXPORT}\\import\\",
          {"filename":{"type":"string","description":"Dateiname z.B. FB_Motor.xml"},
           "content": {"type":"string","description":"Dateiinhalt (XML-Text)"}},
          ["filename","content"]),
        T("read_export_file",
          "Liest eine exportierte Datei und gibt den Inhalt zurueck. "
          "Damit kann Claude exportierte Bausteine oder Tags im Chat anzeigen.",
          {"file_path":{"type":"string"}},
          ["file_path"]),

        # PLC LESEN (JSON — kein Export noetig)
        T("list_plc_blocks",
          "Alle Bausteine der PLC als JSON. "
          "Felder: name, number, type (OB/FC/FB/DB/UDT), language, path (Ordner). "
          "group_path optional: nur eine Gruppe lesen, z.B. 'Antriebe' oder 'Antriebe/Pumpen'. "
          "Vor export_plc_block aufrufen um verfuegbare Namen zu kennen.",
          {"device_name": {"type": "string"},
           "group_path":  {"type": "string",
                           "description": "Optional: Unterordner filtern, z.B. 'Antriebe'"}},
          ["device_name"]),

        T("list_plc_tag_tables",
          "Alle PLC Tag-Tabellen mit Name und Tag-Anzahl. "
          "Aufrufen bevor list_plc_tags oder export_plc_tagtable, "
          "um verfuegbare Tabellennamen zu kennen.",
          {"device_name": {"type": "string"}},
          ["device_name"]),

        T("list_plc_tags",
          "PLC-Tags direkt als JSON (kein XML-Export). "
          "Felder: name, data_type, logical_address, comment, table. "
          "table_name optional: nur eine Tabelle lesen. Leer = alle Tabellen.",
          {"device_name": {"type": "string"},
           "table_name":  {"type": "string",
                           "description": "Optional: nur diese Tabelle lesen"}},
          ["device_name"]),

        T("save_project",
          "Aktuelles Projekt speichern (project.Save()). "
          "Nach allen schreibenden Operationen aufrufen."),
    ]

# ── Dispatch ───────────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name, arguments):
    import logging
    log = logging.getLogger("tia.server")
    a = arguments or {}
    log.info(f"Tool: {name}  keys={list(a.keys())}")
    try:
        result = _dispatch(name, a)
        return [types.TextContent(type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2))]
    except TiaError as e:
        log.warning(f"{name} → {e.code}: {e.message}")
        return [types.TextContent(type="text",
                text=json.dumps(e.to_dict(), ensure_ascii=False, indent=2))]
    except Exception as e:
        log.error(f"{name} → {e}", exc_info=True)
        return [types.TextContent(type="text",
                text=json.dumps({"status":"error","code":"UNEXPECTED","message":str(e),"tool":name},
                                ensure_ascii=False, indent=2))]

def _dispatch(name, a):
    match name:
        case "connect_portal":             return tia.connect_portal(a.get("mode","attach"))
        case "attach_project":             return tia.attach_project()
        case "open_project":               return tia.open_project(a["path"])
        case "get_session_status":         return tia.get_session_status()
        case "get_project_info":           return tia.get_project_info()
        case "list_devices":               return tia.list_devices()
        case "list_hmi_screens":           return tia.list_hmi_screens(a["device_name"])
        case "list_hmi_tags":              return tia.list_hmi_tags(a["device_name"],a.get("table_name"))
        case "list_hmi_alarms":            return tia.list_hmi_alarms(a["device_name"])
        case "list_hmi_textlists":         return tia.list_hmi_textlists(a["device_name"])
        case "export_hmi_screen":          return tia.export_hmi_screen(a["device_name"],a["screen_name"],a["output_path"])
        case "export_hmi_tags":            return tia.export_hmi_tags(a["device_name"],a["output_path"])
        case "list_libraries":             return tia.list_libraries()
        case "list_library_types":         return tia.list_library_types(a["library_name"])
        case "list_master_copies":         return tia.list_master_copies(a["library_name"])
        case "get_library_type_versions":  return tia.get_library_type_versions(a["library_name"],a["type_name"])
        case "execute_openness":           return tia.execute_openness(a["code"],a.get("mode","read"))
        case "get_standard_template":      return {"template": _STANDARD_TEMPLATE}
        case "compile_plc":                return tia.compile_plc(a["device_name"])
        case "export_plc_block":           return tia.export_plc_block(a["device_name"],a["block_name"],a.get("output_path"))
        case "import_plc_block":           return tia.import_plc_block(a["device_name"],a["file_path"])
        case "get_plc_block_source":       return tia.get_plc_block_source(a["device_name"],a["block_name"],a.get("output_path"))
        case "export_plc_tagtable":        return tia.export_plc_tagtable(a["device_name"],a["table_name"],a.get("output_path"))
        case "import_plc_tagtable":        return tia.import_plc_tagtable(a["device_name"],a["file_path"])
        case "export_hmi_tagtable":        return tia.export_hmi_tagtable(a["device_name"],a["table_name"],a.get("output_path"))
        case "import_hmi_tagtable":        return tia.import_hmi_tagtable(a["device_name"],a["file_path"])
        case "import_hmi_screen":          return tia.import_hmi_screen(a["device_name"],a["file_path"])
        case "write_import_file":          return tia.write_import_file(a["filename"],a["content"])
        case "read_export_file":           return tia.read_export_file(a["file_path"])
        case "list_plc_blocks":            return tia.list_plc_blocks(a["device_name"],a.get("group_path"))
        case "list_plc_tag_tables":        return tia.list_plc_tag_tables(a["device_name"])
        case "list_plc_tags":              return tia.list_plc_tags(a["device_name"],a.get("table_name"))
        case "save_project":               return tia.save_project()
        case _: raise TiaError("UNKNOWN_TOOL",f"Unbekanntes Tool: {name}",False)

# ── Entry Point ────────────────────────────────────────────────────────────────

async def main():
    _acquire_lock()                  # Blockiert sofort falls eine Instanz laeuft
    tia.setup()
    import logging
    logging.getLogger("tia.server").info("MCP Server startet")
    try:
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
    finally:
        tia.teardown()
        _release_lock()

if __name__ == "__main__":
    asyncio.run(main())
