# TIA Portal MCP Server — Validierungs-Checkliste

Bei jeder neuen Version vor dem Commit gegen ein **Testprojekt** durchführen.
Testprojekt sollte enthalten: mindestens eine PLC, eine HMI, einen UDT, ein paar Tags und Bausteine.

Ergebnis je Test: ✅ OK · ❌ Fehler (Fehlermeldung notieren) · ⏭ Übersprungen

---

## 1 — Session & Verbindung

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 1.1 | `connect_portal()` | `status: ok, tia_version: V21` | |
| 1.2 | `attach_project()` | `status: ok, project: <Name>` | |
| 1.3 | `get_session_status()` | `portal_connected: true, project_open: true` | |
| 1.4 | `get_project_info()` | Name, Pfad, Geräteliste | |
| 1.5 | `list_devices()` | PLC und HMI mit korrektem Typ | |

---

## 2 — PLC Lesen

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 2.1 | `list_plc_blocks("PLC_1")` | Liste mit OBs, FCs, FBs, DBs | |
| 2.2 | `list_plc_blocks("PLC_1", "Antriebe")` | Nur Bausteine im Ordner Antriebe | |
| 2.3 | `list_plc_tag_tables("PLC_1")` | Tabellennamen und Tag-Anzahl | |
| 2.4 | `list_plc_tags("PLC_1")` | Alle Tags mit Typ, Adresse, Kommentar | |
| 2.5 | `list_plc_tags("PLC_1", "Standard_Tags")` | Nur Tags der angegebenen Tabelle | |
| 2.6 | `list_plc_udts("PLC_1")` | UDTs mit vollständiger Memberstruktur | |
| 2.7 | `get_plc_block_source("PLC_1", "FB_Motor")` | SCL-Quellcode oder XML | |

---

## 3 — PLC Kompilieren & Export

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 3.1 | `compile_plc("PLC_1")` | `errors: 0` oder Fehlerliste | |
| 3.2 | `export_plc_block("PLC_1", "FB_Motor")` | XML-Datei in Exportpfad | |
| 3.3 | `export_plc_tagtable("PLC_1", "Standard_Tags")` | XML-Datei in Exportpfad | |

---

## 4 — Querverweise & Bereinigung

> Erst 3.1 (compile_plc) ausführen — Querverweise müssen aktuell sein.

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 4.1 | `get_cross_references("PLC_1", "Motor1_Start")` | Verwendungsstellen mit Block, Usage | |
| 4.2 | `get_cross_references("PLC_1", "FB_Motor")` | Aufrufstellen des Bausteins | |
| 4.3 | `find_unused_plc_tags("PLC_1")` | Liste ungenutzter Tags (kann leer sein) | |
| 4.4 | `find_unused_hmi_tags("HMI_1")` | Liste + `verified`-Flag prüfen | |

---

## 5 — HMI Lesen

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 5.1 | `list_hmi_screens("HMI_1")` | Screens mit Größe und Elementanzahl | |
| 5.2 | `list_hmi_tags("HMI_1")` | Tags mit Typ, High/Low, Archivierung | |
| 5.3 | `list_hmi_alarms("HMI_1")` | Alarm-Liste mit Klasse | |
| 5.4 | `list_hmi_textlists("HMI_1")` | Textlisten mit Einträgen | |

---

## 6 — Bibliotheken

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 6.1 | `list_libraries()` | Projektbibliothek + ggf. globale | |
| 6.2 | `list_library_types("<Bibliothek>")` | Typen mit Versionen | |
| 6.3 | `find_libraries("C:\\Bibliotheken")` | .al* Dateien mit TIA-Version und match-Flag | |
| 6.4 | `open_library("C:\\Bibliotheken")` | Bibliothek geöffnet, types/copies gezählt | |

---

## 7 — Schreiben (an Testprojekt — nicht an Produktivprojekt!)

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 7.1 | `create_plc_tag_table("PLC_1", "Test_Tabelle")` | `status: ok` | |
| 7.2 | `create_plc_tag("PLC_1", "Test_Tabelle", "Test_Tag", "Bool", "%M10.0")` | `status: ok` | |
| 7.3 | `create_hmi_tag_table("HMI_1", "Test_HMI_Tabelle")` | `status: ok` | |
| 7.4 | `create_hmi_tag("HMI_1", "Test_HMI_Tabelle", "Test_HMI_Tag", "Int", high_limit=100, low_limit=0)` | `status: ok` | |
| 7.5 | `list_plc_tags("PLC_1", "Test_Tabelle")` | Test_Tag sichtbar | |
| 7.6 | `list_hmi_tags("HMI_1", "Test_HMI_Tabelle")` | Test_HMI_Tag sichtbar | |

---

## 8 — Löschen (nur nach Prüfung, nur an Testprojekt!)

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 8.1 | `delete_plc_tag("PLC_1", "Test_Tabelle", "Test_Tag")` | `status: ok` | |
| 8.2 | `delete_hmi_tag("HMI_1", "Test_HMI_Tabelle", "Test_HMI_Tag")` | `status: ok` | |
| 8.3 | `list_plc_tags("PLC_1", "Test_Tabelle")` | Test_Tag nicht mehr vorhanden | |

---

## 9 — Speichern & Import

| # | Tool | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 9.1 | `save_project()` | `status: ok, project: <Name>` | |
| 9.2 | `import_plc_block("PLC_1", "<Pfad>\\FB_Motor.xml")` | `status: ok` | |
| 9.3 | `import_plc_tagtable("PLC_1", "<Pfad>\\plc_tags_Standard_Tags.xml")` | `status: ok` | |

---

## 10 — execute_openness (Wildcard)

| # | Code | Erwartetes Ergebnis | Ergebnis |
|---|---|---|---|
| 10.1 | `result = [d.Name for d in project.Devices]` | Geräteliste als Array | |
| 10.2 | `plc = find_software("PLC_1", "PlcSoftware"); result = plc is not None` | `true` | |

---

## Bekannte Einschränkungen & Hinweise

- `CrossReferenceData` erfordert kompiliertes Projekt — bei Fehler zuerst `compile_plc` aufrufen
- `find_unused_hmi_tags`: `verified: false` wenn CrossReferenceData beim HMI-Typ nicht verfügbar — dann manuelle Prüfung nötig
- `list_plc_udts`: Klassenname `PlcType` kann in V21 abweichen — im Fehlerfall per `execute_openness` den echten Typnamen ermitteln
- Schreibende Operationen (7, 8) immer an **Testprojekt**, nie direkt an Produktivprojekt
- Nach Schreiben immer `save_project()` — TIA speichert nicht automatisch

---

## Versions-Log

| Version | Datum | Tester | Auffälligkeiten |
|---|---|---|---|
| — | — | — | Erste Version der Checkliste |
