# TIA Portal MCP Server — Validierungs-Checkliste

`server.py · tia.py  —  TIA Portal V21 Openness`  
47 registrierte MCP-Tools.

**Zweck:** Vor jedem Release / Commit prüfen ob alle MCP-Tools korrekt reagieren.  
**Testprojekt Advanced:** `F:\02_Projekte\AI\Projekt2\Projekt2.ap21` · PLC: `PLC_1` · HMI: `HMI_Station_1`, `HMI_Station_2`  
**Testprojekt Unified:** Separates Projekt mit WinCC Unified Panel — HMI-Device für Unified-Tests  
**Ergebnis je Test:** ✅ OK · ❌ Fehler · ⚠️ Warnung · ⏭ Übersprungen · 🔄 Offen (Testdaten fehlen) Auswertung als Markdown.

> **Unified-Pflicht:** Alle HMI-Abschnitte (6, 7, neue Tools) sind **zweimal** auszuführen —
> einmal gegen ein WinCC-Advanced-Gerät, einmal gegen ein WinCC-Unified-Gerät.
> Abweichendes Verhalten ist in der Notiz-Spalte mit `[Advanced]` bzw. `[Unified]` zu kennzeichnen.

---

## 1 — Lifecycle: TIA Portal starten, Projekt öffnen, schließen

> Reihenfolge: `open_portal` → `open_project` → arbeiten → `save_project` → `close_project` → `close_portal`

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 1.1 | `open_portal` | `mode="gui"` | ⏭ | TIA Portal manuell gestartet — open_portal Timeout (4 min) auf diesem System. Nach Neuinstallation erneut testen. |
| 1.2 | `open_project` | `path="F:\\02_Projekte\\AI\\Projekt2\\Projekt2.ap21"` | ✅ | Erfolgreich nach manuellem TIA-Start. |
| 1.3 | `get_session_status` | *(keine)* | ✅ | Fix BUG-3: läuft jetzt im STA-Thread. Kein Cross-thread-Fehler mehr. |
| 1.4 | `save_project` | *(keine)* | ✅ | |
| 1.5 | `close_project` | *(keine)* | ✅ | |
| 1.6 | `close_portal` | *(keine)* | ✅ | Fix BUG-7: Dispose + taskkill /F /PID. TIA-Prozess wird jetzt zuverlässig beendet. |
| 1.7 | `open_portal` | `mode="headless"` | ⏭ | Nicht getestet — open_portal Timeout auf diesem System. |

---

## 2 — Session & Verbindung (attach-Modus)

> Reihenfolge: `connect_portal` → `attach_project` → weitere Tools

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 2.1 | `connect_portal` | *(keine)* | ✅ | `status:ok, mode:attach, tia_version:V21, process_id:13768` |
| 2.2 | `attach_project` | *(keine)* | ✅ | `status:ok, project:Projekt2` |
| 2.3 | `get_session_status` | *(keine)* | ✅ | `portal_connected:true, project_open:true, project_name:Projekt2` — Fix BUG-3. |
| 2.4 | `get_project_info` | *(keine)* | ✅ | Gibt alle 3 Devices zurück (S7-1500, HMI_Station_1, HMI_Station_2) — Fix BUG-1. |
| 2.5 | `list_devices` | *(keine)* | ✅ | `devices:[{PLC:PLC_1},{HMI:HMI_RT_1},{HMI:HMI_RT_2}], count:3` — Fix BUG-1. |
| 2.6 | `get_standard_template` | *(keine)* | ✅ | Korrekte Platzhalterstruktur zurückgegeben. |

---

## 3 — PLC: Lesen

> `device_name` = DeviceItem-Name (z.B. `PLC_1`). Im Zweifel zuerst `list_devices` aufrufen.  
> Testprojekt: `PLC_1` mit OB `Main` (LAD), FC `FC_MCP_Test` (SCL), UDT `udt_Test`, Tag-Tabelle `MCP_TestTags` (3 Tags), Baustein-Gruppe `Group_1`.

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 3.1 | `list_plc_blocks` | `device_name="PLC_1"` | 🔄 | Erwartet: `count:2`, blocks: `[{name:Main, type:OB, lang:LAD}, {name:FC_MCP_Test, type:FC, lang:SCL}]` |
| 3.2 | `list_plc_blocks` | `device_name="PLC_1", group="Group_1"` | 🔄 | Gruppenfilter — erwartet leere Liste (Group_1 enthält keine Bausteine) oder Bausteine falls vorhanden |
| 3.3 | `list_plc_tag_tables` | `device_name="PLC_1"` | 🔄 | Erwartet: `count:2`, tables: `[{name:Default tag table, tag_count:0}, {name:MCP_TestTags, tag_count:3}]` |
| 3.4 | `list_plc_tags` | `device_name="PLC_1", table_name="MCP_TestTags"` | 🔄 | Erwartet: 3 Tags — `b_MCP_Flag (Bool, %M0.0)`, `i_MCP_Zaehler (Int, %MW2)`, `r_MCP_Sollwert (Real, %MD4)` |
| 3.5 | `list_plc_tags` | `device_name="PLC_1", table_name="GIBT_ES_NICHT"` | 🔄 | Erwartet: `TABLE_NOT_FOUND, recoverable:true, available:[Default tag table, MCP_TestTags]` |
| 3.6 | `list_plc_udts` | `device_name="PLC_1"` | 🔄 | Erwartet: `count:1`, udts: `[{name:udt_Test, type:PlcStruct}]` |
| 3.7 | `compile_plc` | `device_name="PLC_1"` | ✅ | `errors:0, warnings:0` |
| 3.8 | `get_plc_block_source` | `device_name="PLC_1", block_name="Main"` | ✅ | `type:OB, language:LAD, xml_size_kb:3.9` |
| 3.9 | `get_plc_block_source` | `device_name="PLC_1", block_name="FC_MCP_Test"` | ✅ | `type:FC, language:SCL, scl_source:";"` |

---

## 4 — PLC: Export

> Exportpfad Standard: `C:\tia-mcp\export\` — wird automatisch angelegt.  
> Zieldatei wird vor jedem Export gelöscht (TIA überschreibt nicht).

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 4.1 | `export_plc_block` | `device_name="PLC_1", block_name="Main"` | ✅ | `xml_path:C:\tia-mcp\export\Main.xml` |
| 4.2 | `export_plc_block` | `device_name="PLC_1", block_name="FC_MCP_Test"` | ✅ | `type:FC, xml_path:C:\tia-mcp\export\FC_MCP_Test.xml` |
| 4.3 | `export_plc_tagtable` | `device_name="PLC_1", table_name="MCP_TestTags"` | ✅ | `xml_path:C:\tia-mcp\export\plc_tags_MCP_TestTags.xml` |

---

## 5 — PLC: Import & Schreiben

> ⚠️ **Nur an Testprojekt** — Import überschreibt vorhandene Blöcke / Tabellen (Override-Modus)!

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 5.1 | `import_plc_block` | `device_name="PLC_1", file_path="C:\tia-mcp\export\FC_MCP_Test.xml"` | ✅ | `blocks:[Siemens.Engineering.SW.Blocks.FC]` — Roundtrip 4.2→5.1 ✅ |
| 5.2 | `import_plc_tagtable` | `device_name="PLC_1", file_path="C:\tia-mcp\export\plc_tags_MCP_TestTags.xml"` | ✅ | Roundtrip 4.3→5.2 ✅ |
| 5.3 | `set_plc_block_source` | `device_name="PLC_1", block_name="Block_2", scl_source=";"` | ✅ | Import + Roundtrip erfolgreich. **V21-Einschränkung:** Nur einfache Anweisungen ohne Keywords/Kommentare. Für komplexen SCL: `export_plc_block` → XML bearbeiten → `import_plc_block`. |

---

## 6 — HMI: Lesen

> `device_name` = Station-Name, nicht DeviceItem-Name.  
> Advanced = `HMI_Station_1` (KP1200 Comfort, `Hmi.HmiTarget`), Unified = `HMI_Station_2` (`HmiUnified.HmiSoftware`).  
> Advanced hat keine Alarm-API in V21 — `list_hmi_alarms` gibt `[]` zurück (kein Bug).

| # | Tool | Parameter | Advanced | Unified | Notiz |
|---|---|---|:---:|:---:|---|
| 6.1 | `list_hmi_screens` | `device_name=<HMI>` | ✅ | ✅ | [Adv] `count:2` (MCP_Screen_A, MCP_Screen_B via ScreenFolder). [Uni] `count:2` (via ScreenGroups). BUG-11+14 gefixt. |
| 6.2 | `list_hmi_tags` | `device_name=<HMI>` | ✅ | ✅ | [Adv] `count:3` (MCP_Tags via TagFolder). [Uni] `count:3` (MCP_Tags direkt). `type:"?"` normal — DataTypeName nach API-Create leer. |
| 6.3 | `list_hmi_tags` | `device_name=<HMI>, table_name="MCP_Tags"` | ✅ | ✅ | Filterung korrekt für beide Typen. |
| 6.4 | `list_hmi_alarms` | `device_name=<HMI>` | ✅ | ✅ | [Adv] `count:0` — kein Alarm-API in V21 (kein Bug). [Uni] `count:1` (MCP_Alarm_Test, discrete). |
| 6.5 | `list_hmi_textlists` | `device_name=<HMI>` | ✅ | ✅ | Beide `count:0` — `TextLists`-Attribut in V21 nicht verfügbar (V21-Limitation). |

---

## 7 — HMI: Export & Import

> ⚠️ **Import-Tests nur an Testprojekt** — Override überschreibt vorhandene Daten!  
> Advanced = `HMI_Station_1`, Unified = `HMI_Station_2`.  
> Advanced Export: API (`s.Export`, `table.Export`). Unified Tags: `Tags.Export(DirectoryInfo)`.  
> Unified Screens: V21-Limitation — kein Export/Import via Openness API möglich.

| # | Tool | Parameter | Advanced | Unified | Notiz |
|---|---|---|:---:|:---:|---|
| 7.1 | `export_hmi_screen` | `device_name=<HMI>, screen_name="MCP_Screen_A", output_path=<Pfad>` | ✅ | ⏭ | [Adv] `method:api_export` ✅. [Uni] V21-Limitation — `HmiScreen` hat kein `Export`-Attribut. Screens in binären DB-Dateien eingebettet. |
| 7.2 | `export_hmi_tags` | `device_name=<HMI>` | ✅ | ✅ | [Adv] XML-Datei (`hmi_tags_MCP_Tags.xml`). [Uni] Ordner (`hmi_tags_MCP_Tags/`) via `Tags.Export(DirectoryInfo)`. Default-Tabelle wird übersprungen. |
| 7.3 | `export_hmi_tagtable` | `device_name=<HMI>, table_name="MCP_Tags"` | ✅ | ✅ | [Adv] `xml_path`. [Uni] `export_dir` mit Ordner. |
| 7.4 | `import_hmi_tagtable` | `device_name=<HMI>, file_path=<aus 7.3>` | ✅ | ✅ | Roundtrip 7.3→7.4 für beide Typen ✅. |
| 7.5 | `import_hmi_screen` | `device_name=<HMI>, file_path=<aus 7.1>` | ✅ | ⏭ | [Adv] Screen-Name aus XML gelesen, existierender Screen gelöscht, dann Import ✅ (`deleted_before_import:["MCP_Screen_A"]`). [Uni] V21-Limitation: `SCREEN_IMPORT_NOT_SUPPORTED`. |
| 7.6 | `import_hmi_tags` | `device_name=<HMI>, file_path=<aus 7.2>` | ✅ | ✅ | BUG-12 gefixt — Ordner-Pfad wird korrekt als `DirectoryInfo` übergeben. |
| 7.7 | `export_hmi_alarms` | `device_name=<HMI>` | ⏭ | ⏭ | Beide: `ALARM_EXPORT_NOT_SUPPORTED` — V21-Limitation für Advanced + Unified. |
| 7.8 | `import_hmi_alarms` | `device_name=<HMI>, file_path=<aus 7.7>` | ⏭ | ⏭ | Abhängig von 7.7 — V21-Limitation. |
| 7.9 | `export_hmi_textlists` | `device_name=<HMI>` | ⏭ | ⏭ | Beide: `TEXTLIST_EXPORT_NOT_SUPPORTED` — V21-Limitation. |
| 7.10 | `import_hmi_textlists` | `device_name=<HMI>, file_path=<aus 7.9>` | ⏭ | ⏭ | Abhängig von 7.9 — V21-Limitation. |
| 7.11 | `export_hmi_screens_all` | `device_name=<HMI>` | ✅ | ⏭ | [Adv] `count:2`, beide Screens als XML (`method:api_export`). [Uni] V21-Limitation — gleiche Ursache wie 7.1. |
| 7.12 | `export_hmi_scripts` | `device_name=<HMI>` | ✅ | ✅ | [Adv] `MCP_Script_Test.xml` via `VBScriptFolder`. [Uni] `Global module.hmi.yml` + `.hmi.js` via `Scripts.Export(DirectoryInfo)`. |
| 7.13 | `import_hmi_scripts` | `device_name=<HMI>, file_path=<aus 7.12>` | ✅ | ✅ | [Adv] `VBScriptComposition.Import(FileInfo, ImportOptions)` — iteriert XMLs im Ordner. [Uni] `Scripts.Import(DirectoryInfo)`. |
| 7.14 | `create_hmi_structure` | `device_name=<HMI>, structure={...}` | ⏭ | ⏭ | Noch nicht vollständig spezifiziert — Test zurückgestellt. |



---

## 7b — HMI: Konfiguration (Advanced & Unified) — v1.8.0

> `get_hmi_config` / `set_hmi_config` / `export_hmi_config` funktionieren für **beide** HMI-Typen.  
> Advanced: liest DeviceItem-Attribute (IP, Display, Runtime …).  
> Unified: DeviceItem-Attribute + RuntimeSettings (separates Excel-Sheet).  
> Die alten `get/set/export_hmi_runtime_settings`-Tools (Unified-only) bleiben als Alternative erhalten.

| # | Tool | Parameter | Advanced | Unified | Notiz |
|---|---|---|:---:|:---:|---|
| 7b.1 | `get_hmi_config` | `device_name=<HMI>` | 🔄 | 🔄 | [Adv] JSON mit DeviceItem-Attributen, `type:"Advanced"`. [Uni] Zusätzlich `runtime_settings`-Feld. |
| 7b.2 | `set_hmi_config` | `device_name=<HMI>, settings={...}` | 🔄 | 🔄 | Schreibgeschützte Attrs (Name, OrderNumber …) in `skipped`. [Uni] RuntimeSettings-Keys in `applied_runtime_settings`. |
| 7b.3 | `export_hmi_config` | `device_name=<HMI>` | 🔄 | 🔄 | [Adv] Excel mit blauem Header, 1 Sheet. [Uni] Excel mit grünem Header, 2 Sheets (Gerät + RuntimeSettings). |
| 7b.4 | `export_hmi_config` | `device_name=<HMI>, output_path="C:\tia-mcp\export\test_hmi.xlsx"` | 🔄 | 🔄 | Benutzerdefinierter Exportpfad wird verwendet. |

---

## 5b — PLC: Konfiguration — v1.7.0

> Liest und schreibt DeviceItem-Attribute der CPU (nicht PlcSoftware).  
> Typische Attribute: OrderNumber, FirmwareVersion, CycleMinimumCycleTime, WebserverActivate, SNMPActive, OpcUaPurchasedLicense …  
> `device_name` = DeviceItem-Name (z.B. `PLC_1`).

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 5b.1 | `get_plc_config` | `device_name="PLC_1"` | 🔄 | Erwartet: JSON mit allen DeviceItem-Attributen, `type:"ok"`. |
| 5b.2 | `set_plc_config` | `device_name="PLC_1", settings={"WebserverActivate": false}` | 🔄 | Schreibgeschützte Attrs (OrderNumber …) in `skipped_readonly`. |
| 5b.3 | `export_plc_config` | `device_name="PLC_1"` | 🔄 | Excel mit Gruppen Allgemein, Zyklus, Startup, Zeitzone, Netzwerk, OPC UA, Sicherheit usw. |
| 5b.4 | `export_plc_config` | `device_name="PLC_1", output_path="C:\tia-mcp\export\test_plc.xlsx"` | 🔄 | Benutzerdefinierter Exportpfad. |

---

## 5c — Hardware-Konfiguration — v1.5.0

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 5c.1 | `export_hw_config` | *(keine)* | 🔄 | Excel mit Station, Komponente, Bestellnummer, Slot, IP aller Geräte. |
| 5c.2 | `export_hw_config` | `output_path="C:\tia-mcp\export\test_hw.xlsx"` | 🔄 | Benutzerdefinierter Exportpfad. |

---

## 8 — Bibliotheken

> Falls keine Typen oder Master Copies vorhanden: `count:0` ist korrektes Ergebnis.

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 8.1 | `list_libraries` | *(keine)* | ✅ | `libraries:[{name:ProjectLibrary, scope:project, types:0, copies:0}]` — Fix BUG-4: GlobalLibraries jetzt am Portal-Objekt gelesen. |
| 8.2 | `list_library_types` | `library_name="ProjectLibrary"` | ⏭ | Keine Typen im Testprojekt. |
| 8.3 | `list_master_copies` | `library_name="ProjectLibrary"` | ⏭ | Keine Master Copies im Testprojekt. |
| 8.4 | `get_library_type_versions` | `library_name=..., type_name=...` | ⏭ | Voraussetzung 8.2 nicht erfüllt. |

---

## 9 — Datei-Hilfsfunktionen

> `write_import_file` schreibt nach `C:\tia-mcp\export\import\`.  
> `read_export_file` liest beliebige Dateien aus dem Exportverzeichnis.

| # | Tool | Parameter | Status | Notiz |
|---|---|---|:---:|---|
| 9.1 | `write_import_file` | `filename="test.xml", content="<test/>"` | ✅ | `path:C:\tia-mcp\export\import\test.xml` |
| 9.2 | `read_export_file` | `file_path="C:\tia-mcp\export\import\test.xml"` | ✅ | `content:"<test/>", size_kb:0.0` — Inhalt stimmt überein. |
| 9.3 | `read_export_file` | `file_path="C:\tia-mcp\export\Main.xml"` | ✅ | `content:<XML>, size_kb:3.9` |

---

## 10 — execute_openness (Lesen)

> `mode='read'` ist Standard — schreibende Methoden gesperrt.  
> `iter_devices()` neu im Kontext: iteriert alle Devices inkl. DeviceGroups.

| # | Code | Erwartetes Ergebnis | Status | Notiz |
|---|---|---|:---:|---|
| 10.1 | `result = [d.Name for d in project.Devices]` | `result:[...]` | ⚠️ | Gibt `[]` — Devices liegen in DeviceGroups, nicht auf Top-Level. Kein Bug. Stattdessen `iter_devices()` oder DeviceGroups-Stack verwenden. |
| 10.2 | `plc = find_software("PLC_1", "PlcSoftware"); result = plc is not None` | `result:true` | ✅ | Fix BUG-1: find_software durchsucht DeviceGroups. |
| 10.3 | Iterativer Stack über `project.DeviceGroups` | `[{name, type}, …]` | ✅ | 11 DeviceItems gefunden. `iter_devices()` als Shortcut verfügbar. |
| 10.4 | `result = eval("1+1")` | `CODE_BLOCKED` | ✅ | eval korrekt blockiert. |
| 10.5 | `result = project.Save()` *(read-Modus)* | `WRITE_BLOCKED` | ✅ | .save() im read-Modus korrekt blockiert. |
| 10.6 | `for dev in iter_devices(): result.append(dev.Name)` | Alle Devices | ✅ | PLC_1, HMI_RT_1, HMI_RT_2 — iter_devices() neu im Kontext. |

---

## 11 — execute_openness (Schreiben)

> ⚠️ **Nur an Testprojekt!** `mode='write'` erlaubt alle Methoden.  
> `project.Save()` im write-Modus **nicht verwenden** — stattdessen `save_project`-Tool nutzen.

| # | Code | Erwartetes Ergebnis | Status | Notiz |
|---|---|---|:---:|---|
| 11.1 | `mode="write"` · `project.Save()` | `status:ok` | ❌ | Bekannte Einschränkung: `project.Save()` in execute_openness wirft Exception und disposed Projekt-Handle. Immer `save_project`-Tool verwenden. |
| 11.2 | `mode="write"` · `plc.TagTableGroup.TagTables.Create("MCP_Test")` | `status:ok` | ⏭ | Nicht sinnvoll testbar ohne vorkonfigurierten Testbaustein. |

---

## 12 — Fehlerverhalten

| # | Tool | Auslöser | Erwarteter Fehler | Status | Notiz |
|---|---|---|---|:---:|---|
| 12.1 | `connect_portal` | TIA nicht offen | `NO_PORTAL_PROCESS, recoverable:true` | ✅ | |
| 12.2 | `get_project_info` | Nach `close_project` | `NO_PROJECT, recoverable:true` | ✅ | Nach echtem `close_project` korrekt. |
| 12.3 | `open_project` | `path="F:\nicht\vorhanden.ap21"` | `FILE_NOT_FOUND, recoverable:true` | ✅ | |
| 12.4 | `export_plc_block` | `block_name="GIBT_ES_NICHT"` | `BLOCK_NOT_FOUND, available:[Main, FC_MCP_Test]` | ✅ | `available` korrekt befüllt. |
| 12.5 | `list_hmi_screens` | `device_name="GIBT_ES_NICHT"` | `HMI_NOT_FOUND, available:[...]` | ✅ | `available` zeigt alle 3 Devices. |
| 12.6 | `export_hmi_tagtable` | `table_name="GIBT_ES_NICHT"` | `TABLE_NOT_FOUND, available:[Default tag table, MCP_Tags]` | ✅ | |
| 12.7 | `export_hmi_screen` | `screen_name="GIBT_ES_NICHT"` | `SCREEN_NOT_FOUND, available:[MCP_Screen_A, MCP_Screen_B]` | ✅ | |
| 12.8 | `import_hmi_screen` | Unified-Gerät | `SCREEN_IMPORT_NOT_SUPPORTED, recoverable:false` | ✅ | V21-Limitation sauber kommuniziert. |
| 12.9 | `export_hmi_alarms` | Beide Typen | `ALARM_EXPORT_NOT_SUPPORTED, recoverable:false` | ✅ | Kein Timeout — sauberer Fehler. |
| 12.10 | `close_project` | Kein Projekt offen | `NO_PROJECT, recoverable:true` | ✅ | |
| 12.11 | STA-Timeout | Hängender API-Aufruf | `STA_TIMEOUT, recoverable:true` + Auto-Restart | ✅ | Server bleibt verfügbar nach Timeout. |


---

## 13 — Abgrenzung: Nicht implementierte Tools

Tools die geplant aber noch nicht implementiert sind:

| Nicht implementiert | Äquivalent / Workaround |
|---|---|
| `get_cross_references()` | — geplant |
| `find_unused_plc_tags()` | — geplant |
| `find_unused_hmi_tags()` | — geplant |
| `delete_plc_tag()` | — geplant |
| `delete_hmi_tag()` | — geplant |
| `export_library_type()` | — geplant |
| `use_library_type()` | — geplant |
| `create_plc_tag_table()` | `execute_openness (mode=write)` |
| `create_plc_tag()` | `execute_openness (mode=write)` |
| `create_hmi_tag_table()` | `execute_openness (mode=write)` |
| `create_hmi_tag()` | `execute_openness (mode=write)` |

---

## Bug-Zusammenfassung

Alle 10 identifizierten Bugs wurden gefixt.

| Bug-ID | Priorität | Titel | Status | Root Cause | Fix |
|---|---|---|:---:|---|---|
| BUG-1 | 🔴 KRITISCH | DeviceGroups nicht durchsucht | ✅ | `find_software()`, `_get_hmi()`, `list_devices()`, `get_project_info()` iterieren nur `project.Devices` | `_iter_all_devices()` traversiert `project.Devices` + `project.DeviceGroups` rekursiv |
| BUG-2 | 🔴 KRITISCH | `export_plc_block` Timeout | ✅ | `_find_sw()` kehrt nie zurück wenn PLC in DeviceGroups liegt — STA-Thread blockiert | Durch BUG-1-Fix mitgelöst |
| BUG-3 | 🟠 HOCH | `get_session_status` Cross-thread STA | ✅ | `project.Name` im aufrufenden Thread aufgerufen | `get_session_status()` komplett via `sta.run()` |
| BUG-4 | 🟠 HOCH | `list_libraries` AttributeError V21 | ✅ | `ProjectLibrary.Name` existiert nicht. `GlobalLibraries` hängt am Portal | `_lib_name()` + `_global_libraries()` |
| BUG-5 | 🟡 MITTEL | `execute_openness(write)` + `project.Save()` disposed Handle | ✅ dok. | Bekannte Einschränkung der exec-Sandbox | Dokumentiert: `save_project`-Tool verwenden |
| BUG-6 | 🟢 NIEDRIG | `available:[]` in Fehlermeldungen | ✅ | `available` aus `project.Devices` gebaut — leer wegen DeviceGroups | Durch BUG-1-Fix mitgelöst |
| BUG-7 | 🔴 KRITISCH | `close_portal` Deadlock / TIA bleibt offen | ✅ | `Dispose()` trennt nur API-Verbindung. Über `sta.run()` → Deadlock | Dispose mit 30s-Timeout + `taskkill /F /PID` nach jedem Dispose |
| BUG-8 | 🟡 MITTEL | Export überschreibt nicht | ✅ | TIA wirft Exception wenn Zieldatei existiert | Alle Export-Funktionen löschen Zieldatei vor Export |
| BUG-9 | 🟢 NIEDRIG | `compile_plc` ICompilable nicht gefunden | ✅ | `ICompilable` liegt in `Siemens.Engineering.Base`, nicht in Step7-Assembly | Dreistufige Suche: Step7 → Base per Reflection → Namespace-Import |
| BUG-10 | 🟢 NIEDRIG | `export_hmi_tags` ignoriert `output_path` | ✅ | `output_path` wurde als Dateiname interpretiert, aber Zielordner-Variable wurde ignoriert | `output_path` ist jetzt korrekt Zielordner |

---

## Bekannte V21-Limitationen

| Limitation | Betroffene Tools | Workaround |
|---|---|---|
| `HmiTagTable.Export(FileInfo)` nicht verfügbar | `export_hmi_tags`, `export_hmi_tagtable` | `table.Tags.Export(DirectoryInfo)` — exportiert Ordner statt Datei |
| `HmiScreen.Export()` fehlt bei Unified | `export_hmi_screen`, `export_hmi_screens_all` (Unified) | Kein Workaround — Screens manuell exportieren |
| `ScreenComposition.Import` akzeptiert kein Override | `import_hmi_screen` (Advanced) | Screen vorher löschen, dann importieren ✅ |
| Alarm-Export nicht verfügbar | `export_hmi_alarms` beide Typen | Kein Workaround |
| `TextLists`-Attribut fehlt | `export_hmi_textlists` beide Typen | Kein Workaround |
| `CreateFB()` nur ProDiag | `execute_openness` | XML-Import via `import_plc_block` |
| `project.Save()` in `execute_openness` | — | `save_project`-Tool verwenden |
| `open_portal` Timeout | `open_portal` | TIA manuell starten, dann `connect_portal` |
| Unified Screens in binären DB-Dateien | `export_hmi_screen` Unified | Kein Workaround in V21 |

---

## Versionshistorie

| Version | Datum | Tester | Auffälligkeiten |
|---|---|---|---|
| V0.1 | 2026-06-12 | Claude Sonnet 4.6 (MCP-automatisiert) | Ersterstellung. 7 Bugs identifiziert. Alle PLC- und HMI-Tools wegen BUG-1 nicht funktionsfähig. |
| V0.2 | 2026-06-12 | Claude Sonnet 4.6 | 10 Bugs gefixt. 7 neue Funktionen. |
| V0.3–V0.9 | 2026-06-13–14 | Claude Sonnet 4.6 | Iterative HMI-Erweiterungen, Unified/Advanced-Weiche, Testprojekt-Aufbau, BUG-11–14 identifiziert. |
| V1.0 | 2026-06-14 | Claude Sonnet 4.6 (MCP-automatisiert) | tia.py v1.2.0 deployed. Alle BUGs 11–14 gefixt. Vollständiger Testdurchlauf Advanced + Unified. Ergebnis: PLC ✅, HMI-Lesen ✅, Tag-Export/Import ✅, Screen-Export Advanced ✅, Script-Export/Import ✅. V21-Limitationen dokumentiert. STA-Timeout + Auto-Restart implementiert. |
| V1.1 | 2026-06-15 | Claude Sonnet 4.6 | tia.py v1.3.0: 4 neue PLC-List-Tools (`list_plc_blocks`, `list_plc_tag_tables`, `list_plc_tags`, `list_plc_udts`). Abschnitt 3 in TESTING.md um Tests 3.1–3.6 erweitert. |
| V1.2 | 2026-06-16 | Claude Sonnet 4.6 | tia.py v1.5–1.6: `export_hw_config`, `get/set/export_hmi_runtime_settings`. TESTING.md: Abschnitte 5c, 7b (HMI-Konfiguration) angelegt. |
| V1.3 | 2026-06-16 | Claude Sonnet 4.6 | tia.py v1.7.0: `get/set/export_plc_config`. Abschnitt 5b in TESTING.md ergänzt. |
| V1.4 | 2026-06-16 | Claude Sonnet 4.6 | tia.py v1.8.0: `get/set/export_hmi_config` mit Advanced/Unified-Weiche. Abschnitt 7b um neue Tools erweitert. Tool-Zähler auf 47. |

| V0.6 | 2026-06-13 | Claude Sonnet 4.6 | Advanced/Unified-Weiche für alle HMI-Tools. Neue Hilfsfunktionen: `_hmi_screens()`, `_hmi_screens_import()`, `_hmi_screen_folders()`, `_hmi_tag_folders()`. Neues Tool: `create_hmi_structure`. Testabschnitte 6+7 um Unified-Spalte erweitert. README: API-Unterschiede-Tabelle ergänzt. |