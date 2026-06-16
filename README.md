# TIA Portal MCP Server

KI-Integration für Siemens TIA Portal V21 via Model Context Protocol (MCP).  
Verbindet Claude Desktop, Copilot Studio und andere MCP-Clients mit TIA Portal über die Openness API.

---

## Voraussetzungen

| Komponente | Version |
|---|---|
| TIA Portal | V21 (getestet), V19/V20 teilweise kompatibel |
| Python | 3.12+ |
| Siemens.Engineering.dll | V21 PublicAPI (`C:\Program Files\Siemens\Automation\Portal V21\PublicAPI\V21\net48`) |
| MCP Client | Claude Desktop, Copilot Studio, Open WebUI + Ollama |

---

## Installation

```
C:\tia-mcp\
  server.py       ← MCP-Einstiegspunkt
  tia.py          ← Openness-Logik
  README.md
  export\         ← Exportpfad (wird automatisch angelegt)
    import\       ← Importpfad für write_import_file
```

**Claude Desktop** — `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "tia-portal": {
      "command": "C:\\tia-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\tia-mcp\\server.py"]
    }
  }
}
```

---

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
| `attach_project` | — | Geöffnetes Projekt übernehmen |
| `open_project` | `path` | Projekt per Pfad öffnen |
| `save_project` | — | Projekt speichern |
| `close_project` | — | Projekt schließen |
| `close_portal` | — | TIA Portal beenden |
| `get_session_status` | — | Verbindungsstatus |
| `get_version` | — | Server- und tia.py-Version + Changelog |
| `get_project_info` | — | Projektname, Pfad, Geräteliste |
| `list_devices` | — | Alle Geräte mit Typ (PLC / Advanced / Unified) |

### PLC

| Tool | Parameter | Beschreibung |
|---|---|---|
| `compile_plc` | `device_name` | PLC kompilieren |
| `list_plc_blocks` | `device_name`, [`group`] | Alle Bausteine auflisten (inkl. Untergruppen, opt. Gruppenfilter) |
| `list_plc_tag_tables` | `device_name` | Alle Tag-Tabellen auflisten |
| `list_plc_tags` | `device_name`, `table_name` | Tags einer Tabelle auflisten |
| `list_plc_udts` | `device_name` | Alle UDTs/Strukturen auflisten |
| `get_plc_block_source` | `device_name`, `block_name` | SCL-Quellcode lesen |
| `set_plc_block_source` | `device_name`, `block_name`, `scl_source` | SCL-Quellcode schreiben¹ |
| `export_plc_block` | `device_name`, `block_name` | Baustein als XML exportieren |
| `import_plc_block` | `device_name`, `file_path` | Baustein aus XML importieren |
| `export_plc_tagtable` | `device_name`, `table_name` | PLC-Tag-Tabelle exportieren |
| `import_plc_tagtable` | `device_name`, `file_path` | PLC-Tag-Tabelle importieren |

¹ Nur einfache SCL-Anweisungen ohne Keywords/Kommentare. Für komplexen SCL: Export → XML bearbeiten → Import.

### HMI: Lesen

| Tool | Parameter | Beschreibung |
|---|---|---|
| `list_hmi_screens` | `device_name` | Alle Screens (Advanced + Unified) |
| `list_hmi_tags` | `device_name`, [`table_name`] | HMI-Tags (optional gefiltert) |
| `list_hmi_alarms` | `device_name` | Alarme (Unified: discrete + analog) |
| `list_hmi_textlists` | `device_name` | Textlisten² |

² V21-Limitation: `TextLists`-Attribut nicht verfügbar — gibt immer `count:0` zurück.

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
| `export_hmi_alarms` | `device_name`, [`output_path`] | Alarme exportieren² |
| `import_hmi_alarms` | `device_name`, `file_path` | Alarme importieren² |
| `export_hmi_textlists` | `device_name`, [`output_path`] | Textlisten exportieren² |
| `import_hmi_textlists` | `device_name`, `file_path` | Textlisten importieren² |
| `export_hmi_scripts` | `device_name`, [`output_path`] | Scripts exportieren |
| `import_hmi_scripts` | `device_name`, `file_path` | Scripts importieren |
| `create_hmi_structure` | `device_name`, `structure` | Ordnerstruktur anlegen (experimentell) |

³ Advanced: direkte API. Unified: V21-Limitation — Screens in binären DB-Dateien, kein Openness-Export möglich.  
⁴ Advanced: existierender Screen wird automatisch gelöscht, dann importiert. Unified: V21-Limitation.

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

## WinCC-Funktionsumfang nach Bereich

Basierend auf der WinCC-Projektstruktur:

| WinCC-Bereich | Export | Import | Anmerkung |
|---|:---:|:---:|---|
| **Screens** | ✅ Advanced / ⏭ Unified | ✅ Advanced / ⏭ Unified | Unified: V21-API-Limitation |
| **Screen management** | ❌ | ❌ | Kein API-Zugriff in V21 |
| **HMI tags** | ✅ | ✅ | Beide Typen vollständig |
| **Connections** | ❌ | ❌ | Kein API-Zugriff in V21 |
| **HMI alarms** | ❌ | ❌ | V21-Limitation: `DiscreteAlarms.Export()` nicht verfügbar |
| **Recipes** | ❌ | ❌ | Kein API-Zugriff in V21 |
| **Historical data** | ❌ | ❌ | Kein API-Zugriff in V21 |
| **Scripts** | ✅ | ✅ | Advanced: VBScript, Unified: JS/YML |
| **Scheduled tasks** | ❌ | ❌ | Kein API-Zugriff in V21 |
| **Cycles** | ❌ | ❌ | Kein API-Zugriff in V21 |
| **Reports** | ❌ | ❌ | Kein API-Zugriff in V21 |
| **Text and graphic lists** | ❌ | ❌ | V21-Limitation: `TextLists`-Attribut fehlt |
| **User administration** | ❌ | ❌ | Kein API-Zugriff in V21 |

> Die ❌-Bereiche sind Einschränkungen der TIA Portal Openness API V21 — nicht des MCP-Servers. Siemens öffnet diese APIs ggf. in späteren Versionen (V22+).

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
| Bausteine lesen (SCL) | `get_plc_block_source` | ✅ |
| Bausteine exportieren (XML) | `export_plc_block` | ✅ |
| Bausteine importieren | `import_plc_block` | ✅ |
| SCL schreiben | `set_plc_block_source` | ⚠️ nur einfache Anweisungen |
| Kompilieren | `compile_plc` | ✅ |
| Tag-Tabellen exportieren | `export_plc_tagtable` | ✅ |
| Tag-Tabellen importieren | `import_plc_tagtable` | ✅ |
| Bausteine auflisten | — | ❌ fehlt |
| Tag-Tabellen auflisten | — | ❌ fehlt |
| UDTs lesen / exportieren | — | ❌ fehlt |
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
| Alarme auflisten | `list_hmi_alarms` | ⚠️ V21: immer `[]` |
| Alarme exportieren | `export_hmi_alarms` | ❌ V21-Limit |
| Textlisten | `export/import_hmi_textlists` | ❌ V21-Limit |
| Tags anlegen / löschen | — | ❌ fehlt |
| Connections lesen | — | ❌ fehlt |
| Rezepte | — | ❌ V21-Limit |

### WinCC Unified (HmiSoftware)

| Aufgabe | Tool | Status |
|---|---|:---:|
| Screens auflisten | `list_hmi_screens` | ✅ |
| Screen exportieren | `export_hmi_screen`, `export_hmi_screens_all` | ❌ V21-Limit |
| Screen importieren | `import_hmi_screen` | ❌ V21-Limit |
| Tags auflisten | `list_hmi_tags` | ✅ |
| Tags exportieren | `export_hmi_tags`, `export_hmi_tagtable` | ✅ |
| Tags importieren | `import_hmi_tags`, `import_hmi_tagtable` | ✅ |
| Alarme auflisten | `list_hmi_alarms` | ✅ |
| Alarme exportieren | `export_hmi_alarms` | ❌ V21-Limit |
| Textlisten | `export/import_hmi_textlists` | ❌ V21-Limit |
| Scripts exportieren | `export_hmi_scripts` | ✅ JS/YML |
| Scripts importieren | `import_hmi_scripts` | ✅ |
| Tags anlegen / löschen | — | ❌ fehlt |
| Connections lesen | — | ❌ fehlt |

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

> V21-Limitationen (Alarme, Textlisten, Unified Screens, Rezepte) können nicht durch neue Tools umgangen werden — das ist eine Einschränkung der TIA Openness API selbst, nicht des MCP-Servers.

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
- **STA-Thread-Timeout:** Hängende API-Aufrufe werden nach 60 Sekunden abgebrochen. Der Server bleibt verfügbar, Session-Handles werden zurückgesetzt → `connect_portal` + `attach_project` erneut aufrufen.
- **Unified Screen-Export** — Screens sind in binären DB-Dateien eingebettet, kein Zugriff über Openness möglich.

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

## Changelog

| Version | Datum | Änderungen |
|---|---|---|
| 1.3.0 | 2026-06-15 | `list_plc_blocks`, `list_plc_tag_tables`, `list_plc_tags`, `list_plc_udts` — PLC vollständig lesbar |
| 1.2.0 | 2026-06-14 | BUG-11–14 gefixt: rekursive Screen-Suche, Unified-Typ-Erkennung, HmiTarget-API-Support, import_hmi_screen mit XML-basiertem Delete-vor-Import |
| 1.1.0 | 2026-06-14 | STA-Timeout + Auto-Restart, export_hmi_tags Unified-Workaround, VBScriptFolder-Support, import_hmi_scripts Advanced/Unified |
| 1.0.0 | 2026-06-14 | Erster stabiler Release: 10 Bugs gefixt, Advanced/Unified-Weiche, alle HMI-Tools, PLC-Tools vollständig |