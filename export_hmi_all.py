r"""
export_hmi_all.py -- Vollexport eines HMI-Geraets

Exportiert alle verfuegbaren Komponenten eines HMI (Advanced oder Unified)
in einen timestamped Unterordner unter C:\tia-mcp\export\.

Aufruf:
    python export_hmi_all.py <item_name>
    python export_hmi_all.py <item_name> --out C:\mein\pfad
    python export_hmi_all.py --list       (alle Geraete + Item-Namen anzeigen)

Voraussetzung: TIA Portal muss laufen und ein Projekt offen sein.
Der item_name ist der Software-Item-Name (z.B. HMI_RT_1), nicht der
Geraetename (z.B. HMI_Advanced). --list zeigt beide.
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tia

# ─── Ausgabe-Hilfsfunktionen ───────────────────────────────────────────────────

def _ok(label, result):
    if not isinstance(result, dict):
        print(f"  OK  {label}")
        return
    count = result.get("count", "")
    extra = f" ({count})" if count != "" else ""
    files = result.get("files") or result.get("exported") or []
    if files and isinstance(files, list):
        extra += f" -> {len(files)} Datei(en)"
    elif result.get("xml_path") or result.get("json_path") or result.get("xlsx_path"):
        p = result.get("xml_path") or result.get("json_path") or result.get("xlsx_path")
        extra += f" -> {Path(p).name}"
    print(f"  OK  {label}{extra}")


def _skip(label, reason):
    print(f"  --  {label}  [{reason}]")


def _fail(label, err):
    if isinstance(err, dict):
        code = err.get("code", "?")
        msg  = err.get("message", "")
        rec  = err.get("recoverable", False)
    else:
        code = type(err).__name__
        msg  = str(err)
        rec  = False
    # V21-Limits und "leer aber ok" als -- anzeigen
    if any(x in code for x in ("V21", "NOT_SUPPORTED", "LIMIT", "NO_SCRIPTS",
                                "NO_TAG_TABLES", "NO_CYCLES", "GL_EMPTY", "EMPTY")):
        print(f"  --  {label}  [nicht verfuegbar: {msg}]")
    elif rec:
        print(f"  --  {label}  [{code}: {msg}]")
    else:
        print(f"  XX  {label}  [{code}: {msg}]")


def _call(label, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, dict) and result.get("status") == "error":
            _fail(label, result)
            return None
        _ok(label, result)
        return result
    except tia.TiaError as e:
        _fail(label, {"code": e.code, "message": e.message, "recoverable": e.recoverable})
        return None
    except Exception as e:
        _fail(label, {"code": type(e).__name__, "message": str(e), "recoverable": False})
        return None


# ─── Geraete-Lookup ────────────────────────────────────────────────────────────

def _find_hmi_item(device_name_or_item: str, devices: list):
    """
    Gibt (item_name, hmi_type) zurueck.
    Sucht zuerst nach item_name (HMI_RT_1), dann nach device_name (HMI_Advanced).
    """
    # Direkt als item_name gefunden?
    for d in devices:
        for sw in d.get("software", []):
            if sw.get("item") == device_name_or_item and sw.get("type") in ("Advanced", "Unified"):
                return sw["item"], sw["type"]
    # Als Geraete-Name gefunden?
    for d in devices:
        if d.get("name") == device_name_or_item:
            for sw in d.get("software", []):
                if sw.get("type") in ("Advanced", "Unified"):
                    return sw["item"], sw["type"]
    return None, None


# ─── Hauptexport ───────────────────────────────────────────────────────────────

def export_all(name_arg: str, out_root: Path, devices: list):
    item_name, hmi_type = _find_hmi_item(name_arg, devices)
    if not item_name:
        print(f"\nFehler: '{name_arg}' nicht gefunden. --list zeigt verfuegbare Geraete.\n")
        sys.exit(1)

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_root / f"{item_name}_{ts}"
    out.mkdir(parents=True, exist_ok=True)

    print(f"\nExport: {item_name}  Typ: {hmi_type}")
    print(f"Pfad:   {out}\n")

    is_adv = hmi_type == "Advanced"
    is_uni = hmi_type == "Unified"

    # ── Konfiguration ─────────────────────────────────────────────────────────
    print("[ Konfiguration ]")
    _call("HMI-Konfiguration",      tia.export_hmi_config,            item_name, str(out / "hmi_config.xlsx"))
    if is_uni:
        _call("Runtime-Einstellungen", tia.export_hmi_runtime_settings, item_name, str(out / "hmi_runtime_settings.xlsx"))

    # ── Screens ───────────────────────────────────────────────────────────────
    print("\n[ Screens ]")
    if is_adv:
        _call("Alle Screens",       tia.export_hmi_screens_all,       item_name, str(out / "screens"))
    else:
        _skip("Alle Screens",       "V21-Limit -- Unified Screens nicht exportierbar")

    scr_out = str(out / "screen_mgmt")
    _call("Templates",              tia.export_hmi_screen_management, item_name, "template",        scr_out + r"\templates")
    _call("Slideins",               tia.export_hmi_screen_management, item_name, "slidein",         scr_out + r"\slideins")
    _call("Popups",                 tia.export_hmi_screen_management, item_name, "popup",           scr_out + r"\popups")
    _call("Global Elements",        tia.export_hmi_screen_management, item_name, "global_elements", scr_out)
    _call("Screen Overview",        tia.export_hmi_screen_management, item_name, "overview",        scr_out)

    # ── Tags ──────────────────────────────────────────────────────────────────
    print("\n[ Tags ]")
    _call("HMI-Tags",               tia.export_hmi_tags,              item_name, str(out / "tags"))

    # ── Verbindungen — JSON im Hauptthread schreiben (STA-Thread-Schreibschutz) ──
    print("\n[ Verbindungen ]")
    conn_result = _call("Connections lesen", tia.list_hmi_connections, item_name)
    if conn_result:
        p = out / "hmi_connections.json"
        p.write_text(json.dumps(conn_result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"       -> {p.name}  ({conn_result.get('count', '?')} Verbindungen)")

    # ── Alarme — JSON im Hauptthread schreiben ────────────────────────────────
    print("\n[ Alarme ]")
    if is_adv:
        _skip("Alarme",             "V21-Limit -- Advanced DiscreteAlarms nicht zugaenglich")
    else:
        alarm_result = _call("Alarme lesen", tia.list_hmi_alarms, item_name)
        if alarm_result:
            p = out / "hmi_alarms.json"
            p.write_text(json.dumps(alarm_result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"       -> {p.name}  ({alarm_result.get('count', '?')} Alarme)")

    # ── Textlisten & Grafiklisten ─────────────────────────────────────────────
    print("\n[ Text- und Grafiklisten ]")
    _call("Textlisten",             tia.export_hmi_textlists,         item_name, str(out / "textlists"))
    _call("Grafiklisten",           tia.export_hmi_graphic_lists,     item_name, str(out / "graphic_lists"))

    # ── Scripts ───────────────────────────────────────────────────────────────
    print("\n[ Scripts ]")
    _call("Scripts",                tia.export_hmi_scripts,           item_name, str(out / "scripts"))

    # ── Zyklen ────────────────────────────────────────────────────────────────
    print("\n[ Erfassungszyklen ]")
    if is_adv:
        _call("Cycles (XML)",       tia.export_hmi_cycles,            item_name, str(out / "cycles"))
    else:
        _skip("Cycles",             "V21-Limit -- Unified Cycles nicht exportierbar")

    # ── Datenlogs ─────────────────────────────────────────────────────────────
    print("\n[ Datenlogs ]")
    if is_uni:
        logs = _call("Datenlogs lesen", tia.list_hmi_logs, item_name)
        if logs:
            p = out / "hmi_logs.json"
            p.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"       -> {p.name}")
    else:
        _skip("Datenlogs",          "V21-Limit -- Advanced DataLogs nicht zugaenglich")

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    all_files  = [f for f in out.rglob("*") if f.is_file()]
    file_count = len(all_files)
    size_kb    = sum(f.stat().st_size for f in all_files) // 1024

    print(f"\n{'='*60}")
    print(f"  Fertig:  {file_count} Dateien  {size_kb} KB")
    print(f"  Pfad:    {out}")
    print(f"{'='*60}\n")


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Vollexport eines HMI-Geraets aus TIA Portal"
    )
    parser.add_argument("device_name", nargs="?",
                        help="Item-Name des HMI (z.B. HMI_RT_1) -- --list zeigt alle")
    parser.add_argument("--out", default=r"C:\tia-mcp\export",
                        help=r"Ausgabepfad (Standard: C:\tia-mcp\export)")
    parser.add_argument("--list", action="store_true",
                        help="Alle Geraete mit Item-Namen anzeigen")
    args = parser.parse_args()

    tia._setup_logging()
    tia.sta.start()

    # TIA Portal verbinden
    print("Verbinde mit TIA Portal...")
    r = tia.connect_portal(mode="attach")
    if isinstance(r, dict) and r.get("status") == "error":
        print(f"Fehler: {r.get('message')}")
        sys.exit(1)
    print(f"  Verbunden -- TIA {r.get('tia_version','?')}  PID {r.get('process_id','?')}")

    # Projekt uebernehmen
    print("Uebernehme offenes Projekt...")
    r = tia.attach_project()
    if isinstance(r, dict) and r.get("status") == "error":
        print(f"Fehler: {r.get('message')}")
        sys.exit(1)
    print(f"  Projekt: {r.get('project','?')}\n")

    # Geraete laden (benoetigt fuer --list und Typ-Erkennung)
    info    = tia.list_devices()
    devices = info.get("devices", []) if isinstance(info, dict) else []

    if args.list:
        print("Geraete im Projekt:\n")
        print(f"  {'Geraet':<25}  {'Item-Name':<25}  Typ")
        print(f"  {'-'*25}  {'-'*25}  {'-'*10}")
        for d in devices:
            dname = d.get("name", "?")
            for sw in d.get("software", []):
                iname = sw.get("item", "?")
                itype = sw.get("type", "?")
                print(f"  {dname:<25}  {iname:<25}  {itype}")
        print()
        return

    if not args.device_name:
        parser.print_help()
        sys.exit(1)

    export_all(args.device_name, Path(args.out), devices)


if __name__ == "__main__":
    main()
