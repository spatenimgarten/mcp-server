"""
export_hmi_all.py — Vollexport eines HMI-Geräts

Exportiert alle verfügbaren Komponenten eines HMI (Advanced oder Unified)
in einen timestamped Unterordner unter C:\tia-mcp\export\.

Aufruf:
    python export_hmi_all.py <device_name>
    python export_hmi_all.py <device_name> --out C:\mein\pfad
    python export_hmi_all.py --list          (alle Geräte anzeigen)

Voraussetzung: TIA Portal muss laufen und ein Projekt offen sein.
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tia

# ─── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _ok(label, result):
    count = result.get("count", "")
    extra = f" ({count})" if count != "" else ""
    files = result.get("files") or result.get("exported") or []
    if files and isinstance(files, list):
        extra += f" → {len(files)} Datei(en)"
    elif result.get("xml_path") or result.get("json_path"):
        p = result.get("xml_path") or result.get("json_path")
        extra += f" → {Path(p).name}"
    print(f"  ✓  {label}{extra}")


def _skip(label, reason):
    print(f"  –  {label}  [{reason}]")


def _fail(label, err):
    code = err.get("code", "?")
    msg  = err.get("message", str(err))
    if "V21" in code or "NOT_SUPPORTED" in code or "LIMIT" in code:
        print(f"  –  {label}  [V21-Limit]")
    else:
        print(f"  ✗  {label}  [{code}: {msg}]")


def _call(label, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, dict) and result.get("status") == "error":
            _fail(label, result)
            return None
        _ok(label, result if isinstance(result, dict) else {})
        return result
    except Exception as e:
        _fail(label, {"code": type(e).__name__, "message": str(e)})
        return None


# ─── Hauptexport ───────────────────────────────────────────────────────────────

def export_all(device_name: str, out_root: Path):
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_root / f"{device_name}_{ts}"
    out.mkdir(parents=True, exist_ok=True)

    print(f"\nExport: {device_name}  →  {out}\n")

    # HMI-Typ ermitteln
    info = tia.list_devices()
    devices = info.get("devices", []) if isinstance(info, dict) else []
    hmi_type = next(
        (d.get("type", "?") for d in devices if d.get("name") == device_name), "?"
    )
    print(f"  Gerät: {device_name}  Typ: {hmi_type}\n")

    is_advanced = hmi_type == "Advanced"
    is_unified  = hmi_type == "Unified"

    # ── Konfiguration ─────────────────────────────────────────────────────────
    print("[ Konfiguration ]")
    _call("HMI-Konfiguration",     tia.export_hmi_config,            device_name, str(out / "hmi_config.xlsx"))
    if is_unified:
        _call("Runtime-Einstellungen", tia.export_hmi_runtime_settings, device_name, str(out / "hmi_runtime_settings.xlsx"))

    # ── Screens ───────────────────────────────────────────────────────────────
    print("\n[ Screens ]")
    if is_advanced:
        _call("Alle Screens",          tia.export_hmi_screens_all,      device_name, str(out / "screens"))
        _call("Screen Management",     tia.export_hmi_screen_management, device_name, "template",        str(out / "screen_mgmt" / "templates"))
        _call("Screen Slideins",       tia.export_hmi_screen_management, device_name, "slidein",         str(out / "screen_mgmt" / "slideins"))
        _call("Screen Popups",         tia.export_hmi_screen_management, device_name, "popup",           str(out / "screen_mgmt" / "popups"))
        _call("Global Elements",       tia.export_hmi_screen_management, device_name, "global_elements", str(out / "screen_mgmt"))
        _call("Screen Overview",       tia.export_hmi_screen_management, device_name, "overview",        str(out / "screen_mgmt"))
    elif is_unified:
        _skip("Alle Screens",          "V21-Limit — Unified Screens nicht exportierbar")
        _call("Screen Management",     tia.export_hmi_screen_management, device_name, "template",        str(out / "screen_mgmt" / "templates"))
        _call("Screen Slideins",       tia.export_hmi_screen_management, device_name, "slidein",         str(out / "screen_mgmt" / "slideins"))
        _call("Screen Popups",         tia.export_hmi_screen_management, device_name, "popup",           str(out / "screen_mgmt" / "popups"))
        _call("Global Elements",       tia.export_hmi_screen_management, device_name, "global_elements", str(out / "screen_mgmt"))
        _call("Screen Overview",       tia.export_hmi_screen_management, device_name, "overview",        str(out / "screen_mgmt"))

    # ── Tags ──────────────────────────────────────────────────────────────────
    print("\n[ Tags ]")
    _call("HMI-Tags (alle Tabellen)", tia.export_hmi_tags,             device_name, str(out / "tags"))

    # ── Verbindungen ──────────────────────────────────────────────────────────
    print("\n[ Verbindungen ]")
    _call("Connections",              tia.export_hmi_connections,       device_name, str(out / "hmi_connections.json"))

    # ── Alarme ────────────────────────────────────────────────────────────────
    print("\n[ Alarme ]")
    if is_advanced:
        _skip("Alarme", "V21-Limit — Advanced DiscreteAlarms nicht zugänglich")
    else:
        _call("Alarme (JSON)",        tia.export_hmi_alarms,            device_name, str(out / "hmi_alarms.json"))

    # ── Textlisten & Grafiklisten ─────────────────────────────────────────────
    print("\n[ Text- und Grafiklisten ]")
    _call("Textlisten",               tia.export_hmi_textlists,         device_name, str(out / "textlists"))
    _call("Grafiklisten",             tia.export_hmi_graphic_lists,     device_name, str(out / "graphic_lists"))

    # ── Scripts ───────────────────────────────────────────────────────────────
    print("\n[ Scripts ]")
    _call("Scripts",                  tia.export_hmi_scripts,           device_name, str(out / "scripts"))

    # ── Zyklen ────────────────────────────────────────────────────────────────
    print("\n[ Erfassungszyklen ]")
    if is_advanced:
        _call("Cycles (XML)",         tia.export_hmi_cycles,            device_name, str(out / "cycles"))
    else:
        _skip("Cycles", "V21-Limit — Unified Cycles nicht exportierbar")

    # ── Datenlogs ─────────────────────────────────────────────────────────────
    print("\n[ Datenlogs ]")
    if is_unified:
        logs = _call("Datenlogs lesen", tia.list_hmi_logs, device_name)
        if logs:
            p = out / "hmi_logs.json"
            p.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"       → {p.name}")
    else:
        _skip("Datenlogs", "V21-Limit — Advanced DataLogs nicht zugänglich")

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    files = list(out.rglob("*"))
    file_count = sum(1 for f in files if f.is_file())
    size_kb = sum(f.stat().st_size for f in files if f.is_file()) // 1024

    print(f"\n{'─'*60}")
    print(f"  Fertig: {file_count} Dateien · {size_kb} KB")
    print(f"  Pfad:   {out}")
    print(f"{'─'*60}\n")


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Vollexport eines HMI-Geräts aus TIA Portal"
    )
    parser.add_argument("device_name", nargs="?", help="Name des HMI-Geräts")
    parser.add_argument("--out",  default=r"C:\tia-mcp\export", help="Ausgabepfad (Standard: C:\\tia-mcp\\export)")
    parser.add_argument("--list", action="store_true", help="Alle Geräte auflisten")
    args = parser.parse_args()

    tia._setup_logging()
    tia.sta.start()

    if args.list:
        result = tia.list_devices()
        devices = result.get("devices", []) if isinstance(result, dict) else []
        print("\nGeräte im Projekt:\n")
        for d in devices:
            print(f"  {d.get('name','?'):30s}  {d.get('type','?')}")
        print()
        return

    if not args.device_name:
        parser.print_help()
        sys.exit(1)

    export_all(args.device_name, Path(args.out))


if __name__ == "__main__":
    main()
