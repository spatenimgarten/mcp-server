# TIA Portal MCP Server

Python-basierter MCP-Server (Model Context Protocol) der Claude, lokale LLMs
(Ollama) und **Microsoft Copilot Studio** mit **TIA Portal V21** über die Openness API verbindet.

Ermöglicht LLM-gesteuerte Automatisierung von PLC/HMI-Entwicklungsaufgaben:
Bausteine lesen und bearbeiten, Tags verwalten, HMI konfigurieren, Projekte validieren.

> **Internes Tooling** — läuft auf der gleichen Windows-Maschine wie TIA Portal V21.

---

## Dateien

| Datei | Inhalt |
|---|---|
| `server.py` | MCP stdio Server · Tool-Definitionen · System Prompt · Singleton-Lock |
| `tia.py` | TIA Openness Anbindung · STA-Thread · Session · PLC · HMI · Bibliothek · Executor |
| `bridge.py` | Ollama ↔ MCP Bridge · lokales LLM statt Claude Desktop |
| `web_server.py` | MCP HTTP Streamable Server · für Copilot Studio via Dev Tunnel |
| `start_copilot.bat` | Starter: TIA Portal + web_server.py + Dev Tunnel |

---

## Voraussetzungen

| | |
|---|---|
| TIA Portal | V21 (installiert und lizenziert) |
| Python | 3.10+ (64-bit) |
| Betriebssystem | Windows 10/11 (64-bit) |
| Rechte | Administrator (COM-Zugriff auf TIA) |
| Claude Desktop | [claude.ai/download](https://claude.ai/download) |

---

## Installation

```powershell
# Im Projektordner, als Administrator
python -m venv .venv
.venv\Scripts\activate
pip install mcp pythonnet
```

**TIA Openness aktivieren:**
Extras → Einstellungen → Allgemein → TIA Portal Openness → Zugriff erlauben → TIA neu starten

---

## Modus 1 — Claude Desktop (stdio)

**Claude Desktop konfigurieren** (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tia-portal": {
      "command": "F:\\MCP-Server\\.venv\\Scripts\\python.exe",
      "args":    ["F:\\MCP-Server\\server.py"],
      "cwd":     "F:\\MCP-Server"
    }
  }
}
```

> `command` muss auf die `python.exe` im `.venv` zeigen — nicht System-Python!

TIA Portal öffnen, Projekt laden, Claude Desktop starten — das Hammer-Symbol unten im Chat zeigt alle verfügbaren Tools.

---

## Modus 2 — Copilot Studio (HTTP via Dev Tunnel)

`web_server.py` implementiert den **MCP Streamable HTTP Transport** den Copilot Studio benötigt.
Da Copilot Studio eine öffentlich erreichbare HTTPS-URL erwartet, wird ein
**Microsoft Dev Tunnel** eingesetzt der den lokalen Port 8000 nach außen tunnelt.

> Die TIA-Daten verlassen dabei das lokale System — nur sinnvoll wenn das
> datenschutzseitig akzeptiert ist (Microsoft M365-Tenant).

### Einmalige Einrichtung

**Pakete nachinstallieren:**
```powershell
.venv\Scripts\activate
pip install uvicorn starlette
```

**Dev Tunnel CLI installieren und einrichten:**
```powershell
winget install Microsoft.devtunnel
devtunnel user login                          # mit Firmen-Microsoft-Account anmelden
devtunnel create tia-mcp --allow-anonymous    # benannten Tunnel anlegen
devtunnel port create tia-mcp -p 8000         # Port 8000 registrieren
devtunnel show tia-mcp                        # feste URL anzeigen
```

Die URL hat das Format `https://tia-mcp-8000.euw.devtunnels.ms` — diese **einmalig**
in Copilot Studio eintragen.

**Copilot Studio konfigurieren:**
```
Agent öffnen
→ Tools → Add Tool → New Tool → Model Context Protocol
→ URL: https://tia-mcp-8000.euw.devtunnels.ms/mcp
→ Authentication: None
→ Create
```

### Täglicher Betrieb

```powershell
# Alles auf einmal starten:
start_copilot.bat
```

Die Batch-Datei startet in dieser Reihenfolge:
1. TIA Portal (minimiert, 35 Sekunden Wartezeit)
2. `web_server.py` in eigenem Fenster (Port 8000)
3. Dev Tunnel `tia-mcp` in eigenem Fenster

Zum Beenden: beide Fenster schließen und TIA Portal beenden.
Der Tunnel ist **nur aktiv solange der Prozess läuft** — kein Dauerzugriff von außen.

### Projektpfad anpassen

In `start_copilot.bat` ganz oben:
```bat
set PROJECT_DIR=F:\02_Projekte\AI\MCP-Server
```

> `server.py` (Claude Desktop / stdio) und `web_server.py` (Copilot Studio / HTTP)
> verwenden denselben TIA STA-Thread — **nicht gleichzeitig starten**.

---

## Tools (Übersicht)

### Session
| Tool | Beschreibung |
|---|---|
| `connect_portal(mode)` | Portal verbinden: `attach` / `headless` / `gui` |
| `attach_project()` | Bereits geöffnetes Projekt übernehmen |
| `open_project(path)` | Projekt per Pfad öffnen (`.ap21`) |
| `get_session_status()` | Verbindungs- und Projektstatus |
| `get_project_info()` | Projektname, Pfad, Geräteübersicht |
| `list_devices()` | Alle Geräte mit Typ: PLC / Advanced / Unified |

### PLC — Lesen (JSON, kein Export nötig)
| Tool | Beschreibung |
|---|---|
| `list_plc_blocks(device, group?)` | Alle Bausteine: name, number, type, language, path |
| `list_plc_tag_tables(device)` | Tag-Tabellen mit Namen und Tag-Anzahl |
| `list_plc_tags(device, table?)` | PLC-Tags: name, data_type, address, comment |

### PLC — Export / Import / Kompilieren
| Tool | Beschreibung |
|---|---|
| `compile_plc(device)` | Kompilieren — vor Export bei inkonsistenten Bausteinen |
| `get_plc_block_source(device, block)` | Quellcode lesen: SCL direkt, LAD/FBD als XML |
| `export_plc_block(device, block, path?)` | Baustein als XML exportieren |
| `import_plc_block(device, file)` | Baustein aus XML importieren |
| `export_plc_tagtable(device, table, path?)` | Tag-Tabelle als XML exportieren |
| `import_plc_tagtable(device, file)` | Tag-Tabelle aus XML importieren |
| `save_project()` | Projekt speichern — nach jeder Änderung aufrufen |

### HMI
| Tool | Beschreibung |
|---|---|
| `list_hmi_screens(device)` | Screens mit Größe und Elementanzahl |
| `list_hmi_tags(device, table?)` | Tags mit Typ, High/Low-Limit, Archivierung |
| `list_hmi_alarms(device)` | Diskrete und analoge Alarme |
| `list_hmi_textlists(device)` | Textlisten mit Einträgen |
| `export_hmi_screen(device, screen, path)` | Screen als XML exportieren |
| `export_hmi_tags(device, path)` | Alle Tags als XML exportieren |
| `export_hmi_tagtable(device, table, path?)` | Einzelne Tabelle exportieren |
| `import_hmi_tagtable(device, file)` | Tag-Tabelle importieren |
| `import_hmi_screen(device, file)` | Screen importieren |

### Bibliotheken
| Tool | Beschreibung |
|---|---|
| `list_libraries()` | Projekt- und globale Bibliotheken |
| `list_library_types(lib)` | Typen mit Versionen und Standardversion |
| `list_master_copies(lib)` | Master Copies inkl. Unterordner |
| `get_library_type_versions(lib, type)` | Versionen und Status eines Typs |

### Allgemein
| Tool | Beschreibung |
|---|---|
| `execute_openness(code, mode)` | Python-Code direkt gegen Openness. `mode='read'`\|`'write'` |
| `get_standard_template()` | Vorlage für Standardprojektstruktur |
| `write_import_file(name, content)` | Hochgeladene Datei für Import speichern |
| `read_export_file(path)` | Exportierte Datei lesen und anzeigen |

---

## Typischer Workflow

```
# 1. Verbinden
connect_portal()        → attach (laufende TIA-Instanz)
attach_project()        → offenes Projekt übernehmen

# 2. Orientieren
list_devices()                   → PLC_1, HMI_1 identifizieren
list_plc_blocks("PLC_1")         → Bausteinübersicht
list_plc_tag_tables("PLC_1")     → verfügbare Tabellen

# 3. Arbeiten
get_plc_block_source("PLC_1", "FB_Motor")   → SCL lesen
compile_plc("PLC_1")                         → kompilieren
save_project()                               → speichern
```

---

## Modus 3 — Lokales LLM (Ollama + bridge.py)

```powershell
pip install ollama
ollama pull qwen2.5:14b
python bridge.py
```

`bridge.py` startet `server.py` automatisch als Subprozess und verbindet
Ollama per Function-Calling API mit allen MCP-Tools.

Empfohlene Modelle (CPU-only VM):

| Modell | RAM | Empfehlung |
|---|---|---|
| `qwen2.5-coder:14b` | ~10 GB | Standard — stark bei SCL-Code |
| `qwen2.5:14b` | ~10 GB | Gut für allgemeine Aufgaben |
| `mistral-nemo:12b` | ~8 GB | Schneller, etwas schwächer bei Tool-Calls |

---

## Bekannte TIA V21 Besonderheiten

- Keine `Siemens.Engineering.dll` mehr — aufgeteilt in `net48`-Subfolder
- `SoftwareContainer` liegt unter `Siemens.Engineering.HW.Features`
- `find_software()` sucht nach **DeviceItem**-Namen (`"PLC_1"`), nicht Station-Namen
- `ICompilable` nur per Reflection erreichbar
- Keine rekursiven Funktionen in `execute_openness` — iterativen Stack verwenden
- `project.HwCatalog` existiert nicht — stattdessen `portal.HardwareCatalog`

---

## Häufige Fehler

| Fehler | Lösung |
|---|---|
| `NO_PORTAL_PROCESS` | TIA Portal starten |
| `ACCESS_DENIED` | Als Administrator starten |
| `PROJECT_LOCKED` | Anderen Openness-Client beenden |
| `WRITE_BLOCKED` | `mode='write'` bei `execute_openness` angeben |
| `Block is inconsistent` | `compile_plc()` aufrufen, dann erneut exportieren |
| `find_software` → None | DeviceItem-Namen mit `list_devices()` prüfen |
| Kein Hammer-Symbol | `claude_desktop_config.json` prüfen, venv-Pfad korrekt? |
| Copilot Studio: Verbindungsfehler | Dev Tunnel läuft? `web_server.py` läuft? Port 8000 frei? |
| Tunnel-URL ändert sich | Benannten Tunnel verwenden: `devtunnel create tia-mcp` |

Logs: `C:\tia-mcp\logs\tia_mcp.log`

---

## Projektstruktur (geplant / in Entwicklung)

- **PLCSim Advanced** — `plcsim.py` / `plcsim_server.py` via `Siemens.Simatic.Simulation.Runtime` API
- **Anlagensimulator** — Python-Loop mit snap7, lokales Ollama-Modell als Prozesssimulation
- **Validierungs-Framework** — `validate_project` Tool mit 10 internen Prüfstufen, Excel-Report
- **HMI-Tag-Automation** — Extraktion analoger DB-Variablen → Excel-Review → automatische Tag-Anlage