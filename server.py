"""
server.py — TIA Portal MCP Server
Einstiegspunkt. Startet mit: python server.py
Claude Desktop: %APPDATA%\Claude\claude_desktop_config.json
  { "mcpServers": { "tia-portal": { "command":"python",
    "args":["C:/tia-mcp/server.py"], "cwd":"C:/tia-mcp" } } }
"""

import json, asyncio, socket, sys, os, threading
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import tia
from tia import TiaError, _DEFAULT_EXPORT
import base64

# ═══════════════════════════════════════════════════════════════════════════════
# VERSION
# ═══════════════════════════════════════════════════════════════════════════════
VERSION      = "1.12.0"
VERSION_DATE = "2026-06-16"

# ── Primär / Proxy Architektur ─────────────────────────────────────────────────
# Erste Instanz wird "primär": bindet Port 47823 als JSON-RPC TCP-Server und
# führt alle TIA Openness COM-Aufrufe aus (COM ist Single-Threaded).
# Weitere Instanzen werden "proxy": verbinden sich mit dem Primär und leiten
# alle MCP Tool-Calls durch. Beide laufen als vollwertiger MCP stdio-Server.

_RPC_PORT   = 47823
_is_primary = False
_rpc_server = None
_com_lock   = None          # asyncio.Lock — serialisiert COM-Zugriffe im Primär

# ── Background-Task ────────────────────────────────────────────────────────────
# Lange TIA-Operationen (open_project, create_project, compile_plc) laufen in
# einem Thread und geben sofort "pending" zurück. get_session_status zeigt den
# aktuellen Stand. Nur im Primär relevant.

_LONG_RUNNING = {"open_project", "create_project", "compile_plc", "close_portal"}

_bg_lock   = threading.Lock()
_bg_status = {"running": False, "tool": None, "result": None, "error": None}


async def _rpc_handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Primär: eingehende RPC-Anfrage von einer Proxy-Instanz bearbeiten."""
    try:
        data = await reader.readline()
        if not data:
            return
        req  = json.loads(data)
        tool, args = req["tool"], req.get("args", {})
        if tool in _LONG_RUNNING:
            result = _start_bg(tool, args)
        else:
            result = _dispatch(tool, args)
        response = json.dumps({"ok": True, "result": result}, ensure_ascii=False)
    except TiaError as e:
        response = json.dumps({"ok": False, "error": e.to_dict()}, ensure_ascii=False)
    except Exception as e:
        response = json.dumps({"ok": False, "error": {
            "status": "error", "code": "UNEXPECTED", "message": str(e)
        }}, ensure_ascii=False)
    finally:
        try:
            writer.write(response.encode() + b"\n")
            await writer.drain()
            writer.close()
        except Exception:
            pass


async def _rpc_call(name: str, args: dict):
    """Proxy: Tool-Aufruf an den Primär weiterleiten."""
    reader, writer = await asyncio.open_connection("127.0.0.1", _RPC_PORT)
    try:
        req = json.dumps({"tool": name, "args": args}, ensure_ascii=False) + "\n"
        writer.write(req.encode())
        await writer.drain()
        data = await reader.readline()
        resp = json.loads(data)
        if resp["ok"]:
            return resp["result"]
        err = resp["error"]
        raise TiaError(err.get("code", "PROXY_ERROR"), err.get("message", str(err)), False)
    finally:
        writer.close()


def _start_bg(name: str, args: dict) -> dict:
    """Startet eine lange Operation im Background-Thread. Sofortige Rückkehr."""
    with _bg_lock:
        if _bg_status["running"]:
            return {"status": "busy", "message": f"Läuft bereits: {_bg_status['tool']}. Warte auf Abschluss."}
        _bg_status.update({"running": True, "tool": name, "result": None, "error": None})

    def _run():
        try:
            r = _dispatch(name, args)
            with _bg_lock:
                _bg_status.update({"running": False, "result": r, "error": None})
        except TiaError as e:
            with _bg_lock:
                _bg_status.update({"running": False, "result": None, "error": e.to_dict()})
        except Exception as e:
            with _bg_lock:
                _bg_status.update({"running": False, "result": None,
                                   "error": {"status": "error", "code": "UNEXPECTED", "message": str(e)}})

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "pending", "tool": name,
            "message": "Läuft im Hintergrund. get_session_status aufrufen um Fortschritt zu prüfen."}


async def _start_primary() -> bool:
    """Versucht primäre Instanz zu werden. True = primär, False = proxy."""
    global _is_primary, _rpc_server, _com_lock
    try:
        srv = await asyncio.start_server(_rpc_handle_client, "127.0.0.1", _RPC_PORT)
        _rpc_server = srv
        _is_primary = True
        _com_lock   = asyncio.Lock()
        return True
    except OSError:
        _is_primary = False
        return False


def _stop_primary():
    global _rpc_server
    if _rpc_server:
        _rpc_server.close()
        _rpc_server = None


server = Server("tia-portal")

# ── System Prompt ──────────────────────────────────────────────────────────────

_PROMPT = """
Du bist ein TIA Portal Engineering-Assistent mit direktem Zugriff auf
TIA Portal V21 ueber die Openness API. Du kannst Projekte lesen, analysieren
und Standardstrukturen anlegen (PLC, HMI Advanced/Unified, Bibliotheken).

# Verfuegbare Tools

## Session
  # TIA Portal laeuft noch nicht:
  open_portal(mode)        → TIA Portal starten: gui (mit Oberflaeche) / headless
  open_project(path)       → Projekt oeffnen; wartet automatisch bis TIA bereit ist

  # TIA Portal laeuft bereits:
  connect_portal()         → Laufende TIA Portal Instanz uebernehmen (attach)
  attach_project()         → Bereits geoeffnetes Projekt uebernehmen

  # Lifecycle Ende:
  save_project()           → Projekt speichern
  close_project()          → Projekt schliessen (vorher save_project aufrufen)
  close_portal()           → TIA Portal beenden (vorher close_project aufrufen)

  get_session_status()     → Verbindungs- und Projektstatus pruefen

## Projekt lesen
  get_project_info()       → Name, Pfad, Geraete
  list_devices()           → Alle Geraete mit erkanntem Typ (PLC / Advanced / Unified)

## PLC Export / Import
  compile_plc(device)                          → SPS kompilieren
  export_plc_block(device, block, path?)       → Baustein als XML exportieren
  import_plc_block(device, file_path)          → Baustein aus XML importieren
  get_plc_block_source(device, block, path?)   → Quellcode lesen (SCL: Text, LAD/FBD: XML)
  set_plc_block_source(device, block, scl)     → SCL-Quellcode direkt schreiben
  export_plc_tagtable(device, table, path?)    → PLC Tag-Tabelle exportieren
  import_plc_tagtable(device, file_path)       → PLC Tag-Tabelle importieren

## HMI lesen
  list_hmi_screens(device)            → Alle Bilder mit Groesse und Elementanzahl
  list_hmi_tags(device, table?)       → Tags mit Datentyp, High/Low-Limit, Archivierung
  list_hmi_alarms(device)             → Diskrete und analoge Alarme mit Alarmklasse
  list_hmi_textlists(device)          → Textlisten mit Eintraegen

## HMI Export / Import
  export_hmi_screen(device, screen, path)       → Bild als XML exportieren
  export_hmi_screens_all(device, path?)         → Alle Screens auf einmal exportieren
  import_hmi_screen(device, file_path)          → Bild aus XML importieren
  export_hmi_tags(device, output_path?)         → Alle Tag-Tabellen exportieren (V21: Ordner, V19/V20: XML)
  import_hmi_tags(device, file_path)            → Tags aus Datei/Ordner importieren
  export_hmi_tagtable(device, table, path?)     → Einzelne Tag-Tabelle exportieren
  import_hmi_tagtable(device, file_path)        → Einzelne Tag-Tabelle importieren (Datei oder Ordner)
  export_hmi_scripts(device, path?)             → HMI-Scripts exportieren
  import_hmi_scripts(device, file_path)         → HMI-Scripts importieren
  export_hmi_alarms(device, output_path?)       → Alarme als XML exportieren
  import_hmi_alarms(device, file_path)          → Alarme aus XML importieren
  export_hmi_textlists(device, output_path?)    → Textlisten als XML exportieren
  import_hmi_textlists(device, file_path)       → Textlisten aus XML importieren

## Bibliothek lesen
  list_libraries()                         → Projekt- und globale Bibliotheken
  list_library_types(lib)                  → Typen mit allen Versionen und Standardversion
  list_master_copies(lib)                  → Master Copies (rekursiv)
  get_library_type_versions(lib, type)     → Versionen eines einzelnen Typs

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

1. Reihenfolge (TIA nicht offen): open_portal → open_project → Tools → save_project → close_project → close_portal
   Reihenfolge (TIA bereits offen): connect_portal → attach_project oder open_project → Tools
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
        T("create_project",
          "Neues TIA Portal Projekt anlegen. Läuft im Hintergrund — get_session_status zum Prüfen. "
          "path = Zielordner (wird angelegt), name = Projektname (optional, Standard: Ordnername).",
          {"path": {"type": "string"}, "name": {"type": "string"}},
          ["path"]),
        T("open_portal",
          "TIA Portal starten — neuen Prozess erzeugen. "
          "mode='gui': mit Oberflaeche (Standard). "
          "mode='headless': ohne Oberflaeche, fuer Overnight-Workflows. "
          "Danach open_project() aufrufen — Retry-Logik wartet automatisch.",
          {"mode":{"type":"string","enum":["gui","headless"],"default":"gui"}}),
        T("connect_portal",
          "Laufende TIA Portal Instanz uebernehmen (attach). "
          "TIA Portal muss bereits offen sein — sonst open_portal() verwenden."),
        T("attach_project",  "Bereits in TIA Portal geoeffnetes Projekt uebernehmen. Kein Pfad noetig."),
        T("open_project",    "Projekt oeffnen (.ap21). "
          "Nach open_portal() automatisch auf TIA Portal warten (Retry-Logik).",
          {"path":{"type":"string"},
           "retries":{"type":"integer","default":10,
                      "description":"Anzahl Versuche falls TIA noch startet (default 10)"},
           "retry_delay":{"type":"integer","default":10,
                          "description":"Sekunden zwischen Versuchen (default 10)"}},
          ["path"]),
        T("save_project",  "Aktuelles Projekt speichern. Immer vor close_project aufrufen."),
        T("close_project", "Aktuelles Projekt schliessen (ohne Speichern). "
          "Vorher save_project aufrufen."),
        T("close_portal",  "TIA Portal beenden (Dispose). "
          "Schliesst alle Projekte und beendet den TIA-Prozess. "
          "Vorher save_project und close_project aufrufen."),
        T("get_session_status", "Verbindungsstatus."),
        T("get_version", "Versionen von server.py und tia.py mit Changelog."),
        T("get_project_info",   "Projektinfo und Geraete."),
        T("list_devices",       "Alle Geraete mit HMI-Typ."),
        T("get_hmi_config",
          "HMI-Gerätekonfiguration auslesen — funktioniert für Advanced UND Unified. "
          "Liest alle DeviceItem-Attribute (IP, Display, Runtime, Kommunikation …). "
          "Bei Unified zusätzlich RuntimeSettings als separates Feld.",
          {"device_name": {"type": "string"}}, ["device_name"]),
        T("set_hmi_config",
          "HMI-Gerätekonfiguration schreiben — Advanced und Unified. "
          "Schreibt DeviceItem-Attribute; bei Unified auch RuntimeSettings-Keys. "
          "Schreibgeschützte Attribute (Name, OrderNumber …) werden übersprungen. "
          "Vorher get_hmi_config aufrufen um verfügbare Schlüssel zu sehen.",
          {"device_name": {"type": "string"},
           "settings":    {"type": "object", "description": "Key-Value-Paare"}},
          ["device_name", "settings"]),
        T("export_hmi_config",
          "HMI-Gerätekonfiguration als Excel exportieren — Advanced und Unified. "
          "Advanced: ein Sheet mit gruppierten DeviceItem-Attributen (blau). "
          "Unified: erstes Sheet DeviceItem-Attribute (grün), zweites Sheet RuntimeSettings. "
          f"Standard: {_DEFAULT_EXPORT}\\hmi_config_<device>.xlsx",
          {"device_name":  {"type": "string"},
           "output_path":  {"type": "string", "description": "Optional: anderer Exportpfad (.xlsx)"}},
          ["device_name"]),
        T("get_hmi_runtime_settings",
          "HMI Runtime-Einstellungen auslesen (nur WinCC Unified). "
          "Gibt alle Einstellungen rekursiv als JSON zurück. "
          "Kann als Basis für set_hmi_runtime_settings verwendet werden.",
          {"device_name": {"type": "string"}}, ["device_name"]),
        T("set_hmi_runtime_settings",
          "HMI Runtime-Einstellungen schreiben (nur WinCC Unified). "
          "settings = dict mit Schlüssel/Wert-Paaren (nur einfache Werte, keine Unterstrukturen). "
          "Vorher get_hmi_runtime_settings aufrufen um verfügbare Schlüssel zu sehen.",
          {"device_name": {"type": "string"},
           "settings":    {"type": "object", "description": "Key-Value-Paare z.B. {\"StartScreen\": \"Startbild\", \"GMPEnabled\": true}"}},
          ["device_name", "settings"]),
        T("export_hmi_runtime_settings",
          "HMI Runtime-Einstellungen als Excel exportieren (nur WinCC Unified). "
          f"Standard: {_DEFAULT_EXPORT}\\hmi_runtime_<device>.xlsx",
          {"device_name":  {"type": "string"},
           "output_path":  {"type": "string", "description": "Optional: anderer Exportpfad (.xlsx)"}},
          ["device_name"]),
        T("get_plc_config",
          "Alle Konfigurationsattribute einer SPS (CPU) auslesen. "
          "Liefert Zykluszeiten, Startup-Verhalten, Zeitzone, Netzwerk, SNMP, OPC UA, Webserver u.v.m.",
          {"device_name": {"type": "string", "description": "Name des CPU-DeviceItems z.B. 'PLC_1'"}},
          ["device_name"]),
        T("set_plc_config",
          "Konfigurationsattribute einer SPS schreiben. "
          "Vorher get_plc_config aufrufen um verfügbare Schlüssel zu sehen. "
          "Schreibgeschützte Attribute (z.B. OrderNumber, FirmwareVersion) werden automatisch übersprungen.",
          {"device_name": {"type": "string"},
           "settings":    {"type": "object", "description": "Key-Value-Paare z.B. {\"WebserverActivate\": true}"}},
          ["device_name", "settings"]),
        T("export_plc_config",
          "SPS-Konfiguration als Excel-Datei exportieren, gruppiert nach Kategorien "
          "(Allgemein, Zyklus, Startup, Zeitzone, Netzwerk, OPC UA, Sicherheit usw.). "
          f"Standard: {_DEFAULT_EXPORT}\\plc_config_<device>.xlsx",
          {"device_name":  {"type": "string"},
           "output_path":  {"type": "string", "description": "Optional: anderer Exportpfad (.xlsx)"}},
          ["device_name"]),
        T("export_hw_config",
          "Hardware-Konfiguration aller Geraete als Excel exportieren. "
          "Liefert Station, Komponente, Bestellnummer, Steckplatz, IP-Adresse. "
          f"Standard-Exportpfad: {_DEFAULT_EXPORT}\\hardware_config.xlsx",
          {"output_path": {"type": "string", "description": "Optional: anderer Exportpfad (.xlsx)"}}),
        T("list_hmi_screens",   "Screens eines HMI.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_tags",      "Tags eines HMI, optional nach Tabelle.",
          {"device_name":{"type":"string"},"table_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_alarms",    "Alarme eines HMI.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_logs",
          "HMI-Datenlogs auflisten (Unified). "
          "Liefert Name, Segmentgröße, Speicherdauer, Speicherort und Backup-Einstellungen.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("set_hmi_log",
          "Einstellungen eines HMI-Datenlogs schreiben (Unified). "
          "Schreibbare Felder: Name, SegmentMaxSize, SegmentStartTime, LogMaxSize, StorageDevice, StorageFolder. "
          "Vorher list_hmi_logs aufrufen um Log-Namen zu sehen.",
          {"device_name": {"type": "string"},
           "log_name":    {"type": "string", "description": "Name des zu ändernden DataLogs"},
           "settings":    {"type": "object", "description": "z.B. {\"LogMaxSize\": \"2000\", \"StorageFolder\": \"/logs\"}"}},
          ["device_name", "log_name", "settings"]),
        T("list_hmi_connections",
          "HMI-Verbindungen auflisten inkl. DriverProperties (IP-Adressen etc.). "
          "Hinweis: Integrierte Verbindungen sind in V21 nicht zugänglich.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("export_hmi_connections",
          "HMI-Verbindungen als JSON exportieren (alle Attribute + DriverProperties). "
          "Gegenstück zu import_hmi_connections.",
          {"device_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: Zieldatei (.json)"}},
          ["device_name"]),
        T("import_hmi_connections",
          "HMI-Verbindungen aus JSON importieren. Schreibbare Felder (Name, IP, Treiber …) "
          "werden gesetzt, Read-only-Felder (Node, Partner, Station) übersprungen.",
          {"device_name":{"type":"string"}, "file_path":{"type":"string"}},
          ["device_name","file_path"]),
        T("list_hmi_textlists", "Textlisten eines HMI (Advanced und Unified).",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_cycles",
          "Erfassungszyklen eines HMI auflisten (z.B. 100ms, 1s, 10s). "
          "Advanced: sw.CycleFolder.Cycles. Unified: sw.Cycles. "
          "Gibt Name, Periode, Einheit und Kommentar zurück.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("list_hmi_scheduled_tasks",
          "Geplante Tasks eines HMI auflisten (zeitgesteuerte Funktionsaufrufe). "
          "Advanced: sw.ScheduledTaskFolder.ScheduledTasks. "
          "Gibt Name, Trigger-Typ, Intervall, Funktionsname und Aktivierungsstatus zurück.",
          {"device_name":{"type":"string"}}, ["device_name"]),
        T("export_hmi_screen",  "Einzelnen HMI-Screen als XML exportieren.",
          {"device_name":{"type":"string"},"screen_name":{"type":"string"},
           "output_path":{"type":"string"}}, ["device_name","screen_name","output_path"]),
        T("export_hmi_screens_all",
          "Alle HMI-Screens auf einmal exportieren. output_path = Zielordner (optional).",
          {"device_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: Zielordner"}},
          ["device_name"]),
        T("export_hmi_scripts",
          "HMI-Scripts (VB/JS) exportieren. output_path = Zielordner (optional).",
          {"device_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: Zielordner"}},
          ["device_name"]),
        T("import_hmi_scripts",
          "HMI-Scripts aus Datei oder Ordner importieren. Gegenstück zu export_hmi_scripts.",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),
        T("export_hmi_tags",    "Alle HMI-Tags exportieren (V21: DirectoryInfo, V19/V20: XML). output_path = Zielordner (optional).",
          {"device_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: Zielordner"}},
          ["device_name"]),
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

        # PLC LESEN
        T("list_plc_blocks",
          "Alle PLC-Bausteine auflisten (OB, FC, FB, DB) inkl. Untergruppen. "
          "Rückgabe: name, type, language, number, group, is_consistent. "
          "Optionaler Filter: group='Antriebe' liefert nur Bausteine dieser Gruppe.",
          {"device_name":{"type":"string"},
           "group":{"type":"string","description":"Optional: Gruppenname filtern"}},
          ["device_name"]),

        T("list_plc_tag_tables",
          "Alle PLC-Tag-Tabellen auflisten inkl. Untergruppen. "
          "Rückgabe: name, group, tag_count. Voraussetzung für list_plc_tags und export_plc_tagtable.",
          {"device_name":{"type":"string"}}, ["device_name"]),

        T("list_plc_tags",
          "Alle Tags einer PLC-Tag-Tabelle auflisten. "
          "Rückgabe: name, data_type, logical_address, comment. "
          "table_name aus list_plc_tag_tables entnehmen.",
          {"device_name":{"type":"string"},"table_name":{"type":"string"}},
          ["device_name","table_name"]),

        T("list_plc_udts",
          "Alle PLC-UDTs (Strukturen/Typen) auflisten inkl. Untergruppen. "
          "Rückgabe: name, type (PlcStruct/PlcTypedeF), group, is_consistent.",
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
        T("create_hmi_structure",
          "Ordnerstruktur im HMI anlegen (Bilder und Tag-Tabellen). "
          "Funktioniert für WinCC Advanced und Unified.",
          {"device_name": {"type":"string"},
           "structure":   {"type":"object",
                           "description":
                             "Dict mit 'screens' und/oder 'tag_tables'. "
                             "Wert: Liste aus Strings oder {\"Ordner\":[\"Kind1\",\"Kind2\"]}.",
                           "properties": {
                             "screens":    {"type":"array"},
                             "tag_tables": {"type":"array"}
                           }}},
          ["device_name","structure"]),
        T("import_hmi_tags",
          "Alle HMI-Tags aus XML importieren. Gegenstück zu export_hmi_tags.",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),
        T("export_hmi_alarms",
          "HMI-Alarme als XML exportieren. Gegenstück zu import_hmi_alarms.",
          {"device_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: Zieldatei"}},
          ["device_name"]),
        T("import_hmi_alarms",
          "HMI-Alarme aus XML importieren. Gegenstück zu export_hmi_alarms.",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),
        T("export_hmi_textlists",
          "HMI-Textlisten als XML exportieren. Gegenstück zu import_hmi_textlists.",
          {"device_name":{"type":"string"},
           "output_path":{"type":"string","description":"Optional: Zieldatei"}},
          ["device_name"]),
        T("import_hmi_textlists",
          "HMI-Textlisten aus XML importieren. Gegenstück zu export_hmi_textlists.",
          {"device_name":{"type":"string"},"file_path":{"type":"string"}},
          ["device_name","file_path"]),
        T("set_plc_block_source",
          "SCL-Quellcode direkt in einen Baustein schreiben. Gegenstück zu get_plc_block_source. "
          "Nur für SCL-Bausteine. scl_source = SCL-Code als String.",
          {"device_name":{"type":"string"},"block_name":{"type":"string"},
           "scl_source":{"type":"string","description":"SCL-Quellcode als String"}},
          ["device_name","block_name","scl_source"]),

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
        T("restart_server",
          "MCP Server neu starten. "
          "Der primaere Prozess beendet sich sauber (TIA Verbindung wird getrennt), "
          "Claude Code startet ihn automatisch neu. "
          "Proxy-Instanzen verbinden sich beim naechsten Aufruf selbst wieder."),
    ]

# ── Dispatch ───────────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name, arguments):
    import logging
    log = logging.getLogger("tia.server")
    a = arguments or {}
    mode = "primär" if _is_primary else "proxy"
    log.info(f"Tool [{mode}]: {name}  keys={list(a.keys())}")
    try:
        if _is_primary:
            if name in _LONG_RUNNING:
                result = _start_bg(name, a)
            else:
                async with _com_lock:
                    result = _dispatch(name, a)
        else:
            result = await _rpc_call(name, a)
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
        case "open_portal":                return tia.open_portal(a.get("mode","gui"))
        case "connect_portal":             return tia.connect_portal()
        case "attach_project":             return tia.attach_project()
        case "open_project":               return tia.open_project(a["path"],a.get("retries",10),a.get("retry_delay",10))
        case "save_project":               return tia.save_project()
        case "close_project":              return tia.close_project()
        case "close_portal":               return tia.close_portal()
        case "get_session_status":
            s = tia.get_session_status()
            with _bg_lock:
                bg = dict(_bg_status)
            if bg["running"]:
                s["background_task"] = {"running": True, "tool": bg["tool"]}
            elif bg["tool"] and not bg["running"]:
                s["background_task"] = {
                    "running": False, "tool": bg["tool"],
                    "result": bg["result"], "error": bg["error"]
                }
                _bg_status.update({"tool": None, "result": None, "error": None})
            return s
        case "get_version":                return {
                                               "server": {"version": VERSION, "date": VERSION_DATE, "file": __file__},
                                               "tia":    tia.VERSION_INFO,
                                               "match":  VERSION == tia.VERSION,
                                           }
        case "get_project_info":           return tia.get_project_info()
        case "list_devices":               return tia.list_devices()
        case "export_hw_config":                return tia.export_hw_config(a.get("output_path"))
        case "get_hmi_config":                  return tia.get_hmi_config(a["device_name"])
        case "set_hmi_config":                  return tia.set_hmi_config(a["device_name"], a["settings"])
        case "export_hmi_config":               return tia.export_hmi_config(a["device_name"], a.get("output_path"))
        case "get_hmi_runtime_settings":        return tia.get_hmi_runtime_settings(a["device_name"])
        case "set_hmi_runtime_settings":        return tia.set_hmi_runtime_settings(a["device_name"], a["settings"])
        case "export_hmi_runtime_settings":     return tia.export_hmi_runtime_settings(a["device_name"], a.get("output_path"))
        case "get_plc_config":                  return tia.get_plc_config(a["device_name"])
        case "set_plc_config":                  return tia.set_plc_config(a["device_name"], a["settings"])
        case "export_plc_config":               return tia.export_plc_config(a["device_name"], a.get("output_path"))
        case "list_hmi_screens":           return tia.list_hmi_screens(a["device_name"])
        case "list_hmi_tags":              return tia.list_hmi_tags(a["device_name"],a.get("table_name"))
        case "list_hmi_alarms":            return tia.list_hmi_alarms(a["device_name"])
        case "list_hmi_logs":              return tia.list_hmi_logs(a["device_name"])
        case "set_hmi_log":                return tia.set_hmi_log(a["device_name"], a["log_name"], a["settings"])
        case "list_hmi_connections":        return tia.list_hmi_connections(a["device_name"])
        case "export_hmi_connections":      return tia.export_hmi_connections(a["device_name"],a.get("output_path"))
        case "import_hmi_connections":      return tia.import_hmi_connections(a["device_name"],a["file_path"])
        case "list_hmi_textlists":         return tia.list_hmi_textlists(a["device_name"])
        case "list_hmi_cycles":            return tia.list_hmi_cycles(a["device_name"])
        case "list_hmi_scheduled_tasks":   return tia.list_hmi_scheduled_tasks(a["device_name"])
        case "export_hmi_screen":          return tia.export_hmi_screen(a["device_name"],a["screen_name"],a["output_path"])
        case "export_hmi_screens_all":     return tia.export_hmi_screens_all(a["device_name"],a.get("output_path"))
        case "export_hmi_scripts":         return tia.export_hmi_scripts(a["device_name"],a.get("output_path"))
        case "import_hmi_scripts":         return tia.import_hmi_scripts(a["device_name"],a["file_path"])
        case "export_hmi_tags":            return tia.export_hmi_tags(a["device_name"],a.get("output_path"))
        case "list_libraries":             return tia.list_libraries()
        case "list_library_types":         return tia.list_library_types(a["library_name"])
        case "list_master_copies":         return tia.list_master_copies(a["library_name"])
        case "get_library_type_versions":  return tia.get_library_type_versions(a["library_name"],a["type_name"])
        case "execute_openness":           return tia.execute_openness(a["code"],a.get("mode","read"))
        case "get_standard_template":      return {"template": _STANDARD_TEMPLATE}
        case "compile_plc":                return tia.compile_plc(a["device_name"])
        case "list_plc_blocks":            return tia.list_plc_blocks(a["device_name"], a.get("group"))
        case "list_plc_tag_tables":        return tia.list_plc_tag_tables(a["device_name"])
        case "list_plc_tags":              return tia.list_plc_tags(a["device_name"], a["table_name"])
        case "list_plc_udts":              return tia.list_plc_udts(a["device_name"])
        case "export_plc_block":           return tia.export_plc_block(a["device_name"],a["block_name"],a.get("output_path"))
        case "import_plc_block":           return tia.import_plc_block(a["device_name"],a["file_path"])
        case "get_plc_block_source":       return tia.get_plc_block_source(a["device_name"],a["block_name"],a.get("output_path"))
        case "export_plc_tagtable":        return tia.export_plc_tagtable(a["device_name"],a["table_name"],a.get("output_path"))
        case "import_plc_tagtable":        return tia.import_plc_tagtable(a["device_name"],a["file_path"])
        case "export_hmi_tagtable":        return tia.export_hmi_tagtable(a["device_name"],a["table_name"],a.get("output_path"))
        case "import_hmi_tagtable":        return tia.import_hmi_tagtable(a["device_name"],a["file_path"])
        case "import_hmi_screen":          return tia.import_hmi_screen(a["device_name"],a["file_path"])
        case "create_hmi_structure":       return tia.create_hmi_structure(a["device_name"],a["structure"])
        case "import_hmi_tags":            return tia.import_hmi_tags(a["device_name"],a["file_path"])
        case "export_hmi_alarms":          return tia.export_hmi_alarms(a["device_name"],a.get("output_path"))
        case "import_hmi_alarms":          return tia.import_hmi_alarms(a["device_name"],a["file_path"])
        case "export_hmi_textlists":       return tia.export_hmi_textlists(a["device_name"],a.get("output_path"))
        case "import_hmi_textlists":       return tia.import_hmi_textlists(a["device_name"],a["file_path"])
        case "set_plc_block_source":       return tia.set_plc_block_source(a["device_name"],a["block_name"],a["scl_source"])
        case "write_import_file":          return tia.write_import_file(a["filename"],a["content"])
        case "read_export_file":           return tia.read_export_file(a["file_path"])
        case "create_project":
            path = a["path"]
            name_ = a.get("name", path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1])
            proj = portal.Projects.Create(path, name_)
            return {"status": "ok", "name": proj.Name, "path": safe_str(proj.Path)}
        case "restart_server":
            threading.Timer(0.5, os._exit, args=[0]).start()
            role = "primaer" if _is_primary else "proxy (Anfrage weitergeleitet)"
            return {"status": "ok", "message": f"Server wird neu gestartet (Rolle: {role})"}
        case _: raise TiaError("UNKNOWN_TOOL",f"Unbekanntes Tool: {name}",False)

# ── Entry Point ────────────────────────────────────────────────────────────────

async def main():
    import logging
    log = logging.getLogger("tia.server")

    primary = await _start_primary()
    role = "primär" if primary else "proxy"
    log.info(f"MCP Server startet als {role}")

    if primary:
        tia.setup()

    try:
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
    finally:
        if primary:
            tia.teardown()
            _stop_primary()

if __name__ == "__main__":
    asyncio.run(main())