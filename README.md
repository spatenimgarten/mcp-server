# TIA Portal MCP Server

KI-Integration für Siemens TIA Portal V21 via Model Context Protocol (MCP).  
Verbindet Claude Code und andere MCP-Clients mit TIA Portal über die Openness API.

---

## Voraussetzungen

| Komponente | Version |
|---|---|
| TIA Portal | V21 (getestet), V19/V20 teilweise kompatibel |
| Python | 3.12+ |
| Siemens.Engineering.dll | V21 PublicAPI (`C:\Program Files\Siemens\Automation\Portal V21\PublicAPI\V21\net48`) |
| MCP Client | Claude Code (Desktop App) |

---

## Installation

```
C:\tia-mcp\mcp-server\
  server.py       ← MCP-Einstiegspunkt
  tia.py          ← Openness-Logik
  README.md
  TESTING.md
  commit.bat      ← Git-Hilfsskript (add + commit + push in einem Schritt)
  export\         ← Exportpfad (wird automatisch angelegt)
    import\       ← Importpfad für write_import_file
```

**Commits** — `commit.bat` staged `tia.py`, `server.py`, `README.md` und `TESTING.md` automatisch:

```bat
commit.bat "v1.x.y: kurze Beschreibung der Änderung"
```

**Claude Code** — Einstellungen → MCP Servers:
```json
{
  "mcpServers": {
    "tia-portal": {
      "command": "C:\\tia-mcp\\mcp-server\\.venv\\Scripts\\python.exe",
      "args": ["C:\\tia-mcp\\mcp-server\\server.py"]
    }
  }
}
```

---

## Architektur: Primär / Proxy / Worker

Ab v1.4.0 können mehrere Claude-Sessions gleichzeitig auf denselben TIA Portal MCP Server zugreifen:

- **Erste Instanz (primär):** Bindet Port 47823 als internen JSON-RPC-Server, hält die TIA Openness COM-Verbindung und führt alle Tool-Calls aus.
- **Weitere Instanzen (proxy):** Erkennen automatisch dass eine primäre Instanz läuft, verbinden sich via TCP und leiten alle MCP-Aufrufe durch.

COM-Zugriffe bleiben single-threaded und werden durch einen internen Lock serialisiert. Wird die primäre Instanz beendet, übernimmt beim nächsten Start automatisch die nächste Instanz die Rolle des Primärs.

---


**Worker-Prozess (ab 1.15.0):** Die primäre Instanz lädt die TIA-Bibliotheken nicht selbst. Alle TIA-Aufrufe laufen in `worker.py`, einem Kindprozess, der Aufträge als JSON-Zeilen über stdin/stdout erhält. Die primäre Instanz beendet den Worker

- bei `disconnect_portal` und `close_portal`,
- nach `TIA_MCP_IDLE_DISCONNECT` Sekunden ohne Aufruf (Standard 120, `0` = aus),
- wenn ein Aufruf nicht antwortet (dann notfalls den ganzen Prozessbaum).

Grund: Nach dem ersten Openness-Zugriff bleibt im Prozess etwas bei TIA angemeldet, das weder `Dispose` noch das Abmelden der Event-Handler löst; TIA hing dann beim Schließen des Projekts, bis der Prozess endete. Der nächste Aufruf startet einen neuen Worker und wiederholt `connect_portal`/`attach_project`, wenn vorher verbunden war. `get_session_status` zeigt `worker: laeuft/beendet`; solange kein Worker läuft, antwortet der Server selbst (ohne die TIA-Bibliotheken zu laden).

## Versionsabfrage

```
get_version
```

Gibt die laufenden Versionen von `server.py` und `tia.py` zurück, inklusive Changelog der letzten Änderungen. `match: true` wenn beide auf dem gleichen Stand sind.

```json
{
  "server": { "version": "1.0.0", "date": "2026-06-14", "file": "..." },
  "tia":    { "version": "1.2.0", "date": "2026-06-14", "changes": [...] },
  "match":  false
}
```

> `match: false` ist normal wenn `tia.py` aktualisiert wurde ohne `server.py` anzupassen.

---

## Workflow

```
open_portal / connect_portal
       ↓
attach_project / open_project
       ↓
  [Tools aufrufen]
       ↓
  save_project
       ↓
 close_project
```

- **`open_portal`** — Startet TIA Portal als neuen Prozess (kann >4 Minuten dauern, ggf. Timeout).
- **`connect_portal`** — Verbindet sich mit einem bereits laufenden TIA Portal.
- **`attach_project`** — Übernimmt das im Portal geöffnete Projekt.
- **`open_project`** — Öffnet ein Projekt per Pfad.

---

## Tools — Übersicht

### Session & Projekt

| Tool | Parameter | Beschreibung |
|---|---|---|
| `open_portal` | `mode` (gui\|headless) | TIA Portal starten |
| `connect_portal` | — | Laufendes Portal verbinden |
| `disconnect_portal` | — | Openness-Verbindung trennen, TIA bleibt offen (vor Arbeit in der TIA-Oberfläche) |
| `attach_project` | — | Geöffnetes Projekt übernehmen |
| `open_project` | `path` | Projekt per Pfad öffnen |
| `save_project` | — | Projekt speichern |
| `close_project` | — | Projekt schließen |
| `close_portal` | — | TIA Portal beenden |
| `get_session_status` | — | Verbindungsstatus |
| `get_version` | — | Server- und tia.py-Version + Changelog |
| `get_project_info` | — | Projektname, Pfad, Geräteliste |
| `list_devices` | — | Alle Geräte mit Typ (PLC / Advanced / Unified) |
| `restart_server` | — | Primären MCP-Prozess sauber neu starten |

### PLC

| Tool | Parameter | Beschreibung |
|---|---|---|
| `compile_plc` | `device_name` | PLC kompilieren |
| `get_online_state` | `device_name` | Online-Status (`Offline`, `Online`, `NotReachable`, `Protected` …) + verfügbare Modi / PG-PC- / Zielschnittstellen |
| `go_online` | `device_name`, [`mode`, `pc_interface`, `pc_interface_number`, `target_interface`, `user`, `password`, `trust_certificate`] | Online gehen² |
| `go_offline` | `device_name` | Offline gehen (no-op wenn bereits offline) |
| `list_plc_blocks` | `device_name`, [`group`] | Alle Bausteine auflisten (inkl. Untergruppen, opt. Gruppenfilter) |
| `list_plc_tag_tables` | `device_name` | Alle Tag-Tabellen auflisten |
| `list_plc_tags` | `device_name`, `table_name` | Tags einer Tabelle auflisten |
| `list_plc_udts` | `device_name` | Alle UDTs/Strukturen auflisten |
| `get_plc_block_source` | `device_name`, `block_name` | SCL-Quellcode lesen (vollständiger Baustein inkl. Schnittstelle, via `GenerateSource`) |
| `set_plc_block_source` | `device_name`, `block_name`, `scl_source` | SCL schreiben — ganzer Baustein oder nur Rumpf, danach übersetzt¹ |
| `export_plc_block` | `device_name`, `block_name` | Baustein als XML exportieren |
| `import_plc_block` | `device_name`, `file_path` | Baustein aus XML importieren |
| `export_plc_tagtable` | `device_name`, `table_name` | PLC-Tag-Tabelle exportieren |
| `import_plc_tagtable` | `device_name`, `file_path` | PLC-Tag-Tabelle importieren |
| `get_plc_config` | `device_name` | Alle CPU-Attribute auslesen (Zyklus, Startup, Netzwerk, OPC UA …) |
| `set_plc_config` | `device_name`, `settings` | CPU-Attribute schreiben (schreibgeschützte werden übersprungen) |
| `export_plc_config` | `device_name`, [`output_path`] | CPU-Konfiguration als Excel exportieren, gruppiert nach Kategorien |

¹ Läuft über eine externe Quelle (`PlcExternalSource.GenerateBlocksFromSource`), TIA übersetzt den Text selbst. `scl_source` = vollständiger Baustein (`FUNCTION_BLOCK "Name" … END_FUNCTION_BLOCK` — ersetzt Schnittstelle + Rumpf, legt den Baustein ggf. neu an) oder nur der Rumpf (Schnittstelle bleibt). Danach wird der Baustein übersetzt; Fehler kommen als `status:error` mit `compile.messages` (Text + Zeile). Nur offline (`PLC_ONLINE` sonst).

² Ohne Verbindungsparameter wird die im Projekt gespeicherte Verbindung genutzt. Die Anmeldung läuft über den V21-Event `ConnectionConfiguration.OnlineLegitimation`:
ohne `user`/`password` anonym (falls die SPS `AnonymousUser` erlaubt), sonst Benutzer/Passwort. Einem TLS-Zertifikat der SPS wird nur mit `trust_certificate=true` vertraut.
Die Rückgabe `legitimation` zeigt, welche Abfragen TIA gestellt hat und wie sie beantwortet wurden.

### HMI: Lesen

| Tool | Parameter | Beschreibung |
|---|---|---|
| `list_hmi_screens` | `device_name` | Alle Screens (Advanced + Unified) |
| `list_hmi_tags` | `device_name`, [`table_name`] | HMI-Tags (optional gefiltert) |
| `list_hmi_alarms` | `device_name` | Alarme (Unified: discrete + analog) |
| `list_hmi_connections` | `device_name` | HMI-Verbindungen (Advanced + Unified)² |
| `list_hmi_cycles` | `device_name` | Erfassungszyklen — Advanced: Name + Periode; Unified: V21-Limit |
| `list_hmi_scheduled_tasks` | `device_name` | Geplante Tasks — Advanced + Unified: V21-Limit |
| `list_hmi_logs` | `device_name` | Datenlogs auslesen (Unified) — Name, Segmentgröße, Speicher, Backup |
| `list_hmi_textlists` | `device_name` | Textlisten (Advanced)³ |

² Nur **nicht-integrierte** Verbindungen zugänglich. Integrierte Verbindungen (TIA-Netzwerktopologie) sind in V21 nicht über die API erreichbar.  
³ V21-Limitation Unified: `TextLists` nicht verfügbar.

### HMI: Export & Import

| Tool | Parameter | Beschreibung |
|---|---|---|
| `export_hmi_screen` | `device_name`, `screen_name`, `output_path` | Einzelnen Screen exportieren³ |
| `export_hmi_screens_all` | `device_name`, [`output_path`] | Alle Screens exportieren³ |
| `import_hmi_screen` | `device_name`, `file_path` | Screen importieren⁴ |
| `export_hmi_tags` | `device_name`, [`output_path`] | Alle Tag-Tabellen exportieren |
| `export_hmi_tagtable` | `device_name`, `table_name`, [`output_path`] | Einzelne Tag-Tabelle exportieren |
| `import_hmi_tagtable` | `device_name`, `file_path` | Tag-Tabelle importieren |
| `import_hmi_tags` | `device_name`, `file_path` | Alle HMI-Tags importieren |
| `export_hmi_alarms` | `device_name`, [`output_path`] | Alarme als JSON exportieren (alle Attribute via GetAttributeInfos)⁵ |
| `import_hmi_alarms` | `device_name`, `file_path` | Alarme aus JSON importieren (SetAttribute per Name)⁵ |
| `export_hmi_textlists` | `device_name`, [`output_path`] | Textlisten exportieren (Advanced+Unified XML)² |
| `import_hmi_textlists` | `device_name`, `file_path` | Textlisten importieren² |
| `export_hmi_connections` | `device_name`, [`output_path`] | HMI-Verbindungen als JSON exportieren |
| `import_hmi_connections` | `device_name`, `file_path` | HMI-Verbindungen aus JSON importieren |
| `export_hmi_cycles` | `device_name`, [`output_path`] | Erfassungszyklen als XML exportieren (Advanced) |
| `import_hmi_cycles` | `device_name`, `file_path` | Erfassungszyklen aus XML importieren |
| `list_hmi_graphic_lists` | `device_name` | Grafiklisten auflisten |
| `export_hmi_graphic_lists` | `device_name`, [`output_path`] | Grafiklisten exportieren (Advanced XML / Unified YAML) |
| `import_hmi_graphic_lists` | `device_name`, `file_path` | Grafiklisten importieren |
| `list_hmi_screen_management` | `device_name`, [`screen_type`] | Screen-Management auflisten (template/slidein/popup/global_elements/overview) |
| `export_hmi_screen_management` | `device_name`, `screen_type`, [`output_path`] | Screen-Management-Elemente exportieren |
| `import_hmi_screen_management` | `device_name`, `screen_type`, `file_path` | Screen-Management-Elemente importieren |
| `export_hmi_scripts` | `device_name`, [`output_path`] | Scripts exportieren |
| `import_hmi_scripts` | `device_name`, `file_path` | Scripts importieren |
| `create_hmi_structure` | `device_name`, `structure` | Ordnerstruktur anlegen (experimentell) |

### HMI: Konfiguration (Advanced & Unified)

| Tool | Parameter | Beschreibung |
|---|---|---|
| `get_hmi_config` | `device_name` | HMI-Gerätekonfiguration auslesen — Advanced **und** Unified (IP, Display, Runtime …); Unified zusätzlich mit RuntimeSettings |
| `set_hmi_config` | `device_name`, `settings` | HMI-Gerätekonfiguration schreiben — Advanced und Unified; Unified schreibt auch RuntimeSettings-Keys |
| `export_hmi_config` | `device_name`, [`output_path`] | Excel-Export: Advanced = 1 Sheet blau; Unified = Sheet Gerät (grün) + Sheet RuntimeSettings |
| `list_hmi_logs` | `device_name` | Datenlogs auslesen (Unified) |
| `set_hmi_log` | `device_name`, `log_name`, `settings` | Datenlog-Einstellungen schreiben — Name, SegmentMaxSize, LogMaxSize, StorageDevice, StorageFolder |
| `get_hmi_runtime_settings` | `device_name` | Runtime-Einstellungen auslesen (nur Unified) |
| `set_hmi_runtime_settings` | `device_name`, `settings` | Runtime-Einstellungen schreiben (nur Unified) |
| `export_hmi_runtime_settings` | `device_name`, [`output_path`] | Runtime-Einstellungen als Excel (nur Unified) |

### Hardware & Projekt

| Tool | Parameter | Beschreibung |
|---|---|---|
| `export_hw_config` | [`output_path`] | Hardware-Konfiguration aller Geräte als Excel (Station, Komponente, Bestellnr., Slot, IP) |

³ Advanced: direkte API. Unified: V21-Limitation — Screens in binären DB-Dateien, kein Openness-Export möglich.  
⁴ Advanced: existierender Screen wird automatisch gelöscht, dann importiert. Unified: V21-Limitation.  
⁵ Kein natives XML-Export in V21 — JSON-Workaround liest alle Attribute via `GetAttributeInfos()`. Advanced: V21-Limit (DiscreteAlarms nicht zugänglich).

### Bibliotheken

| Tool | Parameter | Beschreibung |
|---|---|---|
| `list_libraries` | — | Projekt- + Globale Bibliotheken |
| `list_library_types` | `library_name` | Typen einer Bibliothek |
| `get_library_type_versions` | `library_name`, `type_name` | Versionen eines Typs |
| `list_master_copies` | `library_name` | Master Copies |

### Hilfsfunktionen

| Tool | Parameter | Beschreibung |
|---|---|---|
| `execute_openness` | `code`, [`mode`] | Python-Code direkt gegen TIA Openness ausführen |
| `write_import_file` | `filename`, `content` | Datei in `export/import/` schreiben |
| `read_export_file` | `file_path` | Exportierte Datei lesen |
| `get_standard_template` | — | Vorlage für Standardstruktur (PLC + HMI + Bibliothek) |

---

## HMI-Funktionsumfang nach Bereich

Bereich-Referenz basierend auf TIA Portal Projektbaum. ✅ implementiert · ⚠️ eingeschränkt · ❌ V21-Limit · — fehlt noch

| TIA-Bereich | Tool | Advanced | Unified | Anmerkung |
|---|---|:---:|:---:|---|
| **Runtime settings** | `get/set/export_hmi_config` | ✅ | ✅ | Unified zusätzlich mit RuntimeSettings-Sheet |
| **Screens** | `list/export/import_hmi_screen(s)` | ✅ | ⚠️ | Unified: nur list; Export/Import V21-Limit |
| **Screen management** | `list/export/import_hmi_screen_management` | ✅ | ✅ | Templates, Slideins, Popups, GlobalElements, Overview |
| **HMI tags** | `list/export/import_hmi_tags` | ✅ | ✅ | |
| **Connections** | `list/export/import_hmi_connections` | ⚠️ | ✅ | Nur nicht-integrierte; JSON-Export; integrierte V21-Limit |
| **HMI alarms** | `list/export/import_hmi_alarms` | ❌ | ✅ | Advanced: V21-Limit; Unified: JSON via GetAttributeInfos |
| **Recipes** | — | ❌ | ❌ | V21-Limit |
| **Historical data / Logs** | `list_hmi_logs`, `set_hmi_log` | ❌ | ✅ | Advanced: DataLogs nicht zugänglich |
| **Scripts** | `export/import_hmi_scripts` | ✅ | ✅ | Advanced: VBScript · Unified: JS/YML |
| **Scheduled tasks** | `list_hmi_scheduled_tasks` | ❌ | ❌ | V21-Limit — ScheduledTaskFolder nicht zugänglich |
| **Cycles** | `list/export/import_hmi_cycles` | ✅ | ❌ | Advanced: Name, Periode, XML-Export · Unified: V21-Limit |
| **Reporting / Reports** | — | ❌ | ❌ | V21-Limit |
| **Parameter set types** | — | — | ❌ | V21-Limit Unified |
| **Collaboration data** | — | — | ❌ | V21-Limit Unified |
| **Text and graphic lists** | `list/export/import_hmi_textlists`, `list/export/import_hmi_graphic_lists` | ✅ | ⚠️ | Unified TextLists: list ✅, export/import user-Listen; Graphic lists: Advanced XML, Unified YAML |
| **User administration** | — | ❌ | ❌ | V21-Limit |

> ❌-Bereiche sind Einschränkungen der TIA Portal Openness API V21, nicht des MCP-Servers.

---

## Funktionsumfang — Detailanalyse

### PLC

| Aufgabe | Tool | Status |
|---|---|:---:|
| Geräte auflisten | `get_project_info`, `list_devices` | ✅ |
| Bausteine auflisten | `list_plc_blocks` | ✅ inkl. Untergruppen + Gruppenfilter |
| Tag-Tabellen auflisten | `list_plc_tag_tables` | ✅ inkl. Untergruppen |
| Tags auflisten | `list_plc_tags` | ✅ mit Typ, Adresse, Kommentar |
| UDTs auflisten | `list_plc_udts` | ✅ inkl. Untergruppen |
| Bausteine lesen (SCL) | `get_plc_block_source` | ✅ vollständige Quelle |
| Bausteine exportieren (XML) | `export_plc_block` | ✅ |
| Bausteine importieren | `import_plc_block` | ✅ |
| SCL schreiben | `set_plc_block_source` | ✅ ganzer Baustein oder Rumpf, mit Übersetzen |
| Kompilieren | `compile_plc` | ✅ |
| Online / Offline gehen | `go_online`, `go_offline`, `get_online_state` | ✅ inkl. Anmeldung / TLS-Zertifikat |
| Tag-Tabellen exportieren | `export_plc_tagtable` | ✅ |
| Tag-Tabellen importieren | `import_plc_tagtable` | ✅ |
| CPU-Konfiguration lesen | `get_plc_config` | ✅ alle DeviceItem-Attribute |
| CPU-Konfiguration schreiben | `set_plc_config` | ✅ skalare Attribute |
| CPU-Konfiguration exportieren | `export_plc_config` | ✅ Excel, gruppiert |
| DB-Inhalte lesen | — | ❌ fehlt |
| Bausteine löschen | — | ❌ fehlt |

### WinCC Advanced (HmiTarget — z.B. KP/TP Comfort)

| Aufgabe | Tool | Status |
|---|---|:---:|
| Screens auflisten | `list_hmi_screens` | ✅ |
| Screen exportieren | `export_hmi_screen`, `export_hmi_screens_all` | ✅ |
| Screen importieren | `import_hmi_screen` | ✅ |
| Tags auflisten | `list_hmi_tags` | ✅ |
| Tags exportieren | `export_hmi_tags`, `export_hmi_tagtable` | ✅ |
| Tags importieren | `import_hmi_tags`, `import_hmi_tagtable` | ✅ |
| Scripts exportieren | `export_hmi_scripts` | ✅ VBScript |
| Scripts importieren | `import_hmi_scripts` | ✅ VBScript |
| Gerätekonfiguration lesen | `get_hmi_config` | ✅ DeviceItem-Attribute |
| Gerätekonfiguration schreiben | `set_hmi_config` | ✅ skalare Attribute |
| Gerätekonfiguration exportieren | `export_hmi_config` | ✅ Excel |
| Verbindungen auflisten | `list_hmi_connections` | ⚠️ nur nicht-integrierte |
| Verbindungen exportieren | `export_hmi_connections` | ✅ JSON |
| Verbindungen importieren | `import_hmi_connections` | ✅ JSON (SetAttribute) |
| Erfassungszyklen auflisten | `list_hmi_cycles` | ✅ Name, Periode, system-Flag |
| Erfassungszyklen exportieren | `export_hmi_cycles` | ✅ XML |
| Erfassungszyklen importieren | `import_hmi_cycles` | ✅ XML |
| Textlisten auflisten | `list_hmi_textlists` | ✅ |
| Textlisten exportieren | `export_hmi_textlists` | ✅ XML |
| Textlisten importieren | `import_hmi_textlists` | ✅ XML (Override) |
| Grafiklisten auflisten | `list_hmi_graphic_lists` | ✅ |
| Grafiklisten exportieren | `export_hmi_graphic_lists` | ✅ XML |
| Grafiklisten importieren | `import_hmi_graphic_lists` | ✅ XML |
| Screen-Management auflisten | `list_hmi_screen_management` | ✅ template/slidein/popup/global/overview |
| Screen-Management exportieren | `export_hmi_screen_management` | ✅ XML |
| Screen-Management importieren | `import_hmi_screen_management` | ✅ XML |
| Alarme auflisten | `list_hmi_alarms` | ❌ V21-Limit |
| Alarme exportieren | `export_hmi_alarms` | ❌ V21-Limit |
| Datenlogs | `list_hmi_logs` | ❌ V21-Limit |
| Geplante Tasks | `list_hmi_scheduled_tasks` | ❌ V21-Limit |
| Rezepte | — | ❌ V21-Limit |
| Tags anlegen / löschen | — | ❌ fehlt |

### WinCC Unified (HmiSoftware)

| Aufgabe | Tool | Status |
|---|---|:---:|
| Screens auflisten | `list_hmi_screens` | ✅ |
| Screen exportieren | `export_hmi_screen`, `export_hmi_screens_all` | ❌ V21-Limit |
| Screen importieren | `import_hmi_screen` | ❌ V21-Limit |
| Tags auflisten | `list_hmi_tags` | ✅ |
| Tags exportieren | `export_hmi_tags`, `export_hmi_tagtable` | ✅ |
| Tags importieren | `import_hmi_tags`, `import_hmi_tagtable` | ✅ |
| Alarme auflisten | `list_hmi_alarms` | ✅ alle Attribute |
| Alarme exportieren | `export_hmi_alarms` | ✅ JSON (GetAttributeInfos) |
| Alarme importieren | `import_hmi_alarms` | ✅ JSON (SetAttribute per Name) |
| Verbindungen auflisten | `list_hmi_connections` | ✅ |
| Verbindungen exportieren | `export_hmi_connections` | ✅ JSON |
| Verbindungen importieren | `import_hmi_connections` | ✅ JSON |
| Grafiklisten auflisten | `list_hmi_graphic_lists` | ✅ |
| Grafiklisten exportieren | `export_hmi_graphic_lists` | ✅ YAML |
| Grafiklisten importieren | `import_hmi_graphic_lists` | ✅ YAML |
| Screen-Management auflisten | `list_hmi_screen_management` | ✅ template/slidein/popup/global/overview |
| Screen-Management exportieren | `export_hmi_screen_management` | ✅ |
| Screen-Management importieren | `import_hmi_screen_management` | ✅ |
| Scripts exportieren | `export_hmi_scripts` | ✅ JS/YML |
| Scripts importieren | `import_hmi_scripts` | ✅ |
| Gerätekonfiguration lesen | `get_hmi_config` | ✅ DeviceItem + RuntimeSettings |
| Gerätekonfiguration schreiben | `set_hmi_config` | ✅ DeviceItem + RuntimeSettings |
| Gerätekonfiguration exportieren | `export_hmi_config` | ✅ Excel, 2 Sheets |
| Datenlogs auslesen | `list_hmi_logs` | ✅ Segment, Settings, Backup |
| Datenlog schreiben | `set_hmi_log` | ✅ Name, Segmentgröße, Speicher |
| Erfassungszyklen auflisten | `list_hmi_cycles` | ❌ V21-Limit |
| Geplante Tasks | `list_hmi_scheduled_tasks` | ❌ V21-Limit |
| Textlisten auflisten | `list_hmi_textlists` | ✅ user + system |
| Textlisten exportieren | `export_hmi_textlists` | ✅ XML (user-Listen) |
| Textlisten importieren | `import_hmi_textlists` | ✅ XML |
| Tags anlegen / löschen | — | ❌ fehlt |

### Bibliotheken

| Aufgabe | Tool | Status |
|---|---|:---:|
| Bibliotheken auflisten | `list_libraries` | ✅ |
| Typen auflisten | `list_library_types` | ✅ |
| Typ-Versionen | `get_library_type_versions` | ✅ |
| Master Copies auflisten | `list_master_copies` | ✅ |
| Typ exportieren | — | ❌ fehlt |
| Typ importieren / instanziieren | — | ❌ fehlt |
| Master Copy verwenden | — | ❌ fehlt |
| Globale Bibliothek laden | — | ❌ fehlt |

---

## Roadmap — Fehlende Tools

Tools die noch nicht implementiert sind, nach Priorität:

| Prio | Tool | Bereich | Status |
|---|---|---|---|
| ~~🔴 HOCH~~ | ~~`list_plc_blocks`~~ | PLC | ✅ v1.3.0 |
| ~~🔴 HOCH~~ | ~~`list_plc_tag_tables`~~ | PLC | ✅ v1.3.0 |
| ~~🔴 HOCH~~ | ~~`list_plc_tags`~~ | PLC | ✅ v1.3.0 |
| ~~🔴 HOCH~~ | ~~`list_plc_udts`~~ | PLC | ✅ v1.3.0 |
| 🟠 MITTEL | `export_plc_udt` / `import_plc_udt` | PLC | UDTs zwischen Projekten transferieren |
| 🟠 MITTEL | `create_hmi_tag` | HMI | Tags programmatisch anlegen ohne XML-Umweg |
| 🟠 MITTEL | `delete_hmi_tag` | HMI | Tags löschen / bereinigen |
| 🟡 NIEDRIG | `list_plc_block_groups` | PLC | Ordnerstruktur der Bausteine (bereits in list_plc_blocks enthalten) |
| 🟡 NIEDRIG | `export_library_type` | Bibliothek | Bibliothekstypen sichern |
| 🟡 NIEDRIG | `use_library_type` | Bibliothek | Typ in Projekt instanziieren |
| 🟡 NIEDRIG | `get_cross_references` | PLC/HMI | Querverweise zwischen Tags und Bausteinen |

> V21-Limitationen (Advanced-Alarme, Unified Screens, Rezepte, Scheduled Tasks) können nicht durch neue Tools umgangen werden — das ist eine Einschränkung der TIA Openness API selbst, nicht des MCP-Servers. Unified-Alarme werden als JSON-Workaround über `GetAttributeInfos` exportiert.

---

## Advanced vs. Unified — Unterschiede

| | WinCC Advanced (HmiTarget) | WinCC Unified (HmiSoftware) |
|---|---|---|
| Typ-Erkennung | `Siemens.Engineering.Hmi.HmiTarget` | `Siemens.Engineering.HmiUnified.HmiSoftware` |
| Screen-API | `ScreenFolder.Folders → Screens` | `ScreenGroups → Screens` |
| Tag-API | `TagFolder.TagTables` | `TagTables` direkt |
| Tag-Export | `table.Export(FileInfo)` → XML | `table.Tags.Export(DirectoryInfo)` → Ordner |
| Script-API | `VBScriptFolder.VBScripts` | `Scripts` Collection |
| Screen-Export | ✅ `s.Export(FileInfo)` | ❌ V21-Limitation |
| Alarm-API | Kein `DiscreteAlarms`-Export | Kein `DiscreteAlarms`-Export |

---

## Bekannte Einschränkungen (V21)

- **`open_portal`** kann auf manchen Systemen >4 Minuten dauern → Timeout. Workaround: TIA manuell starten, dann `connect_portal`.
- **`project.Save()` in `execute_openness`** — nicht unterstützt, disposed Projekt-Handle. Immer `save_project`-Tool verwenden.
- **`CreateFB()` in `execute_openness`** — nur ProDiag. Neue Bausteine per XML-Import anlegen.
- **STA-Thread-Timeout:** Hängende API-Aufrufe werden nach 60 Sekunden abgebrochen, die alte Verbindung wird freigegeben. Der nächste Aufruf verbindet automatisch neu (attach-Modus).
- **Leerlauf-Trennung:** Nach `TIA_MCP_IDLE_DISCONNECT` Sekunden ohne Aufruf (Standard 120, `0` = aus) wird die Openness-Verbindung getrennt, damit die TIA-Oberfläche nicht blockiert. Der nächste Aufruf verbindet automatisch neu und übernimmt das Projekt wieder.
- **TIA-Rückfragen:** Dialoge, die TIA während eines Openness-Aufrufs zeigen will, werden mit *Abbrechen/Nein* beantwortet und geloggt (`tia.dialog`), damit der Aufruf nicht hängt. `TIA_MCP_DIALOGS=off` schaltet das ab.
- **Unified Screen-Export** — Screens sind in binären DB-Dateien eingebettet, kein Zugriff über Openness möglich.
- **Online-Modus** — Export/Import von Bausteinen (auch `set_plc_block_source`) schlägt fehl mit *"This function is not supported in online mode"*. Vorher `go_offline` aufrufen.
- **`GoOnline()` ohne Legitimation-Handler** — wirft eine `EngineeringTargetInvocationException` ohne Details, sobald die SPS eine Anmeldung verlangt. `go_online` registriert den Handler automatisch.

---

## Fehlerformat

Alle Fehler folgen diesem Schema:

```json
{
  "status": "error",
  "code": "BLOCK_NOT_FOUND",
  "message": "Baustein 'XYZ' nicht gefunden.",
  "recoverable": true,
  "details": {
    "available": ["Main", "FC_MCP_Test"]
  }
}
```

`recoverable: true` = Fehler durch andere Parameter behebbar. `recoverable: false` = Systemlimitation.

---

## Hilfsskripte (`tools/`)

### `json2vorlage.py` — Berichtsvorlage aus der Offline-Konfiguration

Erzeugt eine Excel-Berichtsvorlage für den WinCC-Unified-Bericht-Control aus der Offline-Konfiguration (`.json`, Export im Bericht-Control). Jede Variable steht untereinander als Einzelwert (Spalte A Name, Spalte B Wert). UDTs und Arrays werden in ihre Elemente aufgelöst (`Motor1.Temperatur.Wert`, `Messwerte[3]`). Reines Python, keine Zusatzpakete.

```powershell
python tools\json2vorlage.py anlage.json
```

Alle Einstellungen stehen in **`tools/json2vorlage.ini`** (kommentiert): Titel, Ausgabedatei, Basis-Mappe, Qualitätsspalte, „Erstellt am:“, Filter nach Variablentabellen (`variablen_excel` = TIA-Export `HMITags.xlsx`, `tabellen`), nur im HMI verwendete Variablen (über `list_hmi_tag_usage` des laufenden MCP-Servers, RPC-Port 47823; mit `verwendung_datei` einmal abfragen und später ohne TIA wiederverwenden), Spalte „Verwendet in“ und **Gruppierung nach Variablentabellen** (`gruppieren`: graue Überschriftzeile je Tabelle, Reihenfolge wie unter `tabellen`).

| Aufruf | Wirkung |
|---|---|
| `json2vorlage.py anlage.json` | Vorlage nach den Einstellungen der Ini erzeugen |
| `… --list` | Variablen nur anzeigen |
| `… --tabellen` | Variablentabellen aus `variablen_excel` anzeigen |
| `… --ini linie2.ini` | andere Ini-Datei verwenden (z. B. eine pro Anlage) |

Die Basis-Mappe legt man einmal mit dem Excel-Add-in an: leere Mappe, ein Einzelwert-Segment, speichern. Relative Pfade in der Ini werden zuerst im aktuellen Ordner, dann neben der Ini gesucht.

Getestet mit WinCC Unified PC RT V21 (Vorlagenformat 5.0.0.0): Werte, UDT-Elemente, verschachtelte UDTs, Arrays, DateTime, Time/LTime (kommen als Text), Qualität (`GOOD`/`UNCERTAIN`/`BAD` mit Code) und Erstellungszeitpunkt (Zeitstempel von `@Heartbeat`).

---

## Changelog

| Version | Datum | Änderungen |
|---|---|---|
| 1.16.0 | 2026-10-03 | `list_hmi_tag_usage` — wo werden HMI-Variablen verwendet (Unified): Bilder mit Tag-/Skript-Dynamisierungen, Ereignissen und Eigenschafts-Ereignissen, Bit-/Analogalarme, Archivierung, globale Skriptmodule. Ergebnis: `usages` (Referenz → Fundstellen), `tags` (je Variable `used`/`where`), `unused`. Skripte werden per Textsuche ausgewertet (`Tags("Name")`, passende String-Literale); dynamisch zusammengesetzte Namen werden nicht erkannt. |
| 1.15.0 | 2026-10-04 | **TIA-Openness läuft in einem eigenen Worker-Prozess (`worker.py`).** Trennen, Leerlauf und Timeout beenden den Worker — nur das gibt TIA zuverlässig frei (vorher hing TIA beim Schließen des Projekts, obwohl die Verbindung per `Dispose` getrennt war, bis der Server-Prozess endete). Der nächste Aufruf startet einen neuen Worker und verbindet automatisch neu. Weitere Hänger behoben: STA-Thread pumpt Window-Messages; Leerlauf-Trennung mit automatischem Neuverbinden; alte Verbindungen werden per `Dispose` freigegeben (`connect_portal`, Timeout); nach Timeout kein zweiter STA-Thread mehr; TIA-Rückfragen werden abgebrochen statt zu blockieren. `connect_portal` wählt bei mehreren TIA-Instanzen den richtigen Prozess, `close_portal` beendet nur noch den eigenen. Dialog-Handler werden vor `Dispose` abgemeldet (sonst hing TIA beim Schließen des Projekts, bis der Server-Prozess endete). Neu: `disconnect_portal`. Fix: `create_project` (NameError) und `open_portal` (fehlte in tia.py). Sandbox: `Exception`, `secure_string`, `dir_info`, `file_info`; `CurrentDomain`/`GetAssemblies` gesperrt. |
| 1.14.1 | 2026-09-26 | `set_plc_block_source` neu über externe Quelle statt selbst gebautem Token-XML (Fehler *"The token is not supported"* bei jedem echten SCL-Code); ganzer Baustein oder Rumpf; anschließendes Übersetzen mit Fehlertexten. `get_plc_block_source` liefert lesbares SCL via `GenerateSource`. `compile_plc` liefert die eigentlichen Fehlermeldungen (vorher leer). |
| 1.14.0 | 2026-09-26 | `get_online_state`, `go_online`, `go_offline` — SPS online/offline via `OnlineProvider` inkl. `OnlineLegitimation`-Handler (anonym / Benutzer / Passwort / TLS-Zertifikat). `server.py` und `tia.py` wieder auf gleicher Version. `SyntaxWarning` im `server.py`-Docstring behoben. |
| 1.13.1–1.13.4 | 2026-06-17 | STA-Loop / recoverable TiaErrors nur noch DEBUG-Log; `_get_hmi` akzeptiert device.Name und item.Name |
| 1.13.0 | 2026-06-16 | `export/import_hmi_alarms` — JSON-basiert via GetAttributeInfos (kein V21-API-Export); `list_hmi_alarms` erweitert (alle Attribute) |
| 1.12.x | 2026-06-16 | `export/import_hmi_connections` JSON; `export/import_hmi_cycles` XML; `list/export/import_hmi_graphic_lists`; `list/export/import_hmi_screen_management` (template/slidein/popup/global/overview) |
| 1.12.0 | 2026-06-16 | `set_hmi_log` — Unified DataLog-Einstellungen schreiben (Name, Segment, Storage) |
| 1.11.0 | 2026-06-16 | `list_hmi_logs` — Unified DataLogs mit Segment, Settings, Backup |
| 1.10.0 | 2026-06-16 | `list_hmi_connections` — nicht-integrierte HMI-Verbindungen; `list_hmi_textlists` Fix (sucht alle Items) |
| 1.9.0 | 2026-06-16 | `list_hmi_cycles`, `list_hmi_scheduled_tasks` — Erfassungszyklen (Advanced ✅, Unified ❌) und geplante Tasks (V21-Limit) |
| 1.8.0 | 2026-06-16 | `get_hmi_config`, `set_hmi_config`, `export_hmi_config` — HMI-DeviceItem-Attribute für Advanced und Unified; Unified-Excel mit RuntimeSettings-Sheet |
| 1.7.0 | 2026-06-16 | `get_plc_config`, `set_plc_config`, `export_plc_config` — CPU-Konfigurationsattribute lesen, schreiben und als Excel exportieren |
| 1.6.0 | 2026-06-16 | `get_hmi_runtime_settings`, `set_hmi_runtime_settings`, `export_hmi_runtime_settings` — WinCC Unified Runtime-Einstellungen |
| 1.5.0 | 2026-06-16 | `export_hw_config` — Hardware-Konfiguration aller Geräte als Excel exportieren |
| 1.4.0 | 2026-06-16 | Primär/Proxy-Architektur: mehrere Sessions teilen eine TIA-Verbindung; `restart_server`-Tool; BUG-15 Fix list_plc_tags comment-Feld |
| 1.3.0 | 2026-06-15 | `list_plc_blocks`, `list_plc_tag_tables`, `list_plc_tags`, `list_plc_udts` — PLC vollständig lesbar |
| 1.2.0 | 2026-06-14 | BUG-11–14 gefixt: rekursive Screen-Suche, Unified-Typ-Erkennung, HmiTarget-API-Support, import_hmi_screen mit XML-basiertem Delete-vor-Import |
| 1.1.0 | 2026-06-14 | STA-Timeout + Auto-Restart, export_hmi_tags Unified-Workaround, VBScriptFolder-Support, import_hmi_scripts Advanced/Unified |
| 1.0.0 | 2026-06-14 | Erster stabiler Release: 10 Bugs gefixt, Advanced/Unified-Weiche, alle HMI-Tools, PLC-Tools vollständig |