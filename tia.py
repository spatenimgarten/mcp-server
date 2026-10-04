"""
tia.py — TIA Portal Openness Anbindung
STA Thread · Fehler · Logging · Session · HMI · Bibliothek · Executor
"""

# ═══════════════════════════════════════════════════════════════════════════════
# VERSION
# ═══════════════════════════════════════════════════════════════════════════════
VERSION      = "1.17.2"
VERSION_DATE = "2026-10-03"
VERSION_INFO = {
    "version":      VERSION,
    "date":         VERSION_DATE,
    "file":         __file__,
    "changes": [
        "1.17.2: list_hmi_tag_usage protokolliert den Fortschritt (Bild i/n, Alarme, Archiv, Skripte, "
        "Variablen) ins Log; Worker-Timeout einstellbar (TIA_MCP_WORKER_TIMEOUT, Standard 300 s, lange "
        "Operationen 900 s).",
        "1.17.1: Variablentabellen in Ordnern (TagTableGroups, rekursiv) werden gelesen — list_hmi_tags, list_hmi_tag_usage und der Tabellen-Export uebersahen sie bisher.",
        "1.17.0: list_hmi_tag_usage liefert zusaetzlich members (aufgeloeste Variablen mit UDT-Elementen und "
        "Array-Eintraegen in Deklarationsreihenfolge, Runtime-Datentyp) und system_members — damit braucht "
        "tools/json2vorlage.py keine Offline-Konfiguration mehr.",
        "1.16.0: list_hmi_tag_usage — Verwendung der HMI-Variablen (Unified): Bilder (Tag-/Skript-"
        "Dynamisierungen, Ereignisse, Eigenschafts-Ereignisse), Bit-/Analogalarme, Archivierung, globale "
        "Skriptmodule; liefert usages, tags (table/datatype/used/where) und unused.",
        "1.15.0: TIA-Openness laeuft in eigenem Worker-Prozess (worker.py); Trennen, Leerlauf "
        "(TIA_MCP_IDLE_DISCONNECT, Standard 120 s) und Timeout beenden den Worker — nur das gibt TIA "
        "zuverlaessig frei (vorher hing TIA beim Projekt-Schliessen trotz Dispose). Naechster Aufruf "
        "startet neuen Worker und verbindet automatisch neu. Ausserdem: "
        "STA-Thread pumpt Window-Messages; Openness-Verbindung wird nach "
        "Leerlauf getrennt (TIA_MCP_IDLE_DISCONNECT, Standard 120 s) und beim naechsten Aufruf automatisch "
        "neu aufgebaut; alte Verbindungen werden per Dispose freigegeben (connect_portal, Timeout); nach "
        "Timeout kein zweiter STA-Thread mehr; TIA-Rueckfragen werden abgebrochen statt zu blockieren "
        "(TIA_MCP_DIALOGS); connect_portal waehlt den richtigen TIA-Prozess; close_portal beendet nur den "
        "eigenen Prozess; Dialog-Handler werden vor Dispose abgemeldet (sonst hing TIA beim "
        "Projekt-Schliessen). Neu: disconnect_portal. Fix: create_project, open_portal. Sandbox: Exception, "
        "secure_string, dir_info, file_info.",
        "1.14.1: set_plc_block_source — ueber externe Quelle (GenerateSource / GenerateBlocksFromSource) "
        "statt Token-XML; ganzer Baustein oder nur Rumpf; Offline-Pruefung; Baustein wird danach "
        "uebersetzt (Fehler mit Zeile). get_plc_block_source liefert SCL via GenerateSource "
        "(vorher unbrauchbar zusammengesetzte Tokens). compile_plc liefert Fehlertexte.",
        "1.14.0: get_online_state / go_online / go_offline — SPS online/offline via OnlineProvider, "
        "OnlineLegitimation-Handler (Anmeldung anonym/Benutzer, Passwort, TLS-Zertifikat)",
        "1.13.2: STA-Loop — recoverable TiaErrors nur noch als DEBUG geloggt (kein ERROR-Traceback)",
        "1.13.1: _get_hmi — akzeptiert jetzt device.Name UND item.Name (z.B. HMI_Advanced = HMI_RT_1)",
        "1.13.0: export/import_hmi_alarms — JSON-basiert via GetAttributeInfos (kein V21-API-Export)",
        "1.12.0: set_hmi_log — Unified DataLog-Einstellungen schreiben (Name, Segment, Settings)",
        "1.11.0: list_hmi_logs — Unified DataLogs mit Segment, Settings, Backup-Attributen",
        "1.10.0: list_hmi_connections — nicht-integrierte HMI-Verbindungen (Advanced+Unified); list_hmi_textlists Fix: sucht alle Items der Station",
        "1.9.1: list_hmi_cycles — Periode/Einheit aus Name geparst wenn kein Attribut; GetAttributeInfos für alle Cycle-Attribute",
        "1.9.0: list_hmi_cycles + list_hmi_scheduled_tasks — Erfassungszyklen und geplante Tasks (Advanced/Unified)",
        "1.8.0: get/set/export_hmi_config — HMI-DeviceItem-Attribute für Advanced UND Unified, Unified mit RuntimeSettings-Sheet",
        "1.7.0: get/set/export_plc_config — SPS-DeviceItem-Attribute lesen, schreiben, als Excel exportieren",
        "1.6.0: get/set/export_hmi_runtime_settings — Unified Runtime-Einstellungen lesen, schreiben, exportieren",
        "1.5.0: export_hw_config — Hardware-Konfiguration als Excel exportieren",
        "1.4.0: BUG-15 Fix: list_plc_tags comment-Feld via _mltext() korrekt auslesen",
        "1.3.0: list_plc_blocks — alle Bausteine inkl. Untergruppen, optionaler Gruppenfilter",
        "1.3.0: list_plc_tag_tables — alle Tag-Tabellen inkl. Untergruppen",
        "1.3.0: list_plc_tags — Tags einer Tabelle mit Typ, Adresse, Kommentar",
        "1.3.0: list_plc_udts — alle UDTs/Strukturen inkl. Untergruppen",
        "1.2.0: import_hmi_screen Screen-Name aus XML gelesen für korrektes Delete-vor-Import",
        "1.1.0: STA-Timeout 60s + Auto-Restart, export_hmi_tags Unified-Workaround, VBScriptFolder",
        "1.0.0: BUG-11–14 gefixt: rekursive Screen-Suche, Unified-Typ-Erkennung, HmiTarget-API",
    ]
}

import os, sys, threading, queue, logging, textwrap, re, time
from pathlib import Path
from typing import Any, Callable
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

def _setup_logging(log_dir="C:/tia-mcp/logs", level="INFO"):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / "tia_mcp.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            RotatingFileHandler(log_file, maxBytes=5*1024*1024,
                                backupCount=3, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ]
    )

def _log(name): return logging.getLogger(f"tia.{name}")

# ═══════════════════════════════════════════════════════════════════════════════
# FEHLER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TiaError(Exception):
    code: str
    message: str
    recoverable: bool
    details: dict | None = None

    def to_dict(self):
        return {"status":"error","code":self.code,"message":self.message,
                "recoverable":self.recoverable,
                **({"details":self.details} if self.details else {})}

_ERR_PATTERNS = [
    ("currently locked",  "PROJECT_LOCKED",   "Projekt gesperrt. Andere Session beenden.", False),
    ("No TIA Portal",     "NO_PORTAL_PROCESS","Kein TIA Portal Prozess. TIA Portal starten.", True),
    ("Access is denied",  "ACCESS_DENIED",    "Zugriff verweigert. Als Administrator starten.", False),
    ("already in use",    "PORTAL_IN_USE",    "TIA Portal durch andere Openness-Anwendung belegt.", False),
    ("FileNotFound",      "FILE_NOT_FOUND",   "Datei nicht gefunden. Pfad pruefen.", True),
    ("not found",         "OBJECT_NOT_FOUND", "Objekt nicht gefunden.", True),
]

def _translate(exc):
    msg = str(exc)
    for pattern, code, text, rec in _ERR_PATTERNS:
        if pattern.lower() in msg.lower():
            return TiaError(code, text, rec, {"original": msg})
    return TiaError("TIA_ERROR", f"TIA Fehler: {msg}", False,
                    {"type": type(exc).__name__, "original": msg})

def _tia_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except TiaError:
        raise
    except Exception as e:
        raise _translate(e) from e

# ═══════════════════════════════════════════════════════════════════════════════
# STA THREAD
# ═══════════════════════════════════════════════════════════════════════════════

_STA_TIMEOUT_DEFAULT  = 60   # Sekunden für normale Operationen
_STA_TIMEOUT_HEAVY    = 300  # Sekunden für schwere Ops: open_project, compile, close_portal
_STA_POLL_S           = 0.05 # Wartezeit je Durchlauf, dazwischen werden Window-Messages gepumpt

# Openness-Verbindung nach so vielen Sekunden ohne Aufruf trennen (0 = nie).
# Eine offene Verbindung blockiert sonst die TIA-Oberflaeche, wenn dort gearbeitet wird.
# Der naechste Aufruf verbindet automatisch neu (siehe _Session.ensure_portal).
_IDLE_DISCONNECT_S = float(os.environ.get("TIA_MCP_IDLE_DISCONNECT", "120"))

@dataclass
class _Job:
    fn: Callable; args: tuple; kwargs: dict; result_q: queue.Queue; timeout: float

class _Err:
    def __init__(self, e): self.exception = e

def _pump_messages():
    """Window-Messages des STA-Threads abarbeiten. Ohne Pumpe warten Rueckrufe von
    TIA (Events, Lebenszeichen) endlos und die TIA-Oberflaeche friert ein."""
    try:
        import pythoncom
        pythoncom.PumpWaitingMessages()
    except ImportError:
        pass

class STAThread:
    _instance = None; _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance._started = False
                cls._instance._thread  = None
                cls._instance._generation = 0
                cls._instance._last_job = time.monotonic()
        return cls._instance

    def _spawn(self):
        """Neuen STA-Thread mit eigener Queue starten. Die Generation sorgt dafuer,
        dass ein alter, nach Timeout verwaister Thread keine neuen Jobs mehr annimmt."""
        self._generation += 1
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._loop, args=(self._q, self._generation),
                                        name=f"TIA-STA-{self._generation}", daemon=True)
        self._thread.start()
        self._started = True

    def start(self):
        if self._started: return
        self._spawn()
        _log("sta").info("STA Thread gestartet")

    def stop(self):
        if not self._started: return
        self._q.put(None); self._started = False
        _log("sta").info("STA Thread gestoppt")

    def _restart(self):
        """STA-Thread neu starten nach Timeout. Alte Portal-Instanz im Hintergrund
        freigeben, damit TIA nicht auf den haengenden Client wartet."""
        _log("sta").warning("STA Thread neu gestartet nach Timeout.")
        self._started = False
        _sess.release_async()
        self._spawn()

    def run(self, fn, *args, timeout=None, **kwargs):
        if not self._started: raise RuntimeError("STAThread nicht gestartet")
        t = timeout if timeout is not None else _STA_TIMEOUT_DEFAULT
        rq = queue.Queue()
        self._q.put(_Job(fn, args, kwargs, rq, t))
        try:
            out = rq.get(timeout=t)
        except queue.Empty:
            _log("sta").warning(f"STA Timeout nach {t}s — Thread wird neu gestartet.")
            self._restart()
            raise TiaError(
                "STA_TIMEOUT",
                f"TIA-Operation hat nach {t}s nicht geantwortet. "
                "STA-Thread wurde neu gestartet. "
                "Wartet in TIA ein Dialog? Der naechste Aufruf verbindet automatisch neu.",
                True,
                {"hint": "STA thread restarted, portal released"}
            )
        if isinstance(out, _Err): raise out.exception
        return out

    def _loop(self, q, generation):
        try:
            import pythoncom; pythoncom.CoInitialize()
        except ImportError: pass
        while generation == self._generation:
            try:
                job = q.get(timeout=_STA_POLL_S)
            except queue.Empty:
                _pump_messages()
                self._check_idle()
                continue
            if job is None: break
            try:
                job.result_q.put(job.fn(*job.args, **job.kwargs))
            except Exception as e:
                # Recoverable TiaErrors (leere Listen, nicht vorhandene Objekte) nur als DEBUG
                if isinstance(e, TiaError) and e.recoverable:
                    _log("sta").debug(str(e))
                else:
                    _log("sta").error(str(e), exc_info=True)
                job.result_q.put(_Err(e))
            finally:
                self._last_job = time.monotonic()
        if generation != self._generation:
            _log("sta").info(f"Verwaister STA-Thread {generation} beendet.")
        try:
            import pythoncom; pythoncom.CoUninitialize()
        except ImportError: pass

    def _check_idle(self):
        if (_IDLE_DISCONNECT_S > 0 and _sess.portal is not None
                and time.monotonic() - self._last_job > _IDLE_DISCONNECT_S):
            _log("session").info(f"Openness-Verbindung nach {_IDLE_DISCONNECT_S:.0f}s Leerlauf getrennt "
                                 "(naechster Aufruf verbindet automatisch neu).")
            _sess.release()

sta = STAThread()

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════════════════════════════

_TIA_BASE = r"C:\Program Files\Siemens\Automation"
_VERSIONS = ["V21","V20","V19","V18"]

class _Session:
    portal = None; project = None
    tia_version = None; dll_path = None; _dlls_loaded = False

    # DLLs die geladen werden muessen
    _V21_DLLS = [
        "Siemens.Engineering.Base.dll",      # Hauptassembly (TiaPortal, Project, ...)
        "Siemens.Engineering.Step7.dll",     # PLC (PlcSoftware, Blocks, Tags)
        "Siemens.Engineering.WinCC.dll",     # HMI Advanced
        "Siemens.Engineering.WinCCUnified.dll",  # HMI Unified
        "Siemens.Engineering.AddIn.Base.dll",    # AddIn-Basis
    ]
    _LEGACY_DLLS = [
        "Siemens.Engineering.dll",           # V19/V20 Monolith
        "Siemens.Engineering.Hmi.dll",
        "Siemens.Engineering.HmiUnified.dll",
    ]

    def ensure_dlls(self):
        if self._dlls_loaded: return
        # Pfad suchen — V21 erkennt man an Base.dll statt Engineering.dll
        for v in _VERSIONS:
            candidates = [
                Path(_TIA_BASE) / f"Portal {v}" / "PublicAPI" / v / "net48",  # V21
                Path(_TIA_BASE) / f"Portal {v}" / "PublicAPI" / v,            # V19/V20
                Path(_TIA_BASE) / f"Portal {v}" / "PublicAPI",                # Fallback
            ]
            for p in candidates:
                # V21: Base.dll, aeltere: Engineering.dll
                if (p / "Siemens.Engineering.Base.dll").exists() or                    (p / "Siemens.Engineering.dll").exists():
                    self.tia_version, self.dll_path = v, str(p); break
            if self.dll_path: break
        if not self.dll_path:
            raise TiaError("TIA_NOT_INSTALLED","Keine TIA Installation.",False,{"searched":_VERSIONS})

        import clr
        if self.dll_path not in sys.path: sys.path.append(self.dll_path)

        # Entscheiden ob V21 (aufgeteilte DLLs) oder aelter (Monolith)
        is_v21 = (Path(self.dll_path) / "Siemens.Engineering.Base.dll").exists()
        dlls = self._V21_DLLS if is_v21 else self._LEGACY_DLLS

        for dll in dlls:
            f = os.path.join(self.dll_path, dll)
            if os.path.exists(f):
                try:
                    clr.AddReference(f)
                    _log("session").debug(f"DLL geladen: {dll}")
                except Exception as e:
                    _log("session").warning(f"DLL nicht geladen: {dll} — {e}")

        _log("session").info(f"TIA {self.tia_version} DLLs geladen aus {self.dll_path}")
        self._dlls_loaded = True

    # Fuer automatisches Neuverbinden nach Leerlauf-Trennung / Timeout (nur attach-Modus)
    auto_reconnect = False; pid = None; project_path = None
    _handlers = None   # Referenzen auf Dialog-Handler (gegen Garbage Collection)

    def ensure_portal(self):
        if not self.portal and self.auto_reconnect:
            self._reattach()
        if not self.portal:
            raise TiaError("NOT_CONNECTED","Nicht verbunden. connect_portal aufrufen.",True)

    def ensure_project(self):
        self.ensure_portal()
        if not self.project and self.auto_reconnect and self.project_path:
            self.project = _find_project(self.portal, self.project_path)
        if not self.project:
            raise TiaError("NO_PROJECT","Kein Projekt. open_project aufrufen.",True)

    def remember_project(self, project):
        self.project = project
        try: self.project_path = str(project.Path)
        except Exception: self.project_path = None

    def _reattach(self):
        """Erneut an denselben TIA-Prozess anhaengen (nur im STA-Thread aufrufen)."""
        from Siemens.Engineering import TiaPortal
        proc = _pick_process(list(TiaPortal.GetProcesses()), self.pid, self.project_path)
        if proc is None:
            self.auto_reconnect = False
            raise TiaError("NO_PORTAL_PROCESS", "TIA-Prozess fuer Neuverbindung nicht gefunden. "
                           "connect_portal aufrufen.", True)
        self.attach(proc)
        _log("session").info(f"Automatisch neu verbunden: PID={proc.Id}")

    def attach(self, proc):
        self.release()
        self.portal = proc.Attach()
        self.pid = proc.Id
        _install_dialog_handlers(self.portal)

    def release(self):
        """Openness-Verbindung freigeben (Handler abmelden + Dispose). Im STA-Thread aufrufen."""
        p, h = self.portal, self._handlers
        self.portal, self.project, self._handlers = None, None, None
        if p is None:
            return
        _safe_dispose(p, h)

    def release_async(self, wait_s=5):
        """Freigabe aus fremdem Thread (nach STA-Timeout): Dispose in Hilfs-Thread, damit
        ein haengender TIA-Aufruf den Aufrufer nicht mitblockiert."""
        p, h = self.portal, self._handlers
        self.portal, self.project, self._handlers = None, None, None
        if p is None:
            return
        t = threading.Thread(target=lambda: _safe_dispose(p, h), name="TIA-Dispose", daemon=True)
        t.start(); t.join(wait_s)
        if t.is_alive():
            _log("session").warning(f"Dispose nach Timeout dauert > {wait_s}s — laeuft im Hintergrund weiter.")

_sess = _Session()

def _safe_dispose(portal, handlers=None):
    """Dialog-Handler abmelden, dann Dispose. Bleiben die Handler angemeldet, versucht TIA
    beim Schliessen des Projekts noch den (getrennten) Client zu benachrichtigen und haengt,
    bis der Server-Prozess endet."""
    if handlers:
        try:
            portal.Confirmation -= handlers[0]
            portal.Notification -= handlers[1]
        except Exception as e:
            _log("session").warning(f"Dialog-Handler abmelden fehlgeschlagen (ignoriert): {e}")
    try:
        portal.Dispose()
    except Exception as e:
        _log("session").warning(f"Dispose fehlgeschlagen (ignoriert): {e}")

def _norm_path(p):
    return str(p).replace("/", "\\").rstrip("\\").lower() if p else ""

def _find_project(portal, path):
    for pr in portal.Projects:
        try:
            if _norm_path(pr.Path) == _norm_path(path):
                return pr
        except Exception:
            pass
    return None

def _pick_process(procs, pid=None, project_path=None):
    """TIA-Prozess waehlen: gleiche PID > Prozess mit dem gesuchten Projekt >
    einziger Prozess mit offenem Projekt > erster Prozess."""
    if not procs:
        return None
    if pid is not None:
        for p in procs:
            if p.Id == pid:
                return p
    def proj(p):
        try: return str(p.ProjectPath) if p.ProjectPath else ""
        except Exception: return ""
    if project_path:
        for p in procs:
            if _norm_path(proj(p)) == _norm_path(project_path):
                return p
    with_project = [p for p in procs if proj(p)]
    if len(with_project) == 1:
        return with_project[0]
    return procs[0]

# Verhalten bei TIA-Rueckfragen waehrend eines Openness-Aufrufs:
#   "cancel" (Standard): mit Abbrechen/Nein beantworten -> Aufruf scheitert mit Meldung statt zu haengen
#   "off":               nicht eingreifen (Dialog erscheint in der Oberflaeche, Aufruf wartet)
_DIALOG_MODE = os.environ.get("TIA_MCP_DIALOGS", "cancel").lower()

def _install_dialog_handlers(portal):
    if _DIALOG_MODE == "off":
        return
    log = _log("dialog")
    try:
        from Siemens.Engineering import ConfirmationResult
    except Exception as e:
        log.warning(f"ConfirmationResult nicht verfuegbar, keine Dialog-Handler: {e}")
        return

    def on_confirmation(sender, e):
        try:
            choices = str(e.Choices)
            pick = next((c for c in ("Cancel", "No") if c in choices), None)
            if pick:
                e.Result = getattr(ConfirmationResult, pick)
                e.IsHandled = True
            log.warning(f"TIA-Rueckfrage -> {pick or 'nicht beantwortet'} | {e.Caption}: {e.Text} "
                        f"(Optionen: {choices})")
        except Exception as ex:
            log.error(f"Confirmation-Handler: {ex}")

    def on_notification(sender, e):
        try:
            e.IsHandled = True
            log.warning(f"TIA-Meldung quittiert | {e.Caption}: {e.Text} {getattr(e, 'DetailText', '') or ''}")
        except Exception as ex:
            log.error(f"Notification-Handler: {ex}")

    try:
        portal.Confirmation += on_confirmation
        portal.Notification += on_notification
        _sess._handlers = (on_confirmation, on_notification)
    except Exception as e:
        log.warning(f"Dialog-Handler konnten nicht registriert werden: {e}")

def connect_portal(mode="attach"):
    def _run():
        _sess.ensure_dlls()
        from Siemens.Engineering import TiaPortal, TiaPortalMode
        if mode == "attach":
            procs = list(TiaPortal.GetProcesses())
            if not procs: raise TiaError("NO_PORTAL_PROCESS","TIA Portal starten.",True)
            proc = _pick_process(procs, project_path=_sess.project_path)
            _sess.attach(proc)
            _sess.auto_reconnect = True
            _log("session").info(f"Attached PID={proc.Id} V={_sess.tia_version} "
                                 f"({len(procs)} TIA-Prozess(e))")
            return {"status":"ok","mode":"attach","tia_version":_sess.tia_version,"process_id":proc.Id,
                    "tia_processes":len(procs)}
        _sess.release()
        _sess.auto_reconnect = False
        tm = TiaPortalMode.WithoutUserInterface if mode=="headless" else TiaPortalMode.WithUserInterface
        _sess.portal = TiaPortal(tm)
        try: _sess.pid = _sess.portal.GetCurrentProcess().Id
        except Exception: _sess.pid = None
        _install_dialog_handlers(_sess.portal)
        _log("session").info(f"Gestartet mode={mode} V={_sess.tia_version}")
        return {"status":"ok","mode":mode,"tia_version":_sess.tia_version}
    return sta.run(_tia_call, _run)

def open_portal(mode="gui"):
    """TIA Portal als neuen Prozess starten (gui oder headless)."""
    if mode not in ("gui", "headless"):
        raise TiaError("INVALID_MODE", "mode muss 'gui' oder 'headless' sein.", True)
    return connect_portal(mode)

def disconnect_portal():
    """Openness-Verbindung trennen, TIA bleibt offen. Danach ist die TIA-Oberflaeche frei."""
    def _run():
        was = _sess.portal is not None
        _sess.release()
        _sess.auto_reconnect = False
        _log("session").info("Openness-Verbindung getrennt (disconnect_portal).")
        return {"status":"ok","disconnected":was}
    return sta.run(_tia_call, _run)

def attach_project():
    """Holt das bereits in TIA Portal geoeffnete Projekt — kein Pfad noetig."""
    def _run():
        _sess.ensure_portal()
        projects = list(_sess.portal.Projects)
        if not projects:
            raise TiaError("NO_PROJECT",
                "Kein Projekt in TIA Portal offen. Bitte zuerst ein Projekt oeffnen.",True)
        _sess.remember_project(projects[0])
        _log("session").info(f"Projekt uebernommen: {_sess.project.Name}")
        return {"status":"ok","project":_sess.project.Name,
                "path":str(_sess.project.Path)}
    return sta.run(_tia_call, _run)

def create_project(path, name=None):
    """Neues Projekt anlegen. path = Zielordner (wird angelegt), name = Projektname."""
    def _run():
        _sess.ensure_portal()
        from System.IO import DirectoryInfo
        name_ = name or Path(path).name
        di = DirectoryInfo(path)
        if not di.Exists:
            di.Create()
        proj = _sess.portal.Projects.Create(di, name_)
        _sess.remember_project(proj)
        _log("session").info(f"Projekt angelegt: {proj.Name} in {path}")
        return {"status":"ok","name":proj.Name,"path":str(proj.Path.FullName)}
    return sta.run(_tia_call, _run, timeout=_STA_TIMEOUT_HEAVY)

def open_project(path, retries=10, retry_delay=10):
    """
    Projekt oeffnen (.ap21).
    retries/retry_delay: Wartet bis TIA Portal bereit ist — sinnvoll nach connect_portal(mode='gui').
    Standard: 10 Versuche x 10 Sekunden = max. 100 Sekunden.
    """
    import time
    def _run():
        _sess.ensure_portal()
        from System.IO import FileInfo
        fi = FileInfo(path)
        if not fi.Exists: raise TiaError("FILE_NOT_FOUND",f"Nicht gefunden: {path}",True)
        last_exc = None
        for attempt in range(max(1, retries)):
            try:
                _sess.remember_project(_sess.portal.Projects.Open(fi))
                _log("session").info(f"Projekt: {_sess.project.Name} (Versuch {attempt+1})")
                return {"status":"ok","project":_sess.project.Name,"path":path}
            except Exception as e:
                last_exc = e
                _log("session").warning(f"open_project Versuch {attempt+1}/{retries} fehlgeschlagen: {e}")
                if attempt < retries - 1:
                    time.sleep(retry_delay)
        raise _translate(last_exc)
    return sta.run(_tia_call, _run, timeout=_STA_TIMEOUT_HEAVY)

def save_project():
    """Aktuelles Projekt speichern."""
    def _run():
        _sess.ensure_project()
        _sess.project.Save()
        _log("session").info(f"Projekt gespeichert: {_sess.project.Name}")
        return {"status":"ok","project":_sess.project.Name}
    return sta.run(_tia_call, _run, timeout=_STA_TIMEOUT_HEAVY)

def close_project():
    """
    Aktuelles Projekt schliessen (ohne Speichern).
    Vorher save_project() aufrufen um Aenderungen zu sichern.
    """
    def _run():
        _sess.ensure_project()
        name = _sess.project.Name
        _sess.project.Close()
        _sess.project = None
        _sess.project_path = None
        _log("session").info(f"Projekt geschlossen: {name}")
        return {"status":"ok","closed":name}
    return sta.run(_tia_call, _run)

def close_portal():
    """
    TIA Portal beenden (Dispose + taskkill).
    Schliesst alle offenen Projekte und beendet den TIA-Prozess.
    Vorher save_project() und close_project() aufrufen.
    """
    import threading as _threading
    import subprocess as _subprocess

    if not _sess.portal:
        raise TiaError("NOT_CONNECTED", "Nicht verbunden. connect_portal aufrufen.", True)
    _sess.auto_reconnect = False   # nach dem Beenden nicht wieder anhaengen
    _sess.project_path = None

    # PID vor dem Dispose merken — danach ist der Portal-Handle ggf. ungültig
    # Nur den Prozess der eigenen Verbindung beenden - nie "irgendeinen" TIA-Prozess
    pid_holder = [_sess.pid]
    def _get_pid():
        try:
            from Siemens.Engineering import TiaPortal
            procs = list(TiaPortal.GetProcesses())
            if len(procs) == 1:
                pid_holder[0] = procs[0].Id
        except Exception:
            pass
    if pid_holder[0] is None:
        try:
            sta.run(_get_pid)
        except Exception:
            pass

    # Dispose im STA-Thread mit 30s-Timeout
    done = _threading.Event()
    dispose_error = [None]

    def _dispose():
        try:
            _sess.release()          # Handler abmelden + Dispose
        except Exception as e:
            dispose_error[0] = e
        finally:
            _sess.portal  = None
            _sess.project = None
            done.set()

    rq = queue.Queue()
    sta._q.put(_Job(_dispose, (), {}, rq, 30))

    timed_out = not done.wait(timeout=30)
    if timed_out:
        _log("session").warning("close_portal: Dispose-Timeout nach 30s")
        _sess.portal  = None
        _sess.project = None

    if dispose_error[0]:
        _log("session").warning(f"close_portal Dispose-Fehler (ignoriert): {dispose_error[0]}")

    # Prozess killen — Dispose trennt nur die API-Verbindung, beendet TIA nicht immer
    killed = False
    if pid_holder[0]:
        try:
            _subprocess.run(
                ["taskkill", "/F", "/PID", str(pid_holder[0])],
                stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
                timeout=10
            )
            killed = True
            _log("session").info(f"TIA Portal Prozess {pid_holder[0]} beendet.")
        except Exception as ke:
            _log("session").error(f"taskkill fehlgeschlagen: {ke}")

    msg = "TIA Portal beendet."
    if timed_out:
        msg = "TIA Portal beendet (Dispose-Timeout, force kill)."
    elif killed:
        msg = "TIA Portal beendet."

    return {"status": "ok", "message": msg}

def get_session_status():
    def _run():
        ver = None
        for v in _VERSIONS:
            for sub in [f"PublicAPI/{v}/net48", f"PublicAPI/{v}"]:
                p = Path(_TIA_BASE) / f"Portal {v}" / sub
                if (p / "Siemens.Engineering.Base.dll").exists() or \
                   (p / "Siemens.Engineering.dll").exists():
                    ver = v; break
            if ver: break
        # project.Name nur aufrufen wenn Projekt bekannt — im STA-Thread ist das sicher
        proj_name = None
        if _sess.project:
            try:
                proj_name = _sess.project.Name
            except Exception:
                proj_name = None
        return {
            "tia_installed":    ver,
            "portal_connected": _sess.portal  is not None,
            "project_open":     _sess.project is not None,
            "project_name":     proj_name,
            "tia_pid":          _sess.pid,
            "auto_reconnect":   _sess.auto_reconnect,
            "remembered_project": _sess.project_path,
            "idle_disconnect_s":  _IDLE_DISCONNECT_S,
            "dialog_mode":        _DIALOG_MODE,
        }
    return sta.run(_tia_call, _run)

def get_project_info():
    def _run():
        _sess.ensure_project(); p = _sess.project
        return {"name":p.Name,"path":str(p.Path),
                "devices":[{"name":d.Name,"type":str(d.TypeIdentifier)}
                           for d in _iter_all_devices(p)]}
    return sta.run(_tia_call, _run)

def list_devices():
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        sw_type = _get_sw_container_type()
        result = []
        for device in _iter_all_devices(_sess.project):
            sw_list = []
            stack = list(device.DeviceItems)
            while stack:
                item = stack.pop()
                sw = _try_get_software(item, "", sw_type, eng)
                if sw:
                    full = type(sw).__module__ + "." + type(sw).__name__
                    hw = "Unified"  if "HmiUnified" in full else \
                         "Advanced" if "Hmi"        in full else \
                         "PLC"      if "Plc"        in full else type(sw).__name__
                    sw_list.append({"item": item.Name, "type": hw})
                try:
                    for sub in item.DeviceItems: stack.append(sub)
                except Exception: pass
            result.append({"name": device.Name, "software": sw_list})
        return {"devices": result, "count": len(result)}
    return sta.run(_tia_call, _run)

def _find_plc_item(device_name):
    """CPU DeviceItem anhand des Software-ItemNamens finden."""
    import Siemens.Engineering as eng
    sw_type = _get_sw_container_type()
    for device in _iter_all_devices(_sess.project):
        item_stack = list(device.DeviceItems)
        while item_stack:
            item = item_stack.pop()
            sw = _try_get_software(item, "", sw_type, eng)
            if sw and "Plc" in type(sw).__name__ and item.Name == device_name:
                return item
            for sub in item.DeviceItems:
                item_stack.append(sub)
    raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)


# Attribute die nicht sinnvoll schreibbar sind (interne/berechnete Werte)
_PLC_READONLY_ATTRS = {
    "Classification", "Container", "FirmwareVersion", "InstallationDate",
    "IsBuiltIn", "IsPlugged", "Items", "Name", "OrderNumber",
    "PositionNumber", "ShortDesignation", "TypeIdentifier",
    "TypeIdentifierNormalized", "TypeName", "MultilingualSupportAdvanced",
    "CommentML",
}

# Gruppierung für Excel-Export
_PLC_ATTR_GROUPS = {
    "Allgemein":     ["Name", "OrderNumber", "ShortDesignation", "FirmwareVersion",
                      "TypeName", "Author", "Comment", "LocationIdentifier",
                      "PlantDesignation", "AdditionalInformation", "InstallationDate"],
    "Zyklus":        ["CycleMinimumCycleTime", "CycleMaximumCycleTime",
                      "CycleCommunicationLoad", "CycleEnableMinimumCycleTime",
                      "IsochronousMode", "SendClock"],
    "Startup":       ["StartupActionAfterPowerOn", "StartupComparisonPresetToActualModule",
                      "StartupConfigurationTimeout"],
    "Zeitzone":      ["TimeOfDayLocalTimeZone", "TimeOfDayActivateDaylightSavingTime",
                      "TimeOfDayDaylightSavingTimeOffset", "TimeOfDayDaylightSavingTimeStartMonth",
                      "TimeOfDayDaylightSavingTimeStartWeek", "TimeOfDayDaylightSavingTimeStartWeekday",
                      "TimeOfDayDaylightSavingTimeStartHour", "TimeOfDayStandardTimeStartMonth",
                      "TimeOfDayStandardTimeStartWeek", "TimeOfDayStandardTimeStartWeekday",
                      "TimeOfDayStandardTimeStartHour", "TimeSynchronizationNtpV2"],
    "Sicherheit":    ["PlcAccessControlConfiguration", "ConfigurationControl",
                      "NetworkFaultsAsMaintenance", "SuppressDeactivatingSystemDiagnosticsAlarms",
                      "UseFixedSystemDiagnosticsAlarmIds", "ProtectionIntervalForSummarizeOfSecurityEvents",
                      "ProtectionSummarizeSecurityEventsOnHighLoad",
                      "ProtectionUnitForSummarizeOfSecurityEvents"],
    "Netzwerk":      ["HostAndDomainnameActive", "IPv4ForwardingActive", "CommunicationMode",
                      "PnDnsConfiguration", "PnDnsConfigNameResolve",
                      "SNMPActive", "SNMPReadOnlyActive", "SNMPReadOnlyCommunityName",
                      "SNMPReadWriteCommunityName", "SNMPSynchronizeActive", "SNMPConfigurationSource"],
    "OPC UA":        ["OpcUaPurchasedLicense"],
    "Web & Syslog":  ["WebserverActivate", "SysLogAutoAcceptClient",
                      "SysLogClientCertificateId", "SysLogTrustedCertificateIds"],
    "Speicher":      ["ClockMemoryByte", "SystemMemoryByte", "SystemPowerSupplyExternal"],
    "Diagnose":      ["CentralAlarmManagement", "DetectLoadVoltageFailure",
                      "ProDiagUsedLicenses"],
}


def get_plc_config(device_name):
    def _run():
        _sess.ensure_project()
        item = _find_plc_item(device_name)
        config = {}
        for ai in item.GetAttributeInfos():
            n = str(ai.Name)
            v = item.GetAttribute(n)
            config[n] = str(v) if v is not None else None
        return {"status": "ok", "device": device_name, "config": config}
    return sta.run(_tia_call, _run)


def set_plc_config(device_name, settings: dict):
    def _run():
        _sess.ensure_project()
        item = _find_plc_item(device_name)
        applied, skipped = [], []
        for key, val in settings.items():
            if key in _PLC_READONLY_ATTRS:
                skipped.append(key)
                continue
            item.SetAttribute(key, val)
            applied.append(key)
        return {"status": "ok", "device": device_name, "applied": applied, "skipped_readonly": skipped}
    return sta.run(_tia_call, _run)


def export_plc_config(device_name, output_path=None):
    def _run():
        _sess.ensure_project()
        item = _find_plc_item(device_name)
        config = {}
        for ai in item.GetAttributeInfos():
            n = str(ai.Name)
            v = item.GetAttribute(n)
            config[n] = str(v) if v is not None else None
        return config

    config = sta.run(_tia_call, _run)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise TiaError("MISSING_DEPENDENCY", "openpyxl nicht installiert.", False)

    out = Path(output_path) if output_path else Path(_DEFAULT_EXPORT) / f"plc_config_{device_name}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "PLC Konfiguration"
    thin   = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col, (h, w) in enumerate(zip(["Einstellung", "Wert", "Gruppe"], [40, 40, 22]), 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        c.fill      = PatternFill("solid", start_color="1F4E79")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = border
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22

    grp_fill = PatternFill("solid", start_color="D6E4F0")
    val_fill = PatternFill("solid", start_color="F5FBFF")
    alt_fill = PatternFill("solid", start_color="EAF4FB")
    ro_font  = Font(name="Arial", size=10, color="808080")

    r = 2
    written = set()
    for group, keys in _PLC_ATTR_GROUPS.items():
        c = ws.cell(row=r, column=1, value=group)
        c.font = Font(name="Arial", bold=True, size=10)
        c.fill = grp_fill
        c.border = border
        for col in [2, 3]:
            ws.cell(row=r, column=col).fill   = grp_fill
            ws.cell(row=r, column=col).border = border
        r += 1
        for key in keys:
            if key not in config:
                continue
            fill = val_fill if r % 2 == 0 else alt_fill
            ro   = key in _PLC_READONLY_ATTRS
            ws.cell(row=r, column=1, value=f"  {key}").fill   = fill
            ws.cell(row=r, column=1).font   = ro_font if ro else Font(name="Arial", size=10)
            ws.cell(row=r, column=1).border = border
            ws.cell(row=r, column=2, value=config[key] or "").fill   = fill
            ws.cell(row=r, column=2).font   = Font(name="Arial", size=10)
            ws.cell(row=r, column=2).border = border
            ws.cell(row=r, column=3, value=group).fill   = fill
            ws.cell(row=r, column=3).font   = Font(name="Arial", size=10, color="808080")
            ws.cell(row=r, column=3).border = border
            written.add(key)
            r += 1

    # Restliche Attribute (nicht in Gruppen) am Ende
    remaining = {k: v for k, v in config.items() if k not in written}
    if remaining:
        c = ws.cell(row=r, column=1, value="Sonstige")
        c.font = Font(name="Arial", bold=True, size=10)
        c.fill = grp_fill
        c.border = border
        for col in [2, 3]:
            ws.cell(row=r, column=col).fill   = grp_fill
            ws.cell(row=r, column=col).border = border
        r += 1
        for key, val in sorted(remaining.items()):
            fill = val_fill if r % 2 == 0 else alt_fill
            ro   = key in _PLC_READONLY_ATTRS
            ws.cell(row=r, column=1, value=f"  {key}").fill   = fill
            ws.cell(row=r, column=1).font   = ro_font if ro else Font(name="Arial", size=10)
            ws.cell(row=r, column=1).border = border
            ws.cell(row=r, column=2, value=val or "").fill   = fill
            ws.cell(row=r, column=2).font   = Font(name="Arial", size=10)
            ws.cell(row=r, column=2).border = border
            ws.cell(row=r, column=3, value="Sonstige").fill   = fill
            ws.cell(row=r, column=3).font   = Font(name="Arial", size=10, color="808080")
            ws.cell(row=r, column=3).border = border
            r += 1

    ws.freeze_panes = "A2"
    wb.save(str(out))
    return {"status": "ok", "file": str(out), "device": device_name, "attributes": len(config)}


def export_hw_config(output_path=None):
    def _run():
        _sess.ensure_project()
        rows = []
        for device in _iter_all_devices(_sess.project):
            station = device.Name
            item_stack = [(item, 0) for item in device.DeviceItems]
            while item_stack:
                entry = item_stack.pop()
                di, depth = entry[0], entry[1]
                type_id = str(di.TypeIdentifier) if di.TypeIdentifier else ""
                ip = ""
                try:
                    v = di.GetAttribute("Address")
                    if v: ip = str(v)
                except Exception:
                    pass
                rows.append({
                    "Station":       station,
                    "Depth":         depth,
                    "Name":          str(di.Name),
                    "TypeIdentifier": type_id,
                    "Position":      str(getattr(di, "PositionNumber", "")),
                    "IP":            ip,
                })
                for sub in di.DeviceItems:
                    item_stack.append((sub, depth + 1))
        return rows

    rows = sta.run(_tia_call, _run)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise TiaError("MISSING_DEPENDENCY", "openpyxl nicht installiert. pip install openpyxl", False)

    out = Path(output_path) if output_path else Path(_DEFAULT_EXPORT) / "hardware_config.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Hardware"

    thin   = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    headers    = ["Station", "Komponente", "Bestellnummer", "Steckplatz", "IP-Adresse"]
    col_widths = [30, 42, 38, 12, 18]

    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        c.fill      = PatternFill("solid", start_color="1F4E79")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = border
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22

    prev_station = None
    for r, row in enumerate(rows, 2):
        s      = row["Station"]
        indent = "   " * row["Depth"]
        tid    = row["TypeIdentifier"].replace("OrderNumber:", "") if row["TypeIdentifier"] else ""
        bold   = row["Depth"] == 0
        bg     = "D6E4F0" if s != prev_station else ("EAF4FB" if row["Depth"] == 0 else "F5FBFF")
        fill   = PatternFill("solid", start_color=bg)
        vals   = [s if s != prev_station else "", indent + row["Name"], tid, row["Position"], row["IP"]]
        for col, val in enumerate(vals, 1):
            c           = ws.cell(row=r, column=col, value=val)
            c.font      = Font(name="Arial", size=10, bold=bold)
            c.fill      = fill
            c.border    = border
            c.alignment = Alignment(vertical="center")
        prev_station = s

    ws.freeze_panes  = "A2"
    ws.auto_filter.ref = f"A1:E{len(rows) + 1}"
    wb.save(str(out))
    return {"status": "ok", "file": str(out), "rows": len(rows)}


# ═══════════════════════════════════════════════════════════════════════════════
# HMI RUNTIME SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

def _rs_to_dict(obj, depth=0):
    """RuntimeSettings-Objekt rekursiv in dict umwandeln (max. 3 Ebenen)."""
    if obj is None or depth > 3:
        return None
    result = {}
    for ai in obj.GetAttributeInfos():
        name = str(ai.Name)
        val  = obj.GetAttribute(name)
        if val is None:
            result[name] = None
        elif hasattr(val, "GetAttributeInfos"):
            result[name] = _rs_to_dict(val, depth + 1)
        else:
            s = str(val)
            if s in ("True", "False"):
                result[name] = s == "True"
            else:
                result[name] = s
    return result


def _get_hmi_rs(device_name):
    """Unified HmiSoftware + RuntimeSettings-Objekt zurückgeben."""
    import Siemens.Engineering as eng
    sw_type = _get_sw_container_type()
    for device in _iter_all_devices(_sess.project):
        for item in device.DeviceItems:
            sw = _try_get_software(item, "", sw_type, eng)
            if sw and item.Name == device_name:
                rs = sw.GetAttribute("RuntimeSettings")
                if rs is None:
                    raise TiaError("NO_RUNTIME_SETTINGS",
                                   f"'{device_name}' hat kein RuntimeSettings-Attribut (nur Unified unterstützt).", False)
                return sw, rs
    raise TiaError("HMI_NOT_FOUND", f"HMI '{device_name}' nicht gefunden.", True)


def _get_hmi_item(device_name):
    """(DeviceItem, sw, hmi_type) für Advanced und Unified zurückgeben."""
    import Siemens.Engineering as eng
    sw_type = _get_sw_container_type()
    all_names = []
    for device in _iter_all_devices(_sess.project):
        item_stack = list(device.DeviceItems)
        while item_stack:
            item = item_stack.pop()
            sw = _try_get_software(item, "", sw_type, eng)
            if sw:
                all_names.append(item.Name)
                if item.Name == device_name:
                    full = type(sw).__module__ + "." + type(sw).__name__
                    if "HmiUnified" in full:
                        return item, sw, "Unified"
                    if "Hmi" in full:
                        return item, sw, "Advanced"
            for sub in item.DeviceItems:
                item_stack.append(sub)
    raise TiaError("HMI_NOT_FOUND", f"HMI '{device_name}' nicht gefunden.", True,
                   {"available": all_names})


# Attribute die auf HMI-DeviceItems nicht sinnvoll schreibbar sind
_HMI_READONLY_ATTRS = {
    "Classification", "Container", "FirmwareVersion", "InstallationDate",
    "IsBuiltIn", "IsPlugged", "Items", "Name", "OrderNumber",
    "PositionNumber", "ShortDesignation", "TypeIdentifier",
    "TypeIdentifierNormalized", "TypeName",
}

_HMI_ATTR_GROUPS = {
    "Allgemein":      ["Name", "OrderNumber", "ShortDesignation", "FirmwareVersion",
                       "TypeName", "Author", "Comment", "LocationIdentifier",
                       "PlantDesignation", "AdditionalInformation", "InstallationDate"],
    "Netzwerk":       ["InterfaceIpAddress", "InterfaceSubnetMask", "InterfaceDefaultGateway",
                       "InterfaceMacAddress", "InterfaceDhcp",
                       "PnDeviceName", "PnDnsConfiguration"],
    "Display":        ["DisplayBrightness", "DisplayContrast", "DisplayOrientation",
                       "DisplayResolutionX", "DisplayResolutionY", "DisplayScreenSaver",
                       "DisplayScreenSaverTime", "TouchCalibration"],
    "Runtime":        ["StartupScreenName", "LanguageDefaultName", "PasswordTimeout",
                       "PasswordLevel", "ProjectName", "ProjectPath",
                       "KeypadEnable", "MouseEnable", "TransferEnable"],
    "Kommunikation":  ["MpiAddress", "MpiSubnet", "ProfibusDpAddress",
                       "ProfibusDpSubnet", "S7Protocol", "SlotNumber", "RackNumber"],
    "Sicherheit":     ["SecurityLevel", "UsbAccessEnabled", "SystemKeyEnable"],
}


def get_hmi_config(device_name):
    def _run():
        _sess.ensure_project()
        item, sw, hmi_type = _get_hmi_item(device_name)
        config = {}
        for ai in item.GetAttributeInfos():
            n = str(ai.Name)
            v = item.GetAttribute(n)
            config[n] = str(v) if v is not None else None
        result = {"status": "ok", "device": device_name, "type": hmi_type, "config": config}
        if hmi_type == "Unified":
            rs = sw.GetAttribute("RuntimeSettings")
            if rs is not None:
                result["runtime_settings"] = _rs_to_dict(rs)
        return result
    return sta.run(_tia_call, _run)


def set_hmi_config(device_name, settings: dict):
    def _run():
        _sess.ensure_project()
        item, sw, hmi_type = _get_hmi_item(device_name)
        applied_device, applied_rs, skipped = [], [], []

        # Welche Keys gibt es auf DeviceItem und (Unified) auf RuntimeSettings?
        device_keys = {str(ai.Name) for ai in item.GetAttributeInfos()}
        rs = sw.GetAttribute("RuntimeSettings") if hmi_type == "Unified" else None
        rs_keys = {str(ai.Name) for ai in rs.GetAttributeInfos()} if rs else set()

        for key, val in settings.items():
            if key in _HMI_READONLY_ATTRS:
                skipped.append(key)
                continue
            if key in device_keys:
                item.SetAttribute(key, val)
                applied_device.append(key)
            elif rs and key in rs_keys:
                existing = rs.GetAttribute(key)
                if existing is not None and hasattr(existing, "GetAttributeInfos"):
                    skipped.append(key)
                else:
                    rs.SetAttribute(key, val)
                    applied_rs.append(key)
            else:
                skipped.append(key)
        return {
            "status": "ok", "device": device_name, "type": hmi_type,
            "applied_device": applied_device,
            **({"applied_runtime_settings": applied_rs} if hmi_type == "Unified" else {}),
            "skipped": skipped,
        }
    return sta.run(_tia_call, _run)


def export_hmi_config(device_name, output_path=None):
    def _run():
        _sess.ensure_project()
        item, sw, hmi_type = _get_hmi_item(device_name)
        config = {}
        for ai in item.GetAttributeInfos():
            n = str(ai.Name)
            v = item.GetAttribute(n)
            config[n] = str(v) if v is not None else None
        rs_data = None
        if hmi_type == "Unified":
            rs = sw.GetAttribute("RuntimeSettings")
            if rs is not None:
                rs_data = _rs_to_dict(rs)
        return hmi_type, config, rs_data

    hmi_type, config, rs_data = sta.run(_tia_call, _run)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise TiaError("MISSING_DEPENDENCY", "openpyxl nicht installiert.", False)

    out = Path(output_path) if output_path else \
        Path(_DEFAULT_EXPORT) / f"hmi_config_{device_name}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = f"HMI Config ({hmi_type})"
    thin   = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    hdr_color = "1F4E79" if hmi_type == "Advanced" else "375623"
    for col, (h, w) in enumerate(zip(["Einstellung", "Wert", "Gruppe"], [40, 40, 22]), 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        c.fill      = PatternFill("solid", start_color=hdr_color)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = border
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22

    grp_fill = PatternFill("solid", start_color="D6E4F0")
    val_fill = PatternFill("solid", start_color="F5FBFF")
    alt_fill = PatternFill("solid", start_color="EAF4FB")
    ro_font  = Font(name="Arial", size=10, color="808080")

    def _write_group(ws, r, group, items_iter, ro_set):
        c = ws.cell(row=r, column=1, value=group)
        c.font = Font(name="Arial", bold=True, size=10)
        c.fill = grp_fill; c.border = border
        ws.cell(row=r, column=2).fill = grp_fill; ws.cell(row=r, column=2).border = border
        ws.cell(row=r, column=3).fill = grp_fill; ws.cell(row=r, column=3).border = border
        r += 1
        for key, val in items_iter:
            fill = val_fill if r % 2 == 0 else alt_fill
            ro   = key in ro_set
            ws.cell(row=r, column=1, value=f"  {key}").fill   = fill
            ws.cell(row=r, column=1).font   = ro_font if ro else Font(name="Arial", size=10)
            ws.cell(row=r, column=1).border = border
            ws.cell(row=r, column=2, value=str(val) if val is not None else "").fill   = fill
            ws.cell(row=r, column=2).font   = Font(name="Arial", size=10)
            ws.cell(row=r, column=2).border = border
            ws.cell(row=r, column=3, value=group).fill   = fill
            ws.cell(row=r, column=3).font   = Font(name="Arial", size=10, color="808080")
            ws.cell(row=r, column=3).border = border
            r += 1
        return r

    r = 2
    written = set()
    for group, keys in _HMI_ATTR_GROUPS.items():
        rows = [(k, config[k]) for k in keys if k in config]
        if not rows:
            continue
        r = _write_group(ws, r, group, rows, _HMI_READONLY_ATTRS)
        written.update(k for k, _ in rows)

    remaining = {k: v for k, v in config.items() if k not in written}
    if remaining:
        r = _write_group(ws, r, "Sonstige", sorted(remaining.items()), _HMI_READONLY_ATTRS)

    # Unified: RuntimeSettings als eigenes Sheet
    if rs_data:
        ws2 = wb.create_sheet("RuntimeSettings")
        for col, (h, w) in enumerate(zip(["Einstellung", "Wert", "Gruppe"], [42, 36, 30]), 1):
            c = ws2.cell(row=1, column=col, value=h)
            c.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
            c.fill      = PatternFill("solid", start_color="375623")
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border    = border
            ws2.column_dimensions[get_column_letter(col)].width = w
        ws2.row_dimensions[1].height = 22
        r2 = 2
        for key, val in rs_data.items():
            if isinstance(val, dict):
                c = ws2.cell(row=r2, column=1, value=key)
                c.font = Font(name="Arial", bold=True, size=10)
                c.fill = grp_fill; c.border = border
                ws2.cell(row=r2, column=2).fill = grp_fill; ws2.cell(row=r2, column=2).border = border
                ws2.cell(row=r2, column=3).fill = grp_fill; ws2.cell(row=r2, column=3).border = border
                r2 += 1
                for sk, sv in val.items():
                    fill = val_fill if r2 % 2 == 0 else alt_fill
                    ws2.cell(row=r2, column=1, value=f"  {sk}").fill   = fill
                    ws2.cell(row=r2, column=1).font   = Font(name="Arial", size=10)
                    ws2.cell(row=r2, column=1).border = border
                    ws2.cell(row=r2, column=2, value=str(sv) if sv is not None else "").fill   = fill
                    ws2.cell(row=r2, column=2).font   = Font(name="Arial", size=10)
                    ws2.cell(row=r2, column=2).border = border
                    ws2.cell(row=r2, column=3, value=key).fill   = fill
                    ws2.cell(row=r2, column=3).font   = Font(name="Arial", size=10, color="808080")
                    ws2.cell(row=r2, column=3).border = border
                    r2 += 1
            else:
                fill = val_fill if r2 % 2 == 0 else alt_fill
                ws2.cell(row=r2, column=1, value=key).fill   = fill
                ws2.cell(row=r2, column=1).font   = Font(name="Arial", size=10, bold=True)
                ws2.cell(row=r2, column=1).border = border
                ws2.cell(row=r2, column=2, value=str(val) if val is not None else "").fill   = fill
                ws2.cell(row=r2, column=2).font   = Font(name="Arial", size=10)
                ws2.cell(row=r2, column=2).border = border
                ws2.cell(row=r2, column=3).fill   = fill
                ws2.cell(row=r2, column=3).border = border
                r2 += 1
        ws2.freeze_panes = "A2"

    ws.freeze_panes = "A2"
    wb.save(str(out))
    total = len(config) + (sum(len(v) if isinstance(v, dict) else 1 for v in rs_data.values()) if rs_data else 0)
    return {"status": "ok", "file": str(out), "device": device_name,
            "type": hmi_type, "attributes": len(config),
            **({"runtime_settings": sum(len(v) if isinstance(v, dict) else 1 for v in rs_data.values())} if rs_data else {})}


def get_hmi_runtime_settings(device_name):
    def _run():
        _sess.ensure_project()
        _, rs = _get_hmi_rs(device_name)
        return {"status": "ok", "device": device_name, "settings": _rs_to_dict(rs)}
    return sta.run(_tia_call, _run)


def set_hmi_runtime_settings(device_name, settings: dict):
    """Setzt einfache (nicht-verschachtelte) RuntimeSettings-Werte."""
    def _run():
        _sess.ensure_project()
        _, rs = _get_hmi_rs(device_name)
        applied, skipped = [], []
        for key, val in settings.items():
            v = rs.GetAttribute(key)
            if v is not None and hasattr(v, "GetAttributeInfos"):
                skipped.append(key)
                continue
            rs.SetAttribute(key, val)
            applied.append(key)
        return {"status": "ok", "device": device_name, "applied": applied, "skipped_complex": skipped}
    return sta.run(_tia_call, _run)


def export_hmi_runtime_settings(device_name, output_path=None):
    def _run():
        _sess.ensure_project()
        _, rs = _get_hmi_rs(device_name)
        return _rs_to_dict(rs)

    settings = sta.run(_tia_call, _run)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise TiaError("MISSING_DEPENDENCY", "openpyxl nicht installiert. pip install openpyxl", False)

    out = Path(output_path) if output_path else Path(_DEFAULT_EXPORT) / f"hmi_runtime_{device_name}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "RuntimeSettings"

    thin   = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    headers    = ["Einstellung", "Wert", "Gruppe"]
    col_widths = [42, 36, 30]
    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        c.fill      = PatternFill("solid", start_color="1F4E79")
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = border
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22

    grp_fill  = PatternFill("solid", start_color="D6E4F0")
    val_fill  = PatternFill("solid", start_color="F5FBFF")
    alt_fill  = PatternFill("solid", start_color="EAF4FB")

    r = 2
    for key, val in settings.items():
        if isinstance(val, dict):
            c = ws.cell(row=r, column=1, value=key)
            c.font   = Font(name="Arial", bold=True, size=10)
            c.fill   = grp_fill
            c.border = border
            ws.cell(row=r, column=2).fill   = grp_fill
            ws.cell(row=r, column=2).border = border
            ws.cell(row=r, column=3).fill   = grp_fill
            ws.cell(row=r, column=3).border = border
            r += 1
            for sub_key, sub_val in val.items():
                fill = val_fill if r % 2 == 0 else alt_fill
                ws.cell(row=r, column=1, value=f"  {sub_key}").fill   = fill
                ws.cell(row=r, column=1).font   = Font(name="Arial", size=10)
                ws.cell(row=r, column=1).border = border
                ws.cell(row=r, column=1).alignment = Alignment(vertical="center")
                ws.cell(row=r, column=2, value=str(sub_val) if sub_val is not None else "").fill   = fill
                ws.cell(row=r, column=2).font   = Font(name="Arial", size=10)
                ws.cell(row=r, column=2).border = border
                ws.cell(row=r, column=3, value=key).fill   = fill
                ws.cell(row=r, column=3).font   = Font(name="Arial", size=10, color="808080")
                ws.cell(row=r, column=3).border = border
                r += 1
        else:
            fill = val_fill if r % 2 == 0 else alt_fill
            ws.cell(row=r, column=1, value=key).fill   = fill
            ws.cell(row=r, column=1).font   = Font(name="Arial", size=10, bold=True)
            ws.cell(row=r, column=1).border = border
            ws.cell(row=r, column=1).alignment = Alignment(vertical="center")
            ws.cell(row=r, column=2, value=str(val) if val is not None else "").fill   = fill
            ws.cell(row=r, column=2).font   = Font(name="Arial", size=10)
            ws.cell(row=r, column=2).border = border
            ws.cell(row=r, column=3).fill   = fill
            ws.cell(row=r, column=3).border = border
            r += 1

    ws.freeze_panes = "A2"
    wb.save(str(out))
    return {"status": "ok", "file": str(out), "device": device_name, "settings_count": len(settings)}


# ═══════════════════════════════════════════════════════════════════════════════
# HMI
# ═══════════════════════════════════════════════════════════════════════════════

def _get_hmi(device_name):
    """
    Sucht HMI-Software nach device.Name ODER item.Name — beide Schreibweisen
    werden akzeptiert (z.B. 'HMI_Advanced' und 'HMI_RT_1' sind gleichwertig).
    """
    import Siemens.Engineering as eng
    sw_type = _get_sw_container_type()
    all_device_names = []
    for device in _iter_all_devices(_sess.project):
        all_device_names.append(device.Name)
        for item in device.DeviceItems:
            sw = _try_get_software(item, "", sw_type, eng)
            if sw:
                # Match auf device.Name ODER item.Name
                if device.Name != device_name and item.Name != device_name:
                    continue
                # BUG-13 Fix: FullName prüfen, nicht nur __name__
                # IronPython gibt type.__name__ = "HmiSoftware" für BEIDE Typen zurück
                # aber type.__module__ unterscheidet: "HmiUnified" vs "Hmi"
                full = type(sw).__module__ + "." + type(sw).__name__
                if "HmiUnified" in full: return sw, "Unified"
                if "Hmi"        in full: return sw, "Advanced"
    raise TiaError("HMI_NOT_FOUND", f"HMI '{device_name}' nicht gefunden.", True,
                   {"available": all_device_names})

def _hmi_tag_tables(sw):
    """
    HMI Tag-Tabellen-Collection zurückgeben.
    Unified + Advanced neu:  sw.TagTables direkt
    Advanced HmiTarget:      sw.TagFolder.TagTables
    V19/V20 Unified alt:     sw.TagTableGroup.TagTables
    """
    if hasattr(sw, "TagTables"):
        return sw.TagTables
    if hasattr(sw, "TagFolder"):
        return sw.TagFolder.TagTables
    if hasattr(sw, "TagTableGroup"):
        return sw.TagTableGroup.TagTables
    return []

def _hmi_all_tag_tables(sw):
    """Alle HMI-Variablentabellen inkl. Tabellen in Ordnern (rekursiv).
    _hmi_tag_tables liefert nur die oberste Ebene - in Projekten mit Tabellenordnern
    fehlten dadurch Variablen (list_hmi_tags, list_hmi_tag_usage, Export)."""
    result = list(_hmi_tag_tables(sw))
    def walk(groups):
        for g in groups or []:
            for t in getattr(g, "TagTables", None) or []:
                result.append(t)
            sub = getattr(g, "Groups", None)
            if sub is None:
                sub = getattr(g, "TagTableGroups", None)
            walk(sub)
    for attr in ("TagTableGroups", "TagTableGroup"):
        grp = getattr(sw, attr, None)
        if grp is not None:
            walk(grp if hasattr(grp, "__iter__") else [grp])
            break
    seen, uniq = set(), []
    for t in result:                       # Tabellen der obersten Ebene ggf. doppelt -> entfernen
        key = id(t) if not hasattr(t, "Name") else (str(t.Name), str(getattr(t.Parent, "Name", "")))
        if key not in seen:
            seen.add(key); uniq.append(t)
    return uniq

def _hmi_tag_tables_import(sw, fi, eng):
    """Import-Methode je nach API-Version."""
    if hasattr(sw, "TagTables"):
        sw.TagTables.Import(fi, eng.ImportOptions.Override)
    elif hasattr(sw, "TagFolder"):
        sw.TagFolder.TagTables.Import(fi, eng.ImportOptions.Override)
    elif hasattr(sw, "TagTableGroup"):
        sw.TagTableGroup.Import(fi, eng.ImportOptions.Override)
    else:
        raise TiaError("TAG_IMPORT_NOT_SUPPORTED", "Keine Import-Methode für HMI-Tags gefunden.", False)

def _hmi_screens(sw):
    """
    Alle HMI-Screens liefern — rekursiv aus Gruppen/Ordnern.
    Unified + Advanced neu:  Screens in sw.ScreenGroups (rekursiv)
    Advanced HmiTarget:      Screens in sw.ScreenFolder.Folders (rekursiv)
    Fallback:                sw.Screens direkt
    """
    screens = []

    def _collect_from_groups(collection):
        for grp in collection:
            for s in grp.Screens:
                screens.append(s)
            sub = getattr(grp, "ScreenGroups", None) or getattr(grp, "Folders", None)
            if sub:
                try: _collect_from_groups(sub)
                except Exception: pass

    def _collect_from_folder(folder):
        for s in folder.Screens:
            screens.append(s)
        for sub in folder.Folders:
            _collect_from_folder(sub)

    if hasattr(sw, "ScreenGroups"):
        _collect_from_groups(sw.ScreenGroups)
        if hasattr(sw, "Screens"):
            for s in sw.Screens:
                screens.append(s)
        return screens

    if hasattr(sw, "ScreenFolder"):
        _collect_from_folder(sw.ScreenFolder)
        return screens

    if hasattr(sw, "Screens"):
        return list(sw.Screens)
    if hasattr(sw, "ScreenCollection"):
        return list(sw.ScreenCollection)
    return []

def _hmi_screens_import(sw, fi, eng):
    """Screen-Import je nach API-Version."""
    if hasattr(sw, "Screens") and hasattr(sw.Screens, "Import"):
        sw.Screens.Import(fi, eng.ImportOptions.Override)
        return
    if hasattr(sw, "ScreenFolder"):
        sf = sw.ScreenFolder
        if hasattr(sf, "Screens") and hasattr(sf.Screens, "Import"):
            sf.Screens.Import(fi, eng.ImportOptions.Override)
            return
    if hasattr(sw, "ScreenCollection") and hasattr(sw.ScreenCollection, "Import"):
        sw.ScreenCollection.Import(fi, eng.ImportOptions.Override)
        return
    raise TiaError("SCREEN_IMPORT_NOT_SUPPORTED",
                   "Keine Import-Methode für HMI-Screens gefunden.", False)

def _hmi_screen_folders(sw):
    """
    Oberste Ordner-Collection für Screens zurückgeben.
    Unified + Advanced neu:  sw.ScreenGroups
    Advanced HmiTarget:      sw.ScreenFolder.Folders
    """
    if hasattr(sw, "ScreenGroups"):
        return sw.ScreenGroups, "ScreenGroups"
    if hasattr(sw, "ScreenFolders"):
        return sw.ScreenFolders, "ScreenFolders"
    if hasattr(sw, "ScreenFolder"):
        return sw.ScreenFolder.Folders, "Folders"
    return None, None

def _hmi_tag_folders(sw):
    """
    Oberste Ordner-Collection für Tag-Tabellen zurückgeben.
    Unified + Advanced neu:  sw.TagTableGroups
    Advanced HmiTarget:      sw.TagFolder.Folders
    Advanced älter:          sw.TagTableGroup (singular)
    """
    if hasattr(sw, "TagTableGroups"):
        return sw.TagTableGroups, "TagTableGroups"
    if hasattr(sw, "TagFolder"):
        return sw.TagFolder.Folders, "Folders"
    if hasattr(sw, "TagTableGroup"):
        return sw.TagTableGroup, "TagTableGroup"
    return None, None

def _ensure_folder(collection, name, sub_attr):
    """
    Gibt einen Ordner mit `name` aus `collection` zurück.
    Legt ihn an falls nicht vorhanden.
    sub_attr: Name der Unterordner-Collection am Ordner-Objekt (z.B. 'ScreenGroups').
    """
    for f in collection:
        if f.Name == name:
            return f
    return collection.Create(name)

def list_hmi_screens(device_name):
    def _run():
        _sess.ensure_project(); sw,ht = _get_hmi(device_name)
        screens = [{"name":s.Name,"width":getattr(s,"Width",None),
                    "height":getattr(s,"Height",None),
                    "items":s.ScreenItems.Count if hasattr(s,"ScreenItems") else None}
                   for s in _hmi_screens(sw)]
        return {"device":device_name,"hmi_type":ht,"screens":screens,"count":len(screens)}
    return sta.run(_tia_call, _run)

def list_hmi_tags(device_name, table_name=None):
    def _run():
        _sess.ensure_project(); sw,ht = _get_hmi(device_name); tags = []
        for table in _hmi_all_tag_tables(sw):
            if table_name and table.Name != table_name: continue
            for tag in table.Tags:
                tags.append({"name":tag.Name,"table":table.Name,
                    "type":str(getattr(tag,"DataTypeName","?")),
                    "high":getattr(tag,"HighLimit",None),
                    "low":getattr(tag,"LowLimit",None),
                    "archive":getattr(tag,"LoggingEnabled",None)})
        return {"device":device_name,"hmi_type":ht,"tags":tags,"count":len(tags)}
    return sta.run(_tia_call, _run)

def _alarm_to_dict(a, kind):
    """Liest alle Attribute eines Alarm-Objekts via GetAttributeInfos."""
    d = {"_alarm_type": kind}
    try:
        d["name"] = str(a.Name)
    except Exception:
        d["name"] = "?"
    if hasattr(a, "GetAttributeInfos"):
        try:
            for ai in a.GetAttributeInfos():
                n = str(ai.Name)
                try:
                    v = a.GetAttribute(n)
                    d[n] = str(v) if v is not None else None
                except Exception:
                    pass
        except Exception:
            pass
    return d

def list_hmi_alarms(device_name):
    def _run():
        _sess.ensure_project(); sw, ht = _get_hmi(device_name); alarms = []
        for attr, kind in [("DiscreteAlarms", "discrete"), ("AnalogAlarms", "analog"), ("Alarms", "unified")]:
            if hasattr(sw, attr):
                try:
                    for a in getattr(sw, attr):
                        alarms.append(_alarm_to_dict(a, kind))
                except Exception as e:
                    alarms.append({"_alarm_type": kind, "_error": str(e)})
        return {"device": device_name, "hmi_type": ht, "alarms": alarms, "count": len(alarms)}
    return sta.run(_tia_call, _run)

# ── Variablen-Verwendung (Unified) ─────────────────────────────────────────────
# Skript-Zugriffe: Tags("Name"), HMIRuntime.Tags('Name'), Tags(`Name`)
_TAG_CALL_RE = re.compile(r"""Tags\s*\(\s*(["'`])(.+?)\1""")
_STR_LIT_RE  = re.compile(r"""(["'`])([^"'`\r\n]{1,200})\1""")
_ALARM_TAG_ATTRS = ("RaisedStateTag", "AcknowledgmentStateTag", "AcknowledgmentControlTag", "TriggerTag")

# TIA-Datentyp -> Datentyp-Name der Unified-Runtime (wie in der Offline-Konfiguration des
# Bericht-Controls). Geprueft gegen eine Offline-Konfiguration: Bool, Int, DInt, UDInt, ULInt,
# Real, String, WString, Time, LTime, DateTime, Date_And_Time. Uebrige nach Namensregel.
_RUNTIME_TYPES = {
    "Int": "Int16", "DInt": "Int32", "LInt": "Int64", "SInt": "SByte",
    "UInt": "UInt16", "UDInt": "UInt32", "ULInt": "UInt64", "USInt": "Byte",
    "WString": "String", "Date_And_Time": "DateTime", "DTL": "DateTime", "LDT": "DateTime",
    "LTime": "Time", "LReal": "Double",
}

def _runtime_type(tia_type):
    return _RUNTIME_TYPES.get(tia_type, tia_type)

def _tag_root(ref):
    """'HMI_RT_1::Motor1.Temperatur.Wert' / 'Messwerte[2]' -> 'Motor1' / 'Messwerte'"""
    ref = ref.split("::", 1)[-1]
    return re.split(r"[.\[]", ref, 1)[0]

def list_hmi_tag_usage(device_name, include_scripts=True):
    """
    Wo werden die HMI-Variablen eines Unified-Geraets verwendet?
    Durchsucht Bilder (Tag-/Skript-Dynamisierungen, Ereignisse, Eigenschafts-Ereignisse),
    Bit- und Analogalarme, Archivierung (Logging-Tags) und globale Skriptmodule.
    Skripte werden per Textsuche ausgewertet: Tags("Name") und String-Literale, die einem
    Variablennamen entsprechen. Zusammengesetzte Namen ("Motor" + i) werden nicht erkannt.
    """
    def _run():
        _sess.ensure_project()
        sw, ht = _get_hmi(device_name)
        if ht != "Unified":
            raise TiaError("NOT_SUPPORTED", "list_hmi_tag_usage gibt es nur fuer WinCC Unified.", True)
        log = _log("usage")
        prefix = f"{device_name}::"
        known = {}                                   # Wurzelname -> Tabelle
        dtypes = {}                                  # Wurzelname -> Datentyp (z.B. UDT_Motor)
        for tbl in _hmi_all_tag_tables(sw):
            for t in tbl.Tags:
                known[str(t.Name)] = str(tbl.Name)
                try:
                    dtypes[str(t.Name)] = str(t.DataType)
                except Exception:
                    dtypes[str(t.Name)] = ""
        usages = {}                                  # Referenz -> [Fundstellen]
        notes = []
        stats = {"screens": 0, "screen_items": 0, "dynamizations": 0, "scripts": 0, "alarms": 0}

        def add(ref, where):
            ref = str(ref).strip()
            if not ref or ref.startswith("<"):       # "<No tag>"
                return
            if ref.startswith(prefix):
                ref = ref[len(prefix):]
            usages.setdefault(ref, [])
            if where not in usages[ref]:
                usages[ref].append(where)

        def scan_code(code, where):
            if not code:
                return
            stats["scripts"] += 1
            code = str(code)
            for m in _TAG_CALL_RE.finditer(code):
                add(m.group(2), where)
            for m in _STR_LIT_RE.finditer(code):       # z.B. TagSet(["A","B"]) oder Konstanten
                lit = m.group(2).split("::", 1)[-1]
                if _tag_root(lit) in known:
                    add(lit, where)

        def scan_handlers(obj, where):
            for attr in ("EventHandlers", "PropertyEventHandlers"):
                coll = getattr(obj, attr, None)
                if coll is None:
                    continue
                for h in coll:
                    sub = getattr(h, "PropertyName", None) or getattr(h, "EventType", None)
                    try:
                        scan_code(h.Script.ScriptCode, f"{where} / {attr[:-8]} {sub}")
                    except Exception as e:
                        log.debug(f"{where}: {e}")

        def scan_dynamizations(obj, where):
            coll = getattr(obj, "Dynamizations", None)
            if coll is None:
                return
            for d in coll:
                stats["dynamizations"] += 1
                prop = str(getattr(d, "PropertyName", "?"))
                w = f"{where} ({prop}, {str(getattr(d, 'DynamizationType', ''))})"
                for p in d.GetType().GetProperties():
                    n = str(p.Name)
                    if n in ("Parent",):
                        continue
                    try:
                        v = p.GetValue(d, None)
                    except Exception:
                        continue
                    if v is None:
                        continue
                    if n == "Tag":
                        add(v, w)
                    elif "ScriptCode" in n:
                        scan_code(v, w)
                    elif n == "Trigger":
                        try:
                            for t in v.Tags:
                                add(t, w + " Trigger")
                        except Exception:
                            pass
                    elif isinstance(v, str) and _tag_root(v) in known:
                        add(v, w)

        # Fortschritt ins Log, damit man bei grossen Projekten sieht, wo es haengt
        import time as _time
        t_start = _time.monotonic()
        def phase(text):
            log.info(f"[{device_name}] {text} ({_time.monotonic() - t_start:.0f}s)")
        phase(f"Verwendung: {len(known)} Variablen in {len(_hmi_all_tag_tables(sw))} Tabellen")

        # Bilder
        screens = _hmi_screens(sw)
        for i, scr in enumerate(screens, 1):
            stats["screens"] += 1
            sname = f"Bild {scr.Name}"
            t_scr = _time.monotonic()
            phase(f"Bild {i}/{len(screens)}: {scr.Name}")
            scan_dynamizations(scr, sname)
            scan_handlers(scr, sname)
            for it in scr.ScreenItems:
                stats["screen_items"] += 1
                where = f"{sname} / {it.Name}"
                scan_dynamizations(it, where)
                scan_handlers(it, where)
            if _time.monotonic() - t_scr > 10:
                phase(f"  Bild {scr.Name} dauerte {_time.monotonic() - t_scr:.0f}s")
        phase(f"Bilder fertig: {stats['screens']} Bilder, {stats['screen_items']} Objekte")

        # Alarme
        for coll_name, kind in (("DiscreteAlarms", "Bitalarm"), ("AnalogAlarms", "Analogalarm")):
            for a in getattr(sw, coll_name, None) or []:
                stats["alarms"] += 1
                where = f"{kind} {a.Name}"
                for attr in _ALARM_TAG_ATTRS:
                    try:
                        add(a.GetAttribute(attr), f"{where} ({attr})")
                    except Exception:
                        pass
                try:
                    for t in a.AlarmParameterTags:
                        add(t, f"{where} (Parameter)")
                except Exception:
                    pass

        phase(f"Alarme fertig: {stats['alarms']}")

        # Archivierung
        for tbl in _hmi_all_tag_tables(sw):
            for t in tbl.Tags:
                try:
                    for lt in t.LoggingTags:
                        add(t.Name, f"Archiv {lt.GetAttribute('DataLog')} ({lt.Name})")
                except Exception:
                    pass

        phase("Archivierung fertig")

        # Globale Skriptmodule: Export in Temp-Ordner, dann Textsuche
        if not include_scripts:
            notes.append("Globale Skriptmodule nicht ausgewertet (include_scripts = false).")
        if include_scripts and getattr(sw, "Scripts", None) is not None:
            phase("Globale Skriptmodule exportieren ...")
            import tempfile, shutil
            from System.IO import DirectoryInfo
            tmp = Path(tempfile.mkdtemp(prefix="tia_scripts_"))
            try:
                if any(True for _ in sw.Scripts):
                    sw.Scripts.Export(DirectoryInfo(str(tmp)))
                for f in tmp.rglob("*"):
                    if f.is_file():
                        try:
                            scan_code(f.read_text(encoding="utf-8", errors="ignore"), f"Skriptmodul {f.stem}")
                        except Exception:
                            pass
            except Exception as e:
                notes.append(f"Globale Skripte nicht ausgewertet: {e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

            phase("Globale Skriptmodule fertig")

        used_roots = {}
        for ref, where in usages.items():
            used_roots.setdefault(_tag_root(ref), []).extend(where)
        tags = {name: {"table": tbl, "datatype": dtypes.get(name, ""), "used": name in used_roots,
                       "where": sorted(set(used_roots.get(name, [])))}
                for name, tbl in sorted(known.items())}
        unknown = sorted(r for r in usages if _tag_root(r) not in known)
        if unknown:
            notes.append("Referenzen ohne passende HMI-Variable (Systemvariablen, Tippfehler "
                         "oder dynamische Namen): " + ", ".join(unknown[:20]))
        # Aufgeloeste Variablenliste (UDT-Elemente, Array-Eintraege) in Deklarationsreihenfolge,
        # mit Runtime-Datentyp - damit braucht json2vorlage keine Offline-Konfiguration mehr
        members = []
        for tbl in _hmi_all_tag_tables(sw):
            for t in tbl.Tags:
                stack = [(str(t.Name), t)]
                while stack:
                    name, obj = stack.pop(0)
                    try:
                        kids = list(obj.Members or [])
                    except Exception:
                        kids = []
                    if kids:
                        stack = [(name + (str(m.Name) if str(m.Name).startswith("[") else "." + str(m.Name)), m)
                                 for m in kids] + stack
                        continue
                    tia_type = str(getattr(obj, "DataType", "") or "")
                    members.append({"name": name, "datatype": _runtime_type(tia_type), "tia_type": tia_type,
                                    "root": str(t.Name), "table": str(tbl.Name)})
        phase(f"Variablen aufgeloest: {len(members)} Eintraege")
        system_members = []
        for t in getattr(sw, "SystemTags", None) or []:
            tia_type = str(t.DataType)
            system_members.append({"name": str(t.Name), "datatype": _runtime_type(tia_type), "tia_type": tia_type})

        return {"status": "ok", "device": device_name, "stats": stats,
                "usages": dict(sorted(usages.items())), "tags": tags,
                "unused": [n for n, v in tags.items() if not v["used"]],
                "members": members, "system_members": system_members,
                "notes": notes}
    return sta.run(_tia_call, _run, timeout=_STA_TIMEOUT_HEAVY)

def list_hmi_cycles(device_name):
    def _run():
        _sess.ensure_project(); sw, ht = _get_hmi(device_name)
        cycles = []
        # Advanced: sw.CycleFolder.Cycles  |  Unified: sw.Cycles (direkt)
        src = None
        if hasattr(sw, "CycleFolder") and hasattr(sw.CycleFolder, "Cycles"):
            src = sw.CycleFolder.Cycles
        elif hasattr(sw, "Cycles"):
            src = sw.Cycles
        if src is not None:
            import re as _re
            for c in src:
                name = str(c.Name)
                is_system = None
                if hasattr(c, "GetAttributeInfos"):
                    for ai in c.GetAttributeInfos():
                        n = str(ai.Name)
                        if n == "IsSystemObject":
                            is_system = str(c.GetAttribute(n)) == "True"
                # Periode und Einheit aus Namen parsen ("120 s" → 120, "s")
                period = unit = None
                m = _re.match(r"^([\d.]+)\s*(\w+)$", name.strip())
                if m:
                    period = m.group(1)
                    unit   = m.group(2)
                cycles.append({
                    "name":      name,
                    "period":    period,
                    "unit":      unit,
                    "system":    is_system,
                })
        note = None if src is not None else "CycleFolder/Cycles nicht verfügbar (V21-Limitation oder Unified)"
        return {"device": device_name, "hmi_type": ht, "cycles": cycles,
                "count": len(cycles), **({"note": note} if note else {})}
    return sta.run(_tia_call, _run)


def export_hmi_cycles(device_name, output_path=None):
    """Zyklen als XML exportieren — eine Datei pro Zyklus."""
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        src = None
        if hasattr(sw, "CycleFolder") and hasattr(sw.CycleFolder, "Cycles"):
            src = sw.CycleFolder.Cycles
        elif hasattr(sw, "Cycles"):
            src = sw.Cycles
        if src is None:
            raise TiaError("CYCLES_NOT_SUPPORTED",
                f"Cycles nicht verfügbar für HMI '{device_name}' ({ht}).", False)
        out_dir = Path(output_path) if output_path else _export_dir(None)
        out_dir.mkdir(parents=True, exist_ok=True)
        exported = []
        errors = []
        seen = set()
        for i in range(src.Count):
            c = src[i]
            name = str(c.Name)
            safe_name = name.replace(" ", "_").replace("/", "_")
            if safe_name in seen:
                continue
            seen.add(safe_name)
            xml_file = out_dir / f"hmi_cycle_{device_name}_{safe_name}.xml"
            if xml_file.exists():
                xml_file.unlink()
            try:
                c.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                exported.append({"name": name, "file": str(xml_file)})
            except Exception as ex:
                errors.append({"name": name, "error": str(ex)})
        if not exported and errors:
            raise TiaError("CYCLE_EXPORT_FAILED", f"Kein Zyklus exportierbar: {errors}", False)
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "exported": exported, "errors": errors, "count": len(exported)}
    return sta.run(_tia_call, _run)

def import_hmi_cycles(device_name, file_path):
    """Zyklen aus XML importieren (Override). Gegenstück zu export_hmi_cycles."""
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        fi = FileInfo(file_path)
        if not fi.Exists:
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        src = None
        if hasattr(sw, "CycleFolder") and hasattr(sw.CycleFolder, "Cycles"):
            src = sw.CycleFolder.Cycles
        elif hasattr(sw, "Cycles"):
            src = sw.Cycles
        if src is None:
            raise TiaError("CYCLES_NOT_SUPPORTED",
                f"Cycles nicht verfügbar für HMI '{device_name}' ({ht}).", False)
        src.Import(fi, eng.ImportOptions.Override)
        return {"status": "ok", "device": device_name, "imported_from": file_path}
    return sta.run(_tia_call, _run)

def list_hmi_graphic_lists(device_name):
    """Grafiklisten eines HMI auflisten (Advanced: GraphicLists, Unified: HmiGraphicLists)."""
    def _run():
        _sess.ensure_project()
        _, ht = _get_hmi(device_name)
        gls = []
        seen = set()
        for _item_name, sw, sw_ht in _get_hmi_all_sw(device_name):
            coll_name = "HmiGraphicLists" if sw_ht == "Unified" else "GraphicLists"
            if not hasattr(sw, coll_name):
                continue
            coll = getattr(sw, coll_name)
            for i in range(coll.Count):
                gl = coll[i]
                if gl.Name in seen:
                    continue
                seen.add(gl.Name)
                gls.append({"name": gl.Name})
        return {"device": device_name, "hmi_type": ht, "graphic_lists": gls, "count": len(gls)}
    return sta.run(_tia_call, _run)

def export_hmi_graphic_lists(device_name, output_path=None):
    """
    Grafiklisten exportieren.
    Advanced: je eine XML-Datei pro Liste (gl.Export).
    Unified: Collection-Export in Ordner (HmiGraphicLists.Export(DirectoryInfo, name)).
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        _, ht = _get_hmi(device_name)
        out_dir = Path(output_path) if output_path else _export_dir(None)
        out_dir.mkdir(parents=True, exist_ok=True)
        exported = []
        errors = []
        seen = set()
        for _item_name, sw, sw_ht in _get_hmi_all_sw(device_name):
            if sw_ht == "Unified":
                coll = getattr(sw, "HmiGraphicLists", None)
                if coll is None or coll.Count == 0:
                    continue
                try:
                    files = coll.Export(DirectoryInfo(str(out_dir)), "")
                    for f in files:
                        exported.append({"file": str(f.FullName)})
                except Exception as ex:
                    errors.append({"type": "Unified", "error": str(ex)})
            else:
                coll = getattr(sw, "GraphicLists", None)
                if coll is None:
                    continue
                for i in range(coll.Count):
                    gl = coll[i]
                    if gl.Name in seen:
                        continue
                    seen.add(gl.Name)
                    xml_file = out_dir / f"hmi_gl_{device_name}_{gl.Name}.xml"
                    if xml_file.exists():
                        xml_file.unlink()
                    try:
                        gl.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                        exported.append({"name": gl.Name, "file": str(xml_file)})
                    except Exception as ex:
                        errors.append({"name": gl.Name, "error": str(ex)})
        if not exported and errors:
            raise TiaError("GL_EXPORT_FAILED", f"Kein Export möglich: {errors}", False)
        if not exported and not errors:
            raise TiaError("GL_EMPTY", f"Keine Grafiklisten in '{device_name}' gefunden.", True)
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "exported": exported, "errors": errors, "count": len(exported)}
    return sta.run(_tia_call, _run)

def import_hmi_graphic_lists(device_name, file_path):
    """
    Grafiklisten importieren.
    Advanced: XML-Datei → GraphicLists.Import(FileInfo, Override).
    Unified: Ordner → HmiGraphicLists.Import(DirectoryInfo, name).
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        _, ht = _get_hmi(device_name)
        for _item_name, sw, sw_ht in _get_hmi_all_sw(device_name):
            if sw_ht == "Unified":
                coll = getattr(sw, "HmiGraphicLists", None)
                if coll is None:
                    continue
                p = Path(file_path)
                coll.Import(DirectoryInfo(str(p) if p.is_dir() else str(p.parent)), p.stem if not p.is_dir() else "")
                return {"status": "ok", "device": device_name, "imported_from": file_path}
            else:
                coll = getattr(sw, "GraphicLists", None)
                if coll is None:
                    continue
                fi = FileInfo(file_path)
                if not fi.Exists:
                    raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
                coll.Import(fi, eng.ImportOptions.Override)
                return {"status": "ok", "device": device_name, "imported_from": file_path}
        raise TiaError("GL_IMPORT_NOT_SUPPORTED",
            f"Kein Grafiklisten-Import für '{device_name}' ({ht}).", False)
    return sta.run(_tia_call, _run)

def list_hmi_scheduled_tasks(device_name):
    def _run():
        _sess.ensure_project(); sw, ht = _get_hmi(device_name)
        tasks = []
        # Advanced: sw.ScheduledTaskFolder.ScheduledTasks
        src = None
        if hasattr(sw, "ScheduledTaskFolder") and hasattr(sw.ScheduledTaskFolder, "ScheduledTasks"):
            src = sw.ScheduledTaskFolder.ScheduledTasks
        elif hasattr(sw, "ScheduledTasks"):
            src = sw.ScheduledTasks
        if src is not None:
            for t in src:
                tasks.append({
                    "name":     str(t.Name),
                    "trigger":  str(getattr(t, "Trigger",  getattr(t, "TriggerType", "?"))),
                    "interval": str(getattr(t, "Interval", getattr(t, "Period",      "?"))),
                    "function": str(getattr(t, "FunctionName", getattr(t, "Script", "?"))),
                    "enabled":  str(getattr(t, "Enabled", "?")),
                    "comment":  str(getattr(t, "Comment", "") or ""),
                })
        note = None if src is not None else "ScheduledTaskFolder nicht verfügbar (V21-Limitation oder Unified)"
        return {"device": device_name, "hmi_type": ht, "scheduled_tasks": tasks,
                "count": len(tasks), **({"note": note} if note else {})}
    return sta.run(_tia_call, _run)


def _get_hmi_all_sw(station_name):
    """Gibt alle Software-Objekte einer HMI-Station zurück: [(item_name, sw, hmi_type)]."""
    import Siemens.Engineering as eng
    sw_type = _get_sw_container_type()
    result = []
    for device in _iter_all_devices(_sess.project):
        if device.Name != station_name:
            continue
        for item in device.DeviceItems:
            sw = _try_get_software(item, "", sw_type, eng)
            if sw is None:
                continue
            full = type(sw).__module__ + "." + type(sw).__name__
            ht = "Unified" if "HmiUnified" in full else ("Advanced" if "Hmi" in full else None)
            if ht:
                result.append((item.Name, sw, ht))
    return result


def list_hmi_logs(device_name):
    def _run():
        _sess.ensure_project()
        _, ht = _get_hmi(device_name)
        logs = []
        for _item_name, sw, _ht in _get_hmi_all_sw(device_name):
            if not hasattr(sw, "DataLogs"):
                continue
            for log in sw.DataLogs:
                entry = {"name": str(log.Name)}
                # Segment: Größe, Startzeit, Periode
                try:
                    seg = log.GetAttribute("Segment")
                    entry["segment_max_size"]  = str(seg.GetAttribute("SegmentMaxSize") or "")
                    entry["segment_start"]     = str(seg.GetAttribute("SegmentStartTime") or "")
                    stp = seg.GetAttribute("SegmentTimePeriod")
                    if stp and hasattr(stp, "GetAttributeInfos"):
                        entry["segment_period"] = {str(ai.Name): str(stp.GetAttribute(str(ai.Name))) for ai in stp.GetAttributeInfos()}
                except: pass
                # Settings: Speicher, Gerät, Ordner
                try:
                    stg = log.GetAttribute("Settings")
                    entry["log_max_size"]    = str(stg.GetAttribute("LogMaxSize") or "")
                    entry["storage_device"]  = str(stg.GetAttribute("StorageDevice") or "")
                    entry["storage_folder"]  = str(stg.GetAttribute("StorageFolder") or "")
                    ltp = stg.GetAttribute("LogTimePeriod")
                    if ltp and hasattr(ltp, "GetAttributeInfos"):
                        entry["log_period"] = {str(ai.Name): str(ltp.GetAttribute(str(ai.Name))) for ai in ltp.GetAttributeInfos()}
                except: pass
                # Backup
                try:
                    bkp = log.GetAttribute("Backup")
                    entry["backup_mode"]  = str(bkp.GetAttribute("BackupMode") or "")
                    entry["backup_path"]  = str(bkp.GetAttribute("PrimaryPath") or "")
                except: pass
                logs.append(entry)
        note = None if logs else "DataLogs nicht verfügbar (V21-Limitation oder Advanced)"
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "logs": logs, "count": len(logs),
                **({"note": note} if note else {})}
    return sta.run(_tia_call, _run)


# Schreibbare Felder je Ebene (aus AccessMode-Analyse)
_LOG_DIRECT_RW   = {"Name"}
_LOG_SEGMENT_RW  = {"SegmentMaxSize", "SegmentStartTime"}
_LOG_SETTINGS_RW = {"LogMaxSize", "StorageDevice", "StorageFolder"}


def set_hmi_log(device_name, log_name, settings: dict):
    def _run():
        _sess.ensure_project()
        _, ht = _get_hmi(device_name)
        target_log = None
        for _item_name, sw, _ht in _get_hmi_all_sw(device_name):
            if not hasattr(sw, "DataLogs"):
                continue
            for log in sw.DataLogs:
                if str(log.Name) == log_name:
                    target_log = log
                    break
            if target_log:
                break
        if target_log is None:
            available = []
            for _item_name, sw, _ht in _get_hmi_all_sw(device_name):
                if hasattr(sw, "DataLogs"):
                    available += [str(l.Name) for l in sw.DataLogs]
            raise TiaError("LOG_NOT_FOUND",
                           f"DataLog '{log_name}' nicht gefunden.",
                           True, {"available": available})

        applied, skipped_readonly, skipped_unknown = [], [], []
        seg = target_log.GetAttribute("Segment")
        stg = target_log.GetAttribute("Settings")

        for key, val in settings.items():
            if key in _LOG_DIRECT_RW:
                target_log.SetAttribute(key, val)
                applied.append(key)
            elif key in _LOG_SEGMENT_RW:
                seg.SetAttribute(key, val)
                applied.append(key)
            elif key in _LOG_SETTINGS_RW:
                stg.SetAttribute(key, val)
                applied.append(key)
            elif key in {"SegmentTimePeriod", "LogTimePeriod", "Backup", "Segment", "Settings"}:
                skipped_readonly.append(key)
            else:
                skipped_unknown.append(key)

        return {
            "status": "ok", "device": device_name, "hmi_type": ht, "log": log_name,
            "applied": applied,
            **({"skipped_readonly": skipped_readonly} if skipped_readonly else {}),
            **({"skipped_unknown":  skipped_unknown}  if skipped_unknown  else {}),
        }
    return sta.run(_tia_call, _run)


def _conn_to_dict(c, item_name):
    """Connection-Objekt in serialisierbares Dict umwandeln (inkl. DriverProperties)."""
    entry = {"item": item_name}
    for ai in c.GetAttributeInfos():
        n = str(ai.Name)
        v = c.GetAttribute(n)
        entry[n] = str(v) if v is not None else None
    dp = getattr(c, "DriverProperties", None)
    if dp is not None:
        driver_props = {}
        for i in range(dp.Count):
            prop = dp[i]
            driver_props[str(prop.PropertyName)] = str(prop.Value)
        entry["DriverProperties"] = driver_props
    return entry

def list_hmi_connections(device_name):
    def _run():
        _sess.ensure_project()
        _, ht = _get_hmi(device_name)
        conns = []
        for _item_name, sw, _ht in _get_hmi_all_sw(device_name):
            if not hasattr(sw, "Connections"):
                continue
            for c in sw.Connections:
                conns.append(_conn_to_dict(c, _item_name))
        note = None
        if not conns:
            note = "Keine Verbindungen gefunden. Integrierte Verbindungen sind über die Openness API nicht zugänglich (V21-Limitation)."
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "connections": conns, "count": len(conns),
                **({"note": note} if note else {})}
    return sta.run(_tia_call, _run)

_CONN_RW = {"Name", "Comment", "CommunicationDriver", "DisabledAtStartup", "InitialAddress"}

def export_hmi_connections(device_name, output_path=None):
    """Verbindungen als JSON exportieren (inkl. DriverProperties)."""
    def _run():
        _sess.ensure_project()
        import json as _json
        _, ht = _get_hmi(device_name)
        conns = []
        for _item_name, sw, _ht in _get_hmi_all_sw(device_name):
            if not hasattr(sw, "Connections"):
                continue
            for c in sw.Connections:
                conns.append(_conn_to_dict(c, _item_name))
        out_dir = _export_dir(None if not output_path or not Path(output_path).suffix else output_path)
        json_file = (Path(output_path) if output_path and Path(output_path).suffix
                     else out_dir / f"hmi_connections_{device_name}.json")
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_file.write_text(_json.dumps(conns, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "count": len(conns), "json_path": str(json_file)}
    return sta.run(_tia_call, _run)

def import_hmi_connections(device_name, file_path):
    """
    Verbindungs-Attribute aus JSON importieren (schreibbare Felder + DriverProperties).
    Abgleich über Verbindungsname — unbekannte Verbindungen werden übersprungen.
    """
    def _run():
        _sess.ensure_project()
        import json as _json
        _, ht = _get_hmi(device_name)
        data = _json.loads(Path(file_path).read_text(encoding="utf-8"))
        applied = []
        skipped = []
        for entry in data:
            conn_name = entry.get("Name")
            if not conn_name:
                continue
            found = False
            for _item_name, sw, _ht in _get_hmi_all_sw(device_name):
                if not hasattr(sw, "Connections"):
                    continue
                c = sw.Connections.Find(conn_name)
                if c is None:
                    continue
                found = True
                changes = []
                for key, val in entry.items():
                    if key in ("item", "DriverProperties", "Node", "Partner", "Station"):
                        continue
                    if key in _CONN_RW:
                        c.SetAttribute(key, val)
                        changes.append(key)
                dp_data = entry.get("DriverProperties", {})
                dp = getattr(c, "DriverProperties", None)
                if dp and dp_data:
                    for i in range(dp.Count):
                        prop = dp[i]
                        pname = str(prop.PropertyName)
                        if pname in dp_data:
                            prop.Value = dp_data[pname]
                            changes.append(f"DP:{pname}")
                applied.append({"name": conn_name, "changes": changes})
                break
            if not found:
                skipped.append(conn_name)
        return {"status": "ok", "device": device_name,
                "applied": applied, "skipped": skipped}
    return sta.run(_tia_call, _run)


def _tl_entries(tl):
    entries = []
    if hasattr(tl, "TextListEntries"):
        for e in tl.TextListEntries:
            entries.append({"value": str(getattr(e, "Value", None)), "text": str(getattr(e, "Text", ""))})
    return entries

def list_hmi_textlists(device_name):
    def _run():
        _sess.ensure_project()
        _, ht = _get_hmi(device_name)
        tls = []
        seen = set()
        for _item_name, sw, sw_ht in _get_hmi_all_sw(device_name):
            if sw_ht == "Unified":
                # Unified: HmiTextLists (user) + HmiSystemTextLists (system)
                for coll_name, is_sys in [("HmiTextLists", False), ("HmiSystemTextLists", True)]:
                    if not hasattr(sw, coll_name):
                        continue
                    coll = getattr(sw, coll_name)
                    for i in range(coll.Count):
                        tl = coll[i]
                        key = f"{coll_name}:{tl.Name}"
                        if key in seen:
                            continue
                        seen.add(key)
                        entries = _tl_entries(tl)
                        tls.append({"name": tl.Name, "is_system": is_sys, "entries": entries, "count": len(entries)})
            else:
                # Advanced: TextLists (user + system gemischt)
                if not hasattr(sw, "TextLists"):
                    continue
                for tl in sw.TextLists:
                    key = f"TextLists:{tl.Name}"
                    if key in seen:
                        continue
                    seen.add(key)
                    entries = _tl_entries(tl)
                    tls.append({"name": tl.Name, "entries": entries, "count": len(entries)})
        return {"device": device_name, "hmi_type": ht, "textlists": tls, "count": len(tls)}
    return sta.run(_tia_call, _run)

def _unified_screen_files(project_path):
    """
    Sucht Unified-Screen-Dateien (.hmiScreen) im TIA-Projektordner rekursiv.
    Gibt Dict zurück: {screen_stem: Path}
    """
    import glob as _glob
    proj_dir = Path(project_path).parent
    screens = {}
    for f in _glob.glob(str(proj_dir / "**" / "*.hmiScreen"), recursive=True):
        p = Path(f)
        screens[p.stem] = p
    return screens


def export_hmi_screen(device_name, screen_name, output_path):
    """
    Einzelnen HMI-Screen exportieren.
    Advanced: s.Export(FileInfo) — direkter API-Export.
    Unified:  Keine Export-API in V21 — .hmiScreen-Datei aus Projektordner kopieren.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        all_screens = _hmi_screens(sw)
        screen_names = [s.Name for s in all_screens]

        if screen_name not in screen_names:
            raise TiaError("SCREEN_NOT_FOUND", f"Screen '{screen_name}' nicht gefunden.", True,
                           {"available": screen_names})

        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if ht == "Advanced":
            for s in all_screens:
                if s.Name == screen_name:
                    if p.exists(): p.unlink()
                    s.Export(FileInfo(str(p)), eng.ExportOptions.WithDefaults)
                    return {"status": "ok", "device": device_name, "hmi_type": ht,
                            "screen": screen_name, "output": str(p), "method": "api_export"}

        # Unified: Dateisystem
        proj_path = str(_sess.project.Path)
        screen_files = _unified_screen_files(proj_path)
        if screen_name not in screen_files:
            raise TiaError("SCREEN_FILE_NOT_FOUND",
                f"Screen '{screen_name}' nicht als .hmiScreen-Datei gefunden. "
                "Projekt speichern und erneut versuchen.",
                True, {"available_files": list(screen_files.keys())})
        import shutil as _shutil
        src = screen_files[screen_name]
        if p.exists(): p.unlink()
        _shutil.copy2(str(src), str(p))
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "screen": screen_name, "output": str(p),
                "method": "filesystem_copy", "source": str(src)}
    return sta.run(_tia_call, _run)

def export_hmi_tags(device_name, output_path=None):
    """Alle HMI Tag-Tabellen exportieren. output_path = Zielordner (Standard: C:\\tia-mcp\\export)."""
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        sw, ht = _get_hmi(device_name)
        out_dir = _export_dir(output_path)

        exported = []
        tables = _hmi_all_tag_tables(sw)
        for table in tables:
            safe_name = table.Name.replace(" ", "_").replace("/", "_")
            if safe_name == "Default_tag_table":
                continue  # Default-Tabelle überspringen

            # Advanced HmiTarget / ältere API: table.Export(FileInfo)
            if hasattr(table, "Export"):
                xml_file = out_dir / f"hmi_tags_{safe_name}.xml"
                if xml_file.exists(): xml_file.unlink()
                table.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                exported.append(str(xml_file))

            # Unified V21: table.Tags.Export(DirectoryInfo) — Workaround
            elif hasattr(table, "Tags") and hasattr(table.Tags, "Export"):
                tag_dir = out_dir / f"hmi_tags_{safe_name}"
                tag_dir.mkdir(parents=True, exist_ok=True)
                table.Tags.Export(DirectoryInfo(str(tag_dir)))
                exported.append(str(tag_dir))

        # Fallback: TagTableGroups — Tabellen in Untergruppen
        if not exported and hasattr(sw, "TagTableGroups"):
            for grp in sw.TagTableGroups:
                for table in grp.TagTables:
                    safe_name = table.Name.replace(" ", "_").replace("/", "_")
                    if hasattr(table, "Tags") and hasattr(table.Tags, "Export"):
                        tag_dir = out_dir / f"hmi_tags_{safe_name}"
                        tag_dir.mkdir(parents=True, exist_ok=True)
                        table.Tags.Export(DirectoryInfo(str(tag_dir)))
                        exported.append(str(tag_dir))

        if not exported:
            raise TiaError("NO_TAG_TABLES",
                f"HMI '{device_name}' hat keine exportierbaren Tag-Tabellen.", True)

        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "exported": exported, "count": len(exported)}
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# BIBLIOTHEK
# ═══════════════════════════════════════════════════════════════════════════════

def _lib_name(lib):
    """Bibliotheksname sicher auslesen — V21 hat kein .Name auf ProjectLibrary."""
    for attr in ("Name", "Caption", "RootGroup"):
        try:
            v = getattr(lib, attr, None)
            if v is not None:
                return str(v)
        except Exception:
            pass
    return "ProjectLibrary"

def _global_libraries():
    """GlobalLibraries — in V21 am Portal, in V19/V20 am Projekt."""
    for src in (_sess.portal, _sess.project):
        if src is None:
            continue
        try:
            return list(src.GlobalLibraries)
        except Exception:
            pass
    return []

def _find_lib(name):
    p = _sess.project
    pl_name = _lib_name(p.ProjectLibrary)
    if pl_name == name:
        return p.ProjectLibrary, "project"
    for gl in _global_libraries():
        if _lib_name(gl) == name:
            return gl, "global"
    raise TiaError("LIBRARY_NOT_FOUND", f"Bibliothek '{name}' nicht gefunden.", True,
                   {"available": [pl_name] + [_lib_name(gl) for gl in _global_libraries()]})

def _collect_types(folder, result, path=""):
    for t in folder.Types:
        fp = f"{path}/{t.Name}".lstrip("/"); dv = None; versions = []
        try:
            for v in t.Versions:
                try: is_def = t.DefaultVersion and str(v.VersionNumber)==str(t.DefaultVersion.VersionNumber)
                except: is_def = False
                versions.append({"version":str(v.VersionNumber),"state":str(v.State),"is_default":is_def})
                if is_def: dv = str(v.VersionNumber)
        except Exception as e: versions = [{"error":str(e)}]
        result.append({"name":t.Name,"path":fp,"versions":versions,"default_version":dv})
    for sub in folder.Folders:
        _collect_types(sub, result, f"{path}/{sub.Name}".lstrip("/"))

def list_libraries():
    def _run():
        _sess.ensure_project(); p = _sess.project
        pl = p.ProjectLibrary
        pl_name = _lib_name(pl)
        libs = [{"name": pl_name, "scope": "project",
                 "types":  pl.TypeFolder.Types.Count,
                 "copies": pl.MasterCopyFolder.MasterCopies.Count}]
        for gl in _global_libraries():
            libs.append({"name": _lib_name(gl), "scope": "global", "path": str(gl.Path),
                         "types":  gl.TypeFolder.Types.Count,
                         "copies": gl.MasterCopyFolder.MasterCopies.Count})
        return {"libraries": libs, "count": len(libs)}
    return sta.run(_tia_call, _run)

def list_library_types(library_name):
    def _run():
        _sess.ensure_project(); lib,scope = _find_lib(library_name)
        types_list = []; _collect_types(lib.TypeFolder, types_list)
        return {"library":library_name,"scope":scope,"types":types_list,"count":len(types_list)}
    return sta.run(_tia_call, _run)

def list_master_copies(library_name):
    def _run():
        _sess.ensure_project(); lib,scope = _find_lib(library_name)
        def _col(folder, path=""):
            r = [{"name":mc.Name,"path":f"{path}/{mc.Name}".lstrip("/")} for mc in folder.MasterCopies]
            for sub in folder.Folders: r.extend(_col(sub,f"{path}/{sub.Name}".lstrip("/")))
            return r
        copies = _col(lib.MasterCopyFolder)
        return {"library":library_name,"scope":scope,"master_copies":copies,"count":len(copies)}
    return sta.run(_tia_call, _run)

def get_library_type_versions(library_name, type_name):
    def _run():
        _sess.ensure_project(); lib,scope = _find_lib(library_name)
        types_list = []; _collect_types(lib.TypeFolder, types_list)
        for t in types_list:
            if t["name"] == type_name:
                return {"library":library_name,"type":type_name,
                        "versions":t["versions"],"default_version":t["default_version"]}
        raise TiaError("TYPE_NOT_FOUND",f"Typ '{type_name}' nicht gefunden.",True,
                       {"available":[t["name"] for t in types_list]})
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════════

_BLOCKED_WRITE  = ["save","delete","remove","create","import","compile",
                   "download","export","update","set","add","insert","copy","move","rename"]
_BLOCKED_ALWAYS = ["exec","eval","open","os.","sys.","subprocess","shutil","__import__","builtins",
                   # Scan aller Assemblies der AppDomain hat TIA eingefroren
                   "currentdomain","getassemblies"]
_SAFE_BUILTINS  = {
    "len":len,"str":str,"int":int,"float":float,"bool":bool,"list":list,"dict":dict,
    "tuple":tuple,"set":set,"print":print,"range":range,"enumerate":enumerate,
    "zip":zip,"map":map,"filter":filter,"sorted":sorted,"hasattr":hasattr,
    "getattr":getattr,"isinstance":isinstance,"type":type,
    "min":min,"max":max,"sum":sum,"any":any,"all":all,"round":round,"abs":abs,
    "Exception":Exception,
    "None":None,"True":True,"False":False,
}

def _iter_all_devices(project):
    """
    Liefert alle Devices aus project.Devices UND allen project.DeviceGroups (rekursiv).
    Nötig weil TIA-Projekte mit Gerätegruppen (Ordner) die Devices nicht auf Top-Level haben.
    """
    # Top-Level
    for device in project.Devices:
        yield device
    # DeviceGroups rekursiv (Stack statt Rekursion)
    try:
        group_stack = list(project.DeviceGroups)
        while group_stack:
            grp = group_stack.pop()
            for device in grp.Devices:
                yield device
            try:
                for sub in grp.Groups:
                    group_stack.append(sub)
            except Exception:
                pass
    except Exception:
        pass

def _get_sw_container_type():
    """
    SoftwareContainer-Typ laden.
    V21: Siemens.Engineering.HW.Features.SoftwareContainer (Base-Assembly)
    V19/V20: Siemens.Engineering.SW.SoftwareContainer
    """
    import clr
    candidates = [
        # V21 — exakter Pfad aus Reflektion ermittelt
        "Siemens.Engineering.HW.Features.SoftwareContainer",
        # V19/V20 Fallback
        "Siemens.Engineering.SW.SoftwareContainer",
    ]
    for full_name in candidates:
        parts = full_name.rsplit(".", 1)
        ns, cls = parts[0], parts[1]
        try:
            mod = __import__(ns, fromlist=[cls])
            t = getattr(mod, cls, None)
            if t:
                _log("session").info(f"SoftwareContainer: {full_name}")
                return t
        except Exception: pass
    # Letzter Ausweg: ueber Reflektion auf geladene Assemblies
    try:
        import System
        for asm in System.AppDomain.CurrentDomain.GetAssemblies():
            t = asm.GetType("Siemens.Engineering.HW.Features.SoftwareContainer")
            if t:
                return t
    except Exception: pass
    return None

_SW_CONTAINER_TYPE = None

def _find_sw(project, name, hint, eng):
    """
    Software-Objekt suchen — iterativ, alle Device- und DeviceItem-Ebenen.
    name: DeviceItem-Name (z.B. 'PLC_1') oder leer fuer erstes passendes.
    hint: 'PlcSoftware', 'Hmi', 'Unified' oder leer.
    """
    global _SW_CONTAINER_TYPE
    if _SW_CONTAINER_TYPE is None:
        _SW_CONTAINER_TYPE = _get_sw_container_type()

    sw_type = _SW_CONTAINER_TYPE

    for device in _iter_all_devices(project):
        stack = list(device.DeviceItems)
        while stack:
            item = stack.pop()
            name_match = (not name) or (item.Name == name) or (device.Name == name)
            if name_match:
                # Alle bekannten Wege versuchen
                sw = _try_get_software(item, hint, sw_type, eng)
                if sw: return sw
            try:
                for sub in item.DeviceItems: stack.append(sub)
            except Exception: pass
    return None

def _try_get_software(item, hint, sw_type, eng):
    """GetService mit allen bekannten SoftwareContainer-Typen versuchen."""
    type_candidates = []
    if sw_type: type_candidates.append(sw_type)
    # Fallbacks
    for tc in [
        lambda: eng.SW.SoftwareContainer,
        lambda: eng.HW.SoftwareContainer,
    ]:
        try: type_candidates.append(tc())
        except Exception: pass

    for t in type_candidates:
        try:
            swc = item.GetService[t]()
            if swc:
                sw = swc.Software
                tn = type(sw).__name__
                if not hint or hint.lower() in tn.lower():
                    return sw
        except Exception: pass
    return None

def _to_json(obj):
    if obj is None: return None
    if isinstance(obj,(bool,int,float,str)): return obj
    if isinstance(obj,(list,tuple)): return [_to_json(i) for i in obj]
    if isinstance(obj,dict): return {str(k):_to_json(v) for k,v in obj.items()}
    try: return str(obj)
    except: return f"<{type(obj).__name__}>"


def _mltext(obj, lang="de-DE"):
    """MultilingualText-Objekt sicher als String auslesen (BUG-15)."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        items = obj.Items
        for item in items:
            if str(getattr(item, "Language", "")).startswith(lang[:2]):
                return str(item.Text) if item.Text else ""
        for item in items:
            t = str(item.Text) if item.Text else ""
            if t:
                return t
    except Exception:
        pass
    return ""

def execute_openness(code, mode="read"):
    cl = code.lower()
    for kw in _BLOCKED_ALWAYS:
        if kw in cl:
            raise TiaError("CODE_BLOCKED",f"'{kw}' nicht erlaubt.",False,{"kw":kw})
    if mode == "read":
        for kw in _BLOCKED_WRITE:
            if f".{kw}(" in cl:
                raise TiaError("WRITE_BLOCKED",
                    f"'.{kw}()' im read-Modus gesperrt. mode='write' verwenden.",True,{"call":f".{kw}()"})
    _log("executor").info(f"execute mode={mode} {len(code)}ch")

    def _run():
        # Projekt mit uebernehmen, falls nach Leerlauf-Trennung automatisch neu verbunden wird
        try:
            _sess.ensure_project()
        except TiaError as e:
            if e.code != "NO_PROJECT":
                raise
        import Siemens.Engineering as eng
        import Siemens.Engineering.SW as eng_sw
        from System.IO import DirectoryInfo, FileInfo
        hmi_ns = unified_ns = None
        try: import Siemens.Engineering.Hmi as hmi_ns
        except Exception: pass
        try: import Siemens.Engineering.HmiUnified as unified_ns
        except Exception: pass
        # SoftwareContainer-Typ fuer direkten Zugriff im Code
        sw_container_type = _get_sw_container_type()

        ctx = {
            "portal":   _sess.portal,
            "project":  _sess.project,
            "eng":      eng,
            "sw":       eng_sw,
            "hmi":      hmi_ns,
            "unified":  unified_ns,
            "result":   None,
            # SoftwareContainer direkt nutzbar:
            # swc = item.GetService[SoftwareContainer]()
            "SoftwareContainer": sw_container_type,
            "safe_str":      lambda o: str(o) if o is not None else None,
            "collect":       lambda c: list(c),
            "find_software": lambda n, h="": _find_sw(_sess.project, n, h, eng),
            # Alle Devices inkl. DeviceGroups iterieren:
            # for dev in iter_devices(): ...
            "iter_devices":  lambda: _iter_all_devices(_sess.project),
            # .NET-Hilfen (im Sandbox gibt es kein import; Reflection auf System-Typen
            # hat den Server frueher abstuerzen lassen)
            "secure_string": _secure,
            "dir_info":      lambda p: DirectoryInfo(str(p)),
            "file_info":     lambda p: FileInfo(str(p)),
        }
        exec(textwrap.dedent(code), {"__builtins__":_SAFE_BUILTINS}, ctx)
        return {"status":"ok","mode":mode,"result":_to_json(ctx.get("result"))}
    return sta.run(_tia_call, _run)

# ── Setup / Teardown ──────────────────────────────────────────────────────────
def setup(log_dir="C:/tia-mcp/logs"):
    _setup_logging(log_dir); sta.start()

def teardown():
    sta.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# PLC EXPORT / IMPORT
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_EXPORT = r"C:\tia-mcp\export"

def _export_dir(path=None):
    """Exportpfad — Standard oder Override."""
    p = Path(path or _DEFAULT_EXPORT)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _find_block(plc_sw, block_name):
    """Baustein iterativ suchen — alle Gruppen."""
    stack = [plc_sw.BlockGroup]
    while stack:
        group = stack.pop()
        for block in group.Blocks:
            if block.Name == block_name:
                return block
        for sub in group.Groups:
            stack.append(sub)
    return None

def list_plc_blocks(device_name, group=None):
    """
    Alle PLC-Bausteine auflisten.
    Durchsucht BlockGroup rekursiv inkl. Untergruppen.
    group: optionaler Gruppenname für Filterung (z.B. "Ventile").
    Rückgabe je Baustein: name, type (OB/FC/FB/DB), language, number, group, is_consistent.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        blocks = []

        def _collect(bg, path):
            for b in bg.Blocks:
                btype = b.GetType().Name  # OB, FC, FB, DB, PlcStruct etc.
                lang  = str(getattr(b, "ProgrammingLanguage", "?"))
                blocks.append({
                    "name":          b.Name,
                    "type":          btype,
                    "language":      lang,
                    "number":        getattr(b, "Number", None),
                    "group":         path,
                    "is_consistent": getattr(b, "IsConsistent", None),
                })
            for g in bg.Groups:
                gpath = (path + "/" if path else "") + g.Name
                _collect(g, gpath)

        _collect(plc.BlockGroup, "")

        # Filtern nach Gruppe wenn angegeben
        if group:
            blocks = [b for b in blocks if b["group"] == group or b["group"].startswith(group + "/")]

        return {
            "device":  device_name,
            "count":   len(blocks),
            "blocks":  blocks,
        }
    return sta.run(_tia_call, _run)


def list_plc_tag_tables(device_name):
    """
    Alle PLC-Tag-Tabellen auflisten inkl. Untergruppen.
    Rückgabe je Tabelle: name, group, tag_count.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        tables = []

        def _collect(ttg, path):
            for tt in ttg.TagTables:
                tables.append({
                    "name":      tt.Name,
                    "group":     path,
                    "tag_count": tt.Tags.Count,
                })
            for g in ttg.Groups:
                gpath = (path + "/" if path else "") + g.Name
                _collect(g, gpath)

        _collect(plc.TagTableGroup, "")

        return {
            "device": device_name,
            "count":  len(tables),
            "tables": tables,
        }
    return sta.run(_tia_call, _run)


def list_plc_tags(device_name, table_name):
    """
    Alle Tags einer PLC-Tag-Tabelle auflisten.
    Rückgabe je Tag: name, data_type, logical_address, comment, visible.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # Tag-Tabelle suchen (Top-Level + Gruppen)
        found_table = None

        def _find(ttg):
            for tt in ttg.TagTables:
                if tt.Name == table_name:
                    return tt
            for g in ttg.Groups:
                result = _find(g)
                if result:
                    return result
            return None

        found_table = _find(plc.TagTableGroup)
        if not found_table:
            # Available-Liste aufbauen
            all_tables = []
            def _list(ttg):
                for tt in ttg.TagTables:
                    all_tables.append(tt.Name)
                for g in ttg.Groups:
                    _list(g)
            _list(plc.TagTableGroup)
            raise TiaError("TABLE_NOT_FOUND",
                f"Tag-Tabelle '{table_name}' nicht gefunden.", True,
                {"available": all_tables})

        tags = []
        for tag in found_table.Tags:
            tags.append({
                "name":            tag.Name,
                "data_type":       str(getattr(tag, "DataTypeName", "?")),
                "logical_address": str(getattr(tag, "LogicalAddress", "")),
                "comment":         _mltext(getattr(tag, "Comment", None)),
                "visible":         getattr(tag, "Visible", None),
            })

        return {
            "device":     device_name,
            "table":      table_name,
            "tag_count":  len(tags),
            "tags":       tags,
        }
    return sta.run(_tia_call, _run)


def list_plc_udts(device_name):
    """
    Alle PLC-UDTs (Strukturen) auflisten inkl. Untergruppen.
    Rückgabe je UDT: name, group, is_consistent, modified_date.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        udts = []

        def _collect(tg, path):
            for udt in tg.Types:
                udts.append({
                    "name":          udt.Name,
                    "type":          udt.GetType().Name,  # PlcStruct, PlcTypedeF...
                    "group":         path,
                    "is_consistent": getattr(udt, "IsConsistent", None),
                    "modified_date": str(getattr(udt, "ModifiedDate", "") or ""),
                })
            for g in tg.Groups:
                gpath = (path + "/" if path else "") + g.Name
                _collect(g, gpath)

        _collect(plc.TypeGroup, "")

        return {
            "device": device_name,
            "count":  len(udts),
            "udts":   udts,
        }
    return sta.run(_tia_call, _run)


def export_plc_block(device_name, block_name, output_path=None):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw_type = _get_sw_container_type()
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)
        block = _find_block(plc, block_name)
        if not block:
            avail = [b.Name for b in plc.BlockGroup.Blocks]
            raise TiaError("BLOCK_NOT_FOUND", f"Baustein '{block_name}' nicht gefunden.", True,
                           {"available": avail})
        out_dir = _export_dir(output_path)
        xml_file = out_dir / f"{block_name}.xml"
        if xml_file.exists(): xml_file.unlink()   # TIA überschreibt nicht
        block.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
        _log("plc").info(f"Exportiert: {block_name} → {xml_file}")
        return {"status": "ok", "block": block_name, "type": type(block).__name__,
                "xml_path": str(xml_file)}
    return sta.run(_tia_call, _run)

def import_plc_block(device_name, file_path):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)
        fi = FileInfo(file_path)
        if not fi.Exists:
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        result = plc.BlockGroup.Blocks.Import(fi, eng.ImportOptions.Override)
        _log("plc").info(f"Importiert: {file_path}")
        return {"status": "ok", "imported_from": file_path,
                "blocks": [str(b) for b in result] if result else []}
    return sta.run(_tia_call, _run)

def get_plc_block_source(device_name, block_name, output_path=None):
    """
    Exportiert Baustein und liest den Quellcode aus.
    SCL-Blöcke: gibt lesbaren SCL-Code zurück.
    LAD/FBD: gibt XML zurück.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)
        block = _find_block(plc, block_name)
        if not block:
            raise TiaError("BLOCK_NOT_FOUND", f"Baustein '{block_name}' nicht gefunden.", True)

        out_dir  = _export_dir(output_path)
        xml_file = out_dir / f"{block_name}.xml"
        if xml_file.exists(): xml_file.unlink()   # TIA überschreibt nicht
        block.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)

        # XML lesen
        xml_content = xml_file.read_text(encoding="utf-8")
        block_type  = type(block).__name__
        language    = getattr(block, "ProgrammingLanguage", None)
        lang_str    = str(language) if language else "Unknown"

        # SCL-Quellcode extrahieren
        # V21-Token-XML laesst sich nicht verlustfrei zusammensetzen (Bezeichner und
        # Leerraum stehen in eigenen Elementen) — daher TIA die Quelle generieren lassen.
        # Ergebnis ist der vollstaendige Baustein inkl. Schnittstelle, direkt wieder
        # mit set_plc_block_source importierbar.
        scl_source  = None
        scl_file    = None
        if "SCL" in lang_str.upper() or "StructuredControlLanguage" in lang_str:
            scl_file = out_dir / f"{block_name}.scl"
            if scl_file.exists(): scl_file.unlink()
            try:
                from Siemens.Engineering.SW.ExternalSources import IGenerateSource, GenerateOptions
                from System.Collections.Generic import List
                items = List[IGenerateSource]()
                items.Add(block)
                plc.ExternalSourceGroup.GenerateSource(items, FileInfo(str(scl_file)),
                                                       getattr(GenerateOptions, "None"))
                scl_source = scl_file.read_text(encoding="utf-8-sig")
            except Exception as e:
                _log("plc").warning(f"GenerateSource {block_name} fehlgeschlagen: {e}")
                scl_source = _extract_scl(xml_content)
                if scl_source:
                    scl_file.write_text(scl_source, encoding="utf-8")
                else:
                    scl_file = None

        return {
            "status":    "ok",
            "block":     block_name,
            "type":      block_type,
            "language":  lang_str,
            "xml_path":  str(xml_file),
            "scl_path":  str(scl_file) if scl_file else None,
            "scl_source": scl_source,
            "xml_size_kb": round(len(xml_content) / 1024, 1)
        }
    return sta.run(_tia_call, _run)

def _extract_scl(xml_content: str) -> str | None:
    """
    SCL-Quellcode aus TIA-XML extrahieren.
    V19/V20: <StructuredText>CODE</StructuredText> oder <Body>CODE</Body>
    V21:     <StructuredText xmlns="...v4"><Token Text="..."/><Token Text="..."/>...</StructuredText>
    """
    import re
    # V21: Token-basiertes Format (Schema v4)
    m = re.search(r"<StructuredText[^>]*>(.*?)</StructuredText>", xml_content, re.DOTALL)
    if m:
        inner = m.group(1).strip()
        if inner:
            # Token-Elemente zusammensetzen
            tokens = re.findall(r'<Token[^>]+Text="([^"]*)"', inner)
            if tokens:
                return "".join(tokens)
            # Kein Token — CDATA oder reiner Text
            src = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", inner, flags=re.DOTALL).strip()
            if src:
                return src
    # Ältere Formate
    for tag in ["Body", "SourceText"]:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml_content, re.DOTALL)
        if m:
            src = m.group(1).strip()
            src = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", src, flags=re.DOTALL)
            if src:
                return src
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# PLC TAG-TABELLEN EXPORT / IMPORT
# ═══════════════════════════════════════════════════════════════════════════════

def export_plc_tagtable(device_name, table_name, output_path=None):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)
        for table in plc.TagTableGroup.TagTables:
            if table.Name == table_name:
                out_dir  = _export_dir(output_path)
                xml_file = out_dir / f"plc_tags_{table_name}.xml"
                if xml_file.exists(): xml_file.unlink()
                table.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                return {"status": "ok", "table": table_name, "xml_path": str(xml_file)}
        raise TiaError("TABLE_NOT_FOUND", f"Tag-Tabelle '{table_name}' nicht gefunden.", True)
    return sta.run(_tia_call, _run)

def import_plc_tagtable(device_name, file_path):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)
        fi = FileInfo(file_path)
        if not fi.Exists:
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        plc.TagTableGroup.TagTables.Import(fi, eng.ImportOptions.Override)
        return {"status": "ok", "imported_from": file_path}
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# HMI EXPORT / IMPORT
# ═══════════════════════════════════════════════════════════════════════════════

def export_hmi_tagtable(device_name, table_name, output_path=None):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        sw, ht = _get_hmi(device_name)
        for table in _hmi_all_tag_tables(sw):
            if table.Name == table_name:
                # V19/V20: Export() direkt auf Tabelle
                if hasattr(table, "Export") and callable(getattr(table, "Export")):
                    out_dir  = _export_dir(output_path)
                    xml_file = out_dir / f"hmi_tags_{table_name}.xml"
                    if xml_file.exists(): xml_file.unlink()
                    table.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                    return {"status": "ok", "device": device_name, "hmi_type": ht,
                            "table": table_name, "xml_path": str(xml_file)}
                # V21 WinCC Advanced/Unified: Tags.Export(DirectoryInfo)
                if hasattr(table, "Tags") and hasattr(table.Tags, "Export"):
                    out_dir = _export_dir(output_path) / f"hmi_tags_{table_name}"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    files = list(table.Tags.Export(DirectoryInfo(str(out_dir))))
                    exported = [str(f) for f in files]
                    return {"status": "ok", "device": device_name, "hmi_type": ht,
                            "table": table_name, "exported": exported,
                            "export_dir": str(out_dir)}
                raise TiaError("TAG_EXPORT_NOT_SUPPORTED",
                    f"HMI Tag-Tabelle '{table_name}' gefunden, aber kein Export verfügbar "
                    f"({ht}). Workaround: list_hmi_tags + write_import_file.", False,
                    {"table": table_name, "hmi_type": ht})
        available = [t.Name for t in _hmi_all_tag_tables(sw)]
        raise TiaError("TABLE_NOT_FOUND", f"HMI Tag-Tabelle '{table_name}' nicht gefunden.", True,
                       {"available": available})
    return sta.run(_tia_call, _run)

def import_hmi_tagtable(device_name, file_path):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        sw, ht = _get_hmi(device_name)
        p = Path(file_path)
        if not p.exists():
            raise TiaError("FILE_NOT_FOUND", f"Datei/Ordner nicht gefunden: {file_path}", True)
        # Ordner-Import (V21 Tags.Import(DirectoryInfo))
        if p.is_dir():
            for table in _hmi_tag_tables(sw):
                if hasattr(table, "Tags") and hasattr(table.Tags, "Import"):
                    table.Tags.Import(DirectoryInfo(str(p)))
                    return {"status": "ok", "device": device_name, "imported_from": file_path}
        # Datei-Import (V19/V20)
        _hmi_tag_tables_import(sw, FileInfo(str(p)), eng)
        return {"status": "ok", "device": device_name, "imported_from": file_path}
    return sta.run(_tia_call, _run)


def import_hmi_tags(device_name, file_path):
    """Alle HMI-Tags aus Datei oder Ordner importieren."""
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        sw, ht = _get_hmi(device_name)
        p = Path(file_path)
        if not p.exists():
            raise TiaError("FILE_NOT_FOUND", f"Datei/Ordner nicht gefunden: {file_path}", True)
        if p.is_dir():
            for table in _hmi_tag_tables(sw):
                if hasattr(table, "Tags") and hasattr(table.Tags, "Import"):
                    table.Tags.Import(DirectoryInfo(str(p)))
            return {"status": "ok", "device": device_name, "imported_from": file_path}
        _hmi_tag_tables_import(sw, FileInfo(str(p)), eng)
        return {"status": "ok", "device": device_name, "imported_from": file_path}
    return sta.run(_tia_call, _run)


def _get_screen_variant_coll(sw, screen_type):
    """Gibt (collection, item_attr) für den angefragten Screen-Typ zurück."""
    if screen_type == "template":
        f = getattr(sw, "ScreenTemplateFolder", None)
        return (getattr(f, "ScreenTemplates", None) if f else None, "ScreenTemplates")
    elif screen_type == "slidein":
        f = getattr(sw, "ScreenSlideinFolder", None)
        return (getattr(f, "ScreenSlideins", None) if f else None, "ScreenSlideins")
    elif screen_type == "popup":
        f = getattr(sw, "ScreenPopupFolder", None)
        return (getattr(f, "ScreenPopups", None) if f else None, "ScreenPopups")
    elif screen_type == "global_elements":
        return (getattr(sw, "ScreenGlobalElements", None), "ScreenGlobalElements")
    elif screen_type == "overview":
        return (getattr(sw, "ScreenOverview", None), "ScreenOverview")
    else:
        raise TiaError("INVALID_SCREEN_TYPE",
            f"Ungültiger screen_type '{screen_type}'. Gültig: template, slidein, popup, global_elements, overview", True)

_SCREEN_VARIANT_TYPES = ["template", "slidein", "popup", "global_elements", "overview"]

def list_hmi_screen_management(device_name, screen_type=None):
    """
    Screen-Management-Objekte eines Advanced-HMI auflisten.
    screen_type: template | slidein | popup | global_elements | overview | None (alle)
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        types_to_check = [screen_type] if screen_type else _SCREEN_VARIANT_TYPES
        result = {}
        for stype in types_to_check:
            try:
                coll, _ = _get_screen_variant_coll(sw, stype)
            except TiaError:
                result[stype] = {"error": "invalid type"}
                continue
            if coll is None:
                result[stype] = {"count": 0, "note": "nicht verfügbar"}
                continue
            # global_elements und overview sind einzelne Objekte, keine Collections
            if stype in ("global_elements", "overview"):
                result[stype] = {"type": type(coll).__name__, "has_export": hasattr(coll, "Export")}
            else:
                items = []
                for i in range(coll.Count):
                    item = coll[i]
                    label = (str(item.SlideinType) if stype == "slidein" and hasattr(item, "SlideinType")
                             else str(item.Name) if hasattr(item, "Name") else f"item_{i}")
                    items.append({"name": label})
                result[stype] = {"count": coll.Count, "items": items}
        return {"device": device_name, "hmi_type": ht, "screen_management": result}
    return sta.run(_tia_call, _run)

def export_hmi_screen_management(device_name, screen_type, output_path=None):
    """
    Screen-Management-Objekte exportieren.
    screen_type: template | slidein | global_elements | overview
    (popup: kein Export in V21)
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        out_dir = Path(output_path) if output_path else _export_dir(None)
        out_dir.mkdir(parents=True, exist_ok=True)
        coll, coll_attr = _get_screen_variant_coll(sw, screen_type)
        if coll is None:
            raise TiaError("SCREEN_MGMT_NOT_FOUND",
                f"'{screen_type}' nicht verfügbar für '{device_name}'.", True)
        exported = []
        errors = []
        # global_elements und overview: einzelne Objekte mit Export-Methode
        if screen_type in ("global_elements", "overview"):
            safe = screen_type.replace("_", "")
            xml_file = out_dir / f"hmi_{safe}_{device_name}.xml"
            if xml_file.exists():
                xml_file.unlink()
            try:
                coll.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                exported.append({"name": screen_type, "file": str(xml_file)})
            except Exception as ex:
                errors.append({"name": screen_type, "error": str(ex)})
        else:
            # Collections: Export auf einzelnen Items
            for i in range(coll.Count):
                item = coll[i]
                if not hasattr(item, "Export"):
                    errors.append({"name": str(item.Name), "error": "kein Export"})
                    continue
                label = (str(item.SlideinType) if screen_type == "slidein" and hasattr(item, "SlideinType")
                         else str(item.Name) if hasattr(item, "Name") else f"item_{i}")
                xml_file = out_dir / f"hmi_{screen_type}_{device_name}_{label}.xml"
                if xml_file.exists():
                    xml_file.unlink()
                try:
                    item.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                    exported.append({"name": label, "file": str(xml_file)})
                except Exception as ex:
                    errors.append({"name": label, "error": str(ex)})
        if not exported and errors:
            raise TiaError("SCREEN_MGMT_EXPORT_FAILED", f"Export fehlgeschlagen: {errors}", False)
        return {"status": "ok", "device": device_name, "screen_type": screen_type,
                "exported": exported, "errors": errors, "count": len(exported)}
    return sta.run(_tia_call, _run)

def import_hmi_screen_management(device_name, screen_type, file_path):
    """
    Screen-Management-Objekte importieren.
    screen_type: template | slidein | popup | global_elements | overview
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        fi = FileInfo(file_path)
        if not fi.Exists:
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        coll, _ = _get_screen_variant_coll(sw, screen_type)
        if coll is None:
            raise TiaError("SCREEN_MGMT_NOT_FOUND",
                f"'{screen_type}' nicht verfügbar für '{device_name}'.", True)
        if screen_type in ("global_elements", "overview"):
            # Einzelobjekt: Import via HmiTarget-Methode
            method = {"global_elements": "ImportScreenGlobalElements",
                      "overview": "ImportScreenOverview"}.get(screen_type)
            getattr(sw, method)(fi, eng.ImportOptions.Override)
        else:
            coll.Import(fi, eng.ImportOptions.Override)
        return {"status": "ok", "device": device_name,
                "screen_type": screen_type, "imported_from": file_path}
    return sta.run(_tia_call, _run)

def export_hmi_screens_all(device_name, output_path=None):
    """
    Alle HMI-Screens exportieren.
    Advanced: s.Export(FileInfo). Unified: .hmiScreen-Dateien aus Projektordner kopieren.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        out_dir = (_export_dir(None) / f"hmi_screens_{device_name}") \
                  if not output_path else Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        all_screens = _hmi_screens(sw)
        if not all_screens:
            raise TiaError("NO_SCREENS", f"HMI '{device_name}' hat keine Screens.", True)
        exported = []
        if ht == "Advanced":
            for s in all_screens:
                safe_name = s.Name.replace(" ", "_").replace("/", "_")
                xml_file = out_dir / f"{safe_name}.xml"
                if xml_file.exists(): xml_file.unlink()
                try:
                    s.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                    exported.append({"screen": s.Name, "path": str(xml_file), "method": "api_export"})
                except Exception as e:
                    exported.append({"screen": s.Name, "error": str(e)})
        else:
            import shutil as _shutil
            proj_path = str(_sess.project.Path)
            screen_files = _unified_screen_files(proj_path)
            for s in all_screens:
                name = s.Name
                if name in screen_files:
                    src = screen_files[name]
                    dst = out_dir / src.name
                    if dst.exists(): dst.unlink()
                    _shutil.copy2(str(src), str(dst))
                    exported.append({"screen": name, "path": str(dst), "method": "filesystem_copy"})
                else:
                    exported.append({"screen": name,
                                     "error": "Keine .hmiScreen-Datei — Projekt gespeichert?"})
        ok_count = len([e for e in exported if "path" in e])
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "exported": exported, "count": ok_count}
    return sta.run(_tia_call, _run)

def export_hmi_scripts(device_name, output_path=None):
    """
    HMI-Scripts exportieren.
    Unified:            sw.Scripts.Export(DirectoryInfo)
    Advanced HmiTarget: sw.VBScriptFolder.VBScripts einzeln exportieren
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        sw, ht = _get_hmi(device_name)
        out_dir = (_export_dir(None) / f"hmi_scripts_{device_name}") \
                  if not output_path else Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        exported = []

        # Unified: sw.Scripts
        scripts = getattr(sw, "Scripts", None)
        if scripts is not None:
            if hasattr(scripts, "Export"):
                files = list(scripts.Export(DirectoryInfo(str(out_dir))))
                exported = [str(f) for f in files]
            else:
                for sc in scripts:
                    safe_name = sc.Name.replace(" ", "_").replace("/", "_")
                    if hasattr(sc, "Export"):
                        xml_file = out_dir / f"{safe_name}.xml"
                        if xml_file.exists(): xml_file.unlink()
                        sc.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                        exported.append(str(xml_file))

        # Advanced HmiTarget: sw.VBScriptFolder
        if not exported and hasattr(sw, "VBScriptFolder"):
            vbf = sw.VBScriptFolder
            for sc in vbf.VBScripts:
                safe_name = sc.Name.replace(" ", "_").replace("/", "_")
                if hasattr(sc, "Export"):
                    xml_file = out_dir / f"{safe_name}.xml"
                    if xml_file.exists(): xml_file.unlink()
                    sc.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                    exported.append(str(xml_file))
            for sub in vbf.Folders:
                for sc in sub.VBScripts:
                    safe_name = sc.Name.replace(" ", "_").replace("/", "_")
                    if hasattr(sc, "Export"):
                        xml_file = out_dir / f"{sub.Name}_{safe_name}.xml"
                        if xml_file.exists(): xml_file.unlink()
                        sc.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                        exported.append(str(xml_file))

        if not exported:
            raise TiaError("NO_SCRIPTS",
                f"HMI '{device_name}' hat keine Scripts oder Export nicht verfügbar.", True)
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "exported": exported, "count": len(exported)}
    return sta.run(_tia_call, _run)

def import_hmi_scripts(device_name, file_path):
    """HMI-Scripts importieren. Unified: Scripts.Import(DirectoryInfo). Advanced HmiTarget: VBScriptComposition.Import(FileInfo, ImportOptions)."""
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo, DirectoryInfo
        sw, ht = _get_hmi(device_name)
        p = Path(file_path)
        if not p.exists():
            raise TiaError("FILE_NOT_FOUND", f"Datei/Ordner nicht gefunden: {file_path}", True)

        # Unified: Scripts.Import(DirectoryInfo)
        scripts = getattr(sw, "Scripts", None)
        if scripts is not None and hasattr(scripts, "Import"):
            arg = DirectoryInfo(str(p)) if p.is_dir() else FileInfo(str(p))
            scripts.Import(arg)
            return {"status": "ok", "device": device_name, "imported_from": file_path}

        # Advanced HmiTarget: VBScriptComposition.Import(FileInfo, ImportOptions)
        if hasattr(sw, "VBScriptFolder"):
            vbf = sw.VBScriptFolder
            if hasattr(vbf, "VBScripts") and hasattr(vbf.VBScripts, "Import"):
                imported = []
                if p.is_dir():
                    # Alle XML-Dateien im Ordner einzeln importieren
                    for xml_file in p.glob("*.xml"):
                        vbf.VBScripts.Import(FileInfo(str(xml_file)), eng.ImportOptions.Override)
                        imported.append(str(xml_file))
                else:
                    vbf.VBScripts.Import(FileInfo(str(p)), eng.ImportOptions.Override)
                    imported.append(str(p))
                return {"status": "ok", "device": device_name,
                        "imported_from": file_path, "files": imported}

        raise TiaError("SCRIPTS_IMPORT_NOT_SUPPORTED",
            f"Scripts-Import nicht verfügbar für '{device_name}' ({ht}).", False)
    return sta.run(_tia_call, _run)



def import_hmi_screen(device_name, file_path):
    """
    HMI-Screen importieren.
    Advanced: existierenden Screen gleichen Namens löschen, dann Import via API.
    Unified:  ⏭ V21-Limitation — kein Screen-Import via API.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        src = Path(file_path)
        if not src.exists():
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)

        if ht == "Unified":
            raise TiaError("SCREEN_IMPORT_NOT_SUPPORTED",
                f"Screen-Import für Unified nicht verfügbar (V21-Limitation).", False,
                {"hint": "Unified-Screens können nur manuell in TIA Portal importiert werden."})

        # Advanced: Screen-Name aus XML lesen (nicht aus Dateinamen)
        try:
            import xml.etree.ElementTree as _et
            tree = _et.parse(str(src))
            root = tree.getroot()
            # TIA XML: <SW.Screens.Screen ... Name="..."> oder Attribut in ObjectList
            screen_name = None
            for elem in root.iter():
                if "Screen" in elem.tag and elem.get("Name"):
                    screen_name = elem.get("Name")
                    break
                # Alternative: AttributeList/Name
                if elem.tag.endswith("Name") and elem.text:
                    parent_tag = elem.getparent().tag if hasattr(elem, "getparent") else ""
                    if "Screen" in parent_tag:
                        screen_name = elem.text
                        break
            # Fallback: alle Children nach Name-Tag suchen
            if not screen_name:
                for elem in root.iter():
                    if elem.tag == "Name" and elem.text:
                        screen_name = elem.text
                        break
        except Exception:
            screen_name = None

        # Existierenden Screen löschen
        deleted = []
        if screen_name:
            for s in _hmi_screens(sw):
                if s.Name == screen_name:
                    s.Delete()
                    deleted.append(screen_name)
                    break

        _hmi_screens_import(sw, FileInfo(str(src)), eng)
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "imported_from": file_path, "method": "api_import",
                "deleted_before_import": deleted}
    return sta.run(_tia_call, _run)


def export_hmi_alarms(device_name, output_path=None):
    """
    HMI-Alarme als JSON exportieren (alle Attribute via GetAttributeInfos).
    Kein natives API-Export in V21 — JSON ermöglicht Soll/Ist-Vergleich.
    output_path: Zieldatei .json (Standard: C:\\tia-mcp\\export\\hmi_alarms_<device>.json).
    """
    def _run():
        _sess.ensure_project()
        import json as _json
        sw, ht = _get_hmi(device_name)
        out_dir  = _export_dir(None if output_path and Path(output_path).suffix else output_path)
        json_file = Path(output_path) if (output_path and Path(output_path).suffix) \
                    else out_dir / f"hmi_alarms_{device_name}.json"
        json_file.parent.mkdir(parents=True, exist_ok=True)
        alarms = []
        for attr, kind in [("DiscreteAlarms", "discrete"), ("AnalogAlarms", "analog"), ("Alarms", "unified")]:
            if hasattr(sw, attr):
                try:
                    for a in getattr(sw, attr):
                        alarms.append(_alarm_to_dict(a, kind))
                except Exception as e:
                    pass
        result = {"device": device_name, "hmi_type": ht, "alarms": alarms, "count": len(alarms)}
        json_file.write_text(_json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "count": len(alarms), "json_path": str(json_file)}
    return sta.run(_tia_call, _run)

_ALARM_SKIP = {"_alarm_type", "name", "Name"}

def import_hmi_alarms(device_name, file_path):
    """
    HMI-Alarme aus JSON importieren (SetAttribute für jedes schreibbare Attribut).
    Gegenstück zu export_hmi_alarms — matched per Name.
    """
    def _run():
        _sess.ensure_project()
        import json as _json
        sw, ht = _get_hmi(device_name)
        p = Path(file_path)
        if not p.exists():
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        data = _json.loads(p.read_text(encoding="utf-8"))
        src_alarms = data.get("alarms", [])

        # Aufbau Name→Objekt-Map
        alarm_map = {}
        for attr, kind in [("DiscreteAlarms", "discrete"), ("AnalogAlarms", "analog"), ("Alarms", "unified")]:
            if hasattr(sw, attr):
                try:
                    for a in getattr(sw, attr):
                        alarm_map[str(a.Name)] = (a, kind)
                except Exception:
                    pass

        applied, skipped = [], []
        for src in src_alarms:
            name = src.get("name") or src.get("Name", "")
            if name not in alarm_map:
                skipped.append({"name": name, "reason": "not_found"})
                continue
            obj, _ = alarm_map[name]
            changes = []
            for k, v in src.items():
                if k in _ALARM_SKIP or v is None:
                    continue
                try:
                    obj.SetAttribute(k, v)
                    changes.append(k)
                except Exception:
                    pass
            applied.append({"name": name, "changes": changes})
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "applied": applied, "skipped": skipped}
    return sta.run(_tia_call, _run)

def export_hmi_textlists(device_name, output_path=None):
    """
    HMI-Textlisten als XML exportieren — eine Datei pro Textliste.
    output_path: Zielordner (Standard: C:\\tia-mcp\\export\\).
    Gibt Liste aller exportierten Dateien zurück.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        _, ht = _get_hmi(device_name)
        out_dir = Path(output_path) if output_path else _export_dir(None)
        out_dir.mkdir(parents=True, exist_ok=True)
        exported = []
        errors = []
        seen = set()
        all_sw = _get_hmi_all_sw(device_name)
        for _item_name, sw, sw_ht in all_sw:
            colls = (["HmiTextLists", "HmiSystemTextLists"] if sw_ht == "Unified"
                     else (["TextLists"] if hasattr(sw, "TextLists") else []))
            for coll_name in colls:
                if not hasattr(sw, coll_name):
                    continue
                coll = getattr(sw, coll_name)
                for i in range(coll.Count):
                    tl = coll[i]
                    key = f"{coll_name}:{tl.Name}"
                    if key in seen:
                        continue
                    seen.add(key)
                    xml_file = out_dir / f"hmi_tl_{device_name}_{tl.Name}.xml"
                    if xml_file.exists():
                        xml_file.unlink()
                    try:
                        tl.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                        exported.append({"name": tl.Name, "file": str(xml_file)})
                    except Exception as ex:
                        errors.append({"name": tl.Name, "error": str(ex)})
        if not exported:
            raise TiaError("TEXTLIST_EXPORT_NOT_SUPPORTED",
                f"Keine Textlisten exportierbar. errors={errors}", True)
        return {"status": "ok", "device": device_name, "hmi_type": ht,
                "exported": exported, "count": len(exported)}
    return sta.run(_tia_call, _run)

def import_hmi_textlists(device_name, file_path):
    """
    HMI-Textlisten aus XML importieren (eine Datei, Override).
    Gegenstück zu export_hmi_textlists.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        _, ht = _get_hmi(device_name)
        fi = FileInfo(file_path)
        if not fi.Exists:
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        for _item_name, sw, sw_ht in _get_hmi_all_sw(device_name):
            coll_name = "HmiTextLists" if sw_ht == "Unified" else "TextLists"
            if not hasattr(sw, coll_name):
                continue
            getattr(sw, coll_name).Import(fi, eng.ImportOptions.Override)
            return {"status": "ok", "device": device_name, "imported_from": file_path}
        raise TiaError("TEXTLIST_IMPORT_NOT_SUPPORTED",
            f"Kein Textlisten-Import für HMI '{device_name}' ({ht}) verfügbar.", False)
    return sta.run(_tia_call, _run)

def create_hmi_structure(device_name, structure):
    """
    Legt Ordner unter Bilder (Screens) und Tag-Tabellen im HMI an.
    Funktioniert für WinCC Advanced und WinCC Unified.

    structure: dict mit optionalen Keys 'screens' und 'tag_tables'.
    Jeder Wert ist eine Liste aus Strings oder Dicts {"Ordner": ["Kind1","Kind2"]}.

    Beispiel:
        {
          "screens":    ["Start", {"Antriebe": ["Motor1","Motor2"]}, "Pumpen"],
          "tag_tables": ["Allgemein", {"Antriebe": ["Motoren","Umrichter"]}]
        }
    """
    def _flatten(items):
        """Gibt Liste von (parent, child_or_None) zurück."""
        out = []
        for item in items:
            if isinstance(item, str):
                out.append((item, None))
            elif isinstance(item, dict):
                for folder, children in item.items():
                    if not children:
                        out.append((folder, None))
                    else:
                        for child in (children if isinstance(children, list) else [children]):
                            out.append((folder, child))
        return out

    def _ensure(collection, name, child_attr):
        """Gibt Ordner zurück, legt ihn an falls nötig."""
        for f in collection:
            if f.Name == name:
                return f
        return collection.Create(name)

    def _run():
        _sess.ensure_project()
        sw, ht = _get_hmi(device_name)
        created = {"screens": [], "tag_tables": []}
        errors  = []

        # ── Bilder / Screens ────────────────────────────────────────────────
        screen_items = structure.get("screens", [])
        if screen_items:
            folders, ftype = _hmi_screen_folders(sw)
            if folders is None:
                errors.append("Screen-Ordner nicht unterstützt auf diesem HMI-Typ.")
            else:
                # Unterordner-Attribut je nach Typ
                sub_attr = ftype  # "ScreenGroups" oder "ScreenFolders"
                for parent, child in _flatten(screen_items):
                    try:
                        pf = _ensure(folders, parent, sub_attr)
                        entry = f"{parent}"
                        if child:
                            sub = getattr(pf, sub_attr, None)
                            if sub is not None:
                                _ensure(sub, child, sub_attr)
                                entry = f"{parent}/{child}"
                            else:
                                errors.append(f"Unterordner '{parent}/{child}': "
                                              f"keine Sub-Collection ({sub_attr}) gefunden.")
                        if entry not in created["screens"]:
                            created["screens"].append(entry)
                    except Exception as e:
                        errors.append(f"Screen-Ordner '{parent}': {e}")

        # ── Tag-Tabellen ─────────────────────────────────────────────────────
        tag_items = structure.get("tag_tables", [])
        if tag_items:
            tag_root, ttype = _hmi_tag_folders(sw)
            if tag_root is None:
                errors.append("Tag-Tabellen-Ordner nicht unterstützt auf diesem HMI-Typ.")
            else:
                # Advanced V21: TagTableGroups ist die Root-Collection
                # Advanced älter / Unified: TagTableGroup ist ein einzelnes Root-Objekt
                #   dessen Unterordner über .TagTableGroups erreichbar sind
                if ttype == "TagTableGroups":
                    root_coll = tag_root          # direkt iterable Collection
                    sub_attr  = "TagTableGroups"
                else:
                    # TagTableGroup (singular) → Unterordner via .TagTableGroups
                    root_coll = getattr(tag_root, "TagTableGroups", None)
                    sub_attr  = "TagTableGroups"
                    if root_coll is None:
                        errors.append("TagTableGroup hat keine TagTableGroups-Unterordner.")
                        root_coll = []

                for parent, child in _flatten(tag_items):
                    try:
                        pf = _ensure(root_coll, parent, sub_attr)
                        entry = f"{parent}"
                        if child:
                            sub = getattr(pf, sub_attr, None)
                            if sub is not None:
                                _ensure(sub, child, sub_attr)
                                entry = f"{parent}/{child}"
                            else:
                                errors.append(f"Unterordner '{parent}/{child}': "
                                              f"keine Sub-Collection gefunden.")
                        if entry not in created["tag_tables"]:
                            created["tag_tables"].append(entry)
                    except Exception as e:
                        errors.append(f"Tag-Tabellen-Ordner '{parent}': {e}")

        return {
            "status":  "ok" if not errors else "partial",
            "device":  device_name,
            "hmi_type": ht,
            "created": created,
            "errors":  errors,
        }
    return sta.run(_tia_call, _run)

_SCL_HEADER_RE = re.compile(
    r'^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK)\s+"?([^"\s:]+)"?', re.M)
_SCL_BEGIN_RE  = re.compile(r'^[ \t]*BEGIN[ \t]*\r?$', re.M)
_SCL_END_RE    = re.compile(r'^[ \t]*END_(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK)[ \t]*\r?$', re.M)

def set_plc_block_source(device_name, block_name, scl_source):
    """
    SCL-Quellcode schreiben — ueber eine externe Quelle (PlcExternalSource).
    scl_source kann sein:
      - vollstaendiger Baustein (FUNCTION_BLOCK "Name" ... END_FUNCTION_BLOCK):
        Schnittstelle + Rumpf werden ersetzt, Baustein wird bei Bedarf neu angelegt.
      - nur Rumpf (Anweisungen): Schnittstelle bleibt, Quelle des bestehenden
        Bausteins wird generiert und der Teil zwischen BEGIN und END_... ersetzt.
    TIA uebersetzt die Quelle selbst (GenerateBlocksFromSource) — kein eigenes
    Token-XML mehr (das scheiterte mit 'The token is not supported').
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from Siemens.Engineering.SW.ExternalSources import (
            IGenerateSource, GenerateOptions, GenerateBlockOption)
        from System.Collections.Generic import List
        from System.IO import FileInfo

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        try:
            state = str(_online_provider(device_name).State)
        except TiaError:
            state = "Offline"
        if state != "Offline":
            raise TiaError("PLC_ONLINE",
                f"PLC '{device_name}' ist {state} — Quellen-Import nur offline moeglich. "
                "Vorher go_offline aufrufen.", True, {"state": state})

        block = _find_block(plc, block_name)
        if block:
            lang = str(getattr(block, "ProgrammingLanguage", ""))
            if "SCL" not in lang.upper():
                raise TiaError("WRONG_LANGUAGE",
                    f"Baustein '{block_name}' ist {lang}, kein SCL — set_plc_block_source nur fuer SCL.", True)

        out_dir = _export_dir()
        src_file = out_dir / f"{block_name}_set.scl"

        m = _SCL_HEADER_RE.search(scl_source)
        if m:
            mode = "full"
            if m.group(2) != block_name:
                raise TiaError("BLOCK_NAME_MISMATCH",
                    f"Quelle definiert '{m.group(2)}', erwartet '{block_name}'.", True)
            source_text = scl_source
        else:
            mode = "body"
            if not block:
                raise TiaError("BLOCK_NOT_FOUND",
                    f"Baustein '{block_name}' nicht gefunden. Fuer neue Bausteine den "
                    "vollstaendigen Quelltext (FUNCTION_BLOCK ... END_FUNCTION_BLOCK) uebergeben.", True)
            gen_file = out_dir / f"{block_name}_gen.scl"
            if gen_file.exists(): gen_file.unlink()
            items = List[IGenerateSource]()
            items.Add(block)
            plc.ExternalSourceGroup.GenerateSource(items, FileInfo(str(gen_file)), getattr(GenerateOptions, "None"))
            gen = gen_file.read_text(encoding="utf-8-sig")
            b = _SCL_BEGIN_RE.search(gen)
            e = list(_SCL_END_RE.finditer(gen))
            if not b or not e:
                raise TiaError("SCL_SOURCE_UNEXPECTED",
                    "BEGIN / END_... in generierter Quelle nicht gefunden.", False,
                    {"source_path": str(gen_file)})
            source_text = gen[:b.end()] + "\n" + scl_source.strip("\r\n") + "\n" + gen[e[-1].start():]

        source_text = source_text.replace("\r\n", "\n").replace("\n", "\r\n")
        src_file.write_text(source_text, encoding="utf-8-sig", newline="")

        # Zielgruppe: bestehender Baustein bleibt in seiner Untergruppe
        target_group = None
        if block:
            grp = block.Parent
            if type(grp).__name__ == "PlcBlockUserGroup":
                target_group = grp

        sources = plc.ExternalSourceGroup.ExternalSources
        src_name = f"MCP_{block_name}"
        old = sources.Find(src_name)
        if old: old.Delete()
        src = sources.CreateFromFile(src_name, str(src_file))
        try:
            if target_group is not None:
                created = src.GenerateBlocksFromSource(target_group, getattr(GenerateBlockOption, "None"))
            else:
                created = src.GenerateBlocksFromSource(getattr(GenerateBlockOption, "None"))
        except Exception as ex:
            msg = [l.strip() for l in str(ex).splitlines() if l.strip() and not l.strip().startswith("bei ")]
            raise TiaError("SCL_GENERATE_FAILED",
                "Baustein konnte nicht aus der Quelle erzeugt werden: " + " | ".join(msg[:6]), True,
                {"source_path": str(src_file), "mode": mode})
        finally:
            try: src.Delete()
            except Exception: pass

        # Erzeugter Baustein ist inkonsistent und Syntaxfehler fallen erst beim
        # Uebersetzen auf — daher direkt den Baustein uebersetzen.
        new_block = _find_block(plc, block_name)
        errors, warnings, messages = _compile(new_block)
        _log("plc").info(f"SCL gesetzt ({mode}): {block_name} — {errors} Fehler, {warnings} Warnungen")
        return {"status": "ok" if errors == 0 else "error", "block": block_name, "mode": mode,
                "source_path": str(src_file),
                "compile": {"errors": errors, "warnings": warnings, "messages": messages[:20]}}
    return sta.run(_tia_call, _run, timeout=_STA_TIMEOUT_HEAVY)

# ═══════════════════════════════════════════════════════════════════════════════
# DATEI-HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════════════════════

def write_import_file(filename: str, content: str) -> dict:
    """
    Schreibt Dateiinhalt (z.B. aus Chat-Upload) in den Import-Ordner.
    Claude kann so hochgeladene XML-Dateien fuer den Import bereitstellen.
    """
    import_dir = Path(_DEFAULT_EXPORT) / "import"
    import_dir.mkdir(parents=True, exist_ok=True)
    out = import_dir / filename
    out.write_text(content, encoding="utf-8")
    _log("import").info(f"Import-Datei geschrieben: {out}")
    return {"status": "ok", "path": str(out)}

def read_export_file(file_path: str) -> dict:
    """Liest eine exportierte Datei und gibt den Inhalt zurueck."""
    p = Path(file_path)
    if not p.exists():
        raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
    content = p.read_text(encoding="utf-8")
    return {"status": "ok", "path": file_path,
            "content": content, "size_kb": round(len(content)/1024, 1)}

# ═══════════════════════════════════════════════════════════════════════════════
# KOMPILIEREN
# ═══════════════════════════════════════════════════════════════════════════════

def _compile(obj):
    """ICompilable-Service von obj (PlcSoftware oder PlcBlock) ausfuehren.
    Rueckgabe: (ErrorCount, WarningCount, Meldungen). Meldungen sind hierarchisch —
    die eigentlichen Fehlertexte stehen in den Blaettern."""
    compiler = obj.GetService[_compilable_type(obj)]()
    if not compiler:
        raise TiaError("COMPILE_NOT_SUPPORTED",
            "Kein Compiler-Service verfuegbar.", False)
    result = compiler.Compile()
    messages = []
    def _walk(msgs, path):
        for msg in msgs:
            desc = str(msg.Description)
            sub = list(getattr(msg, "Messages", []) or [])
            p = f"{path}/{msg.Path}" if path and str(getattr(msg, "Path", "")) else str(getattr(msg, "Path", "")) or path
            if sub:
                _walk(sub, p)
            elif str(msg.State) in ("Error", "Warning"):
                messages.append({"severity": str(msg.State), "description": desc, "path": p})
    try:
        _walk(result.Messages, "")
    except Exception:
        pass
    return result.ErrorCount, result.WarningCount, messages

def _compilable_type(obj):
    # ICompilable liegt in V21 in Siemens.Engineering.Base (Compiler-Namespace).
    # Strategie: alle geladenen Assemblies nach dem Typ durchsuchen.
    compilable_type = None
    step7_asm = obj.GetType().Assembly
    # 1) Direkt aus Step7-Assembly
    compilable_type = step7_asm.GetType("Siemens.Engineering.Compiler.ICompilable")
    # 2) Aus Base-Assembly (referenziert von Step7)
    if not compilable_type:
        for ref in step7_asm.GetReferencedAssemblies():
            if "Base" in str(ref.Name):
                try:
                    import System.Reflection as refl
                    base_asm = refl.Assembly.Load(ref)
                    compilable_type = base_asm.GetType(
                        "Siemens.Engineering.Compiler.ICompilable")
                    if compilable_type:
                        break
                except Exception:
                    pass
    # 3) Fallback: Namespace direkt importieren
    if not compilable_type:
        try:
            from Siemens.Engineering.Compiler import ICompilable
            compilable_type = ICompilable
        except Exception:
            pass

    if not compilable_type:
        raise TiaError("COMPILE_NOT_SUPPORTED",
            "ICompilable nicht gefunden — Siemens.Engineering.Base.dll pruefen.", False)
    return compilable_type

def compile_plc(device_name):
    """SPS kompilieren — behebt inkonsistente Bausteine vor dem Export."""
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        errors, warnings, messages = _compile(plc)
        _log("compile").info(
            f"Kompiliert {device_name}: {errors} Fehler, {warnings} Warnungen")
        return {
            "status":   "ok" if errors == 0 else "error",
            "device":   device_name,
            "errors":   errors,
            "warnings": warnings,
            "messages": messages[:20]
        }
    return sta.run(_tia_call, _run, timeout=_STA_TIMEOUT_HEAVY)

# ═══════════════════════════════════════════════════════════════════════════════
# ONLINE / OFFLINE
# ═══════════════════════════════════════════════════════════════════════════════

def _online_provider(device_name):
    """OnlineProvider-Service der CPU. Typ liegt in V21 in Siemens.Engineering.Base."""
    item = _find_plc_item(device_name)
    op_type = _sess.project.GetType().Assembly.GetType("Siemens.Engineering.Online.OnlineProvider")
    if not op_type:
        raise TiaError("ONLINE_NOT_SUPPORTED",
            "OnlineProvider nicht gefunden — Siemens.Engineering.Base.dll pruefen.", False)
    op = item.GetService[op_type]()
    if not op:
        raise TiaError("ONLINE_NOT_SUPPORTED",
            f"Kein OnlineProvider fuer '{device_name}' verfuegbar.", False)
    return op

def _online_options(cfg):
    """Verfuegbare Modi / PG-PC-Schnittstellen / Zielschnittstellen auflisten."""
    modes = []
    for m in cfg.Modes:
        pcs = []
        for pc in m.PcInterfaces:
            pcs.append({"name": str(pc.Name), "number": int(pc.Number),
                        "targets": [str(ti.Name) for ti in pc.TargetInterfaces]})
        modes.append({"mode": str(m.Name), "pc_interfaces": pcs})
    return modes

def get_online_state(device_name):
    def _run():
        _sess.ensure_project()
        op = _online_provider(device_name)
        cfg = op.Configuration
        return {"status": "ok", "device": device_name,
                "state": str(op.State),
                "is_configured": bool(cfg.IsConfigured),
                "options": _online_options(cfg)}
    return sta.run(_tia_call, _run)

def _secure(text):
    import System.Security
    s = System.Security.SecureString()
    for ch in text:
        s.AppendChar(ch)
    s.MakeReadOnly()
    return s

def _legitimation_handler(requests, user=None, password=None, trust_certificate=False):
    """Handler fuer ConnectionConfiguration.OnlineLegitimation (V21).
    TIA fragt darueber Anmeldung, Passwort und TLS-Zertifikat ab. Ohne Handler
    bricht GoOnline() mit EngineeringTargetInvocationException ab."""
    def _h(c):
        kind = c.GetType().Name
        entry = {"type": kind}
        try:
            if kind == "OnlineAuthenticationConfiguration":
                supported = {str(a.CurrentUserType): a.CurrentUserType
                             for a in c.GetSupportedAuthenticationTypes()}
                entry["supported"] = list(supported)
                cred = c.OnlineCredentials
                if user and password:
                    utype = next((supported[k] for k in ("ProjectUser", "GlobalUser", "PasswordOnly")
                                  if k in supported), None)
                    if utype is None:
                        entry["handled"] = False
                        entry["hint"] = "Keine Benutzeranmeldung unterstuetzt."
                    else:
                        cred.Type = utype
                        cred.Name = user
                        cred.SetPassword(_secure(password))
                        entry["handled"] = f"{utype} ({user})"
                elif password and "PasswordOnly" in supported:
                    cred.Type = supported["PasswordOnly"]
                    cred.SetPassword(_secure(password))
                    entry["handled"] = "PasswordOnly"
                elif "AnonymousUser" in supported:
                    cred.Type = supported["AnonymousUser"]
                    entry["handled"] = "AnonymousUser"
                else:
                    entry["handled"] = False
                    entry["hint"] = "Anmeldung erforderlich — user und password angeben."
            elif kind in ("OnlinePasswordConfiguration", "OnlineReadAccessPassword"):
                if password:
                    c.SetPassword(_secure(password))
                    entry["handled"] = "password"
                else:
                    entry["handled"] = False
                    entry["hint"] = "Passwort erforderlich — password angeben."
            elif kind == "TlsVerificationConfiguration":
                entry["plc_name"] = str(c.PlcName)
                entry["verification_info"] = str(c.VerificationInfo)
                if trust_certificate:
                    sel_type = c.CurrentSelection.GetType()
                    import System
                    c.CurrentSelection = System.Enum.Parse(sel_type, "Trusted")
                    entry["handled"] = "Trusted"
                else:
                    entry["handled"] = False
                    entry["hint"] = "SPS-Zertifikat pruefen, dann trust_certificate=true setzen."
            else:
                entry["handled"] = False
        except Exception as e:
            entry["handled"] = False
            entry["error"] = str(e)
        requests.append(entry)
    return _h

def go_online(device_name, mode=None, pc_interface=None, pc_interface_number=None,
              target_interface=None, user=None, password=None, trust_certificate=False):
    """Online gehen. Ohne Parameter wird die im Projekt gespeicherte Verbindung genutzt."""
    def _run():
        _sess.ensure_project()
        op = _online_provider(device_name)
        cfg = op.Configuration

        if mode or pc_interface or target_interface:
            m = next((x for x in cfg.Modes if not mode or str(x.Name) == mode), None)
            if not m:
                raise TiaError("ONLINE_MODE_NOT_FOUND", f"Modus '{mode}' nicht gefunden.", True,
                               {"options": _online_options(cfg)})
            pc = next((x for x in m.PcInterfaces
                       if (not pc_interface or str(x.Name) == pc_interface)
                       and (pc_interface_number is None or int(x.Number) == int(pc_interface_number))), None)
            if not pc:
                raise TiaError("ONLINE_PC_INTERFACE_NOT_FOUND",
                               f"PG/PC-Schnittstelle '{pc_interface}' nicht gefunden.", True,
                               {"options": _online_options(cfg)})
            ti = next((x for x in pc.TargetInterfaces
                       if not target_interface or str(x.Name) == target_interface), None)
            if not ti:
                raise TiaError("ONLINE_TARGET_NOT_FOUND",
                               f"Zielschnittstelle '{target_interface}' nicht gefunden.", True,
                               {"options": _online_options(cfg)})
            cfg.ApplyConfiguration(ti)
        elif not cfg.IsConfigured:
            raise TiaError("ONLINE_NOT_CONFIGURED",
                "Keine Online-Verbindung konfiguriert. mode, pc_interface und target_interface angeben.",
                True, {"options": _online_options(cfg)})

        before = str(op.State)
        requests = []
        handler = _legitimation_handler(requests, user, password, trust_certificate)
        cfg.OnlineLegitimation += handler
        try:
            op.GoOnline()
        except Exception as e:
            open_req = [r for r in requests if not r.get("handled")]
            raise TiaError("ONLINE_FAILED",
                f"GoOnline fehlgeschlagen: {str(e).splitlines()[0]}", True,
                {"state": str(op.State), "legitimation": requests,
                 "hint": open_req[0].get("hint") if open_req else None})
        finally:
            cfg.OnlineLegitimation -= handler
        state = str(op.State)
        _log("online").info(f"go_online {device_name}: {before} → {state} {requests}")
        result = {"status": "ok" if state == "Online" else "error",
                  "device": device_name, "state_before": before, "state": state,
                  "legitimation": requests}
        if state == "Protected":
            result["hint"] = "SPS ist zugriffsgeschuetzt — Legitimation im TIA Portal durchfuehren."
        elif state == "NotReachable":
            result["hint"] = "SPS nicht erreichbar — Schnittstelle/IP pruefen (get_online_state)."
        return result
    return sta.run(_tia_call, _run, timeout=_STA_TIMEOUT_HEAVY)

def go_offline(device_name):
    def _run():
        _sess.ensure_project()
        op = _online_provider(device_name)
        before = str(op.State)
        if before != "Offline":
            op.GoOffline()
        state = str(op.State)
        _log("online").info(f"go_offline {device_name}: {before} → {state}")
        return {"status": "ok" if state == "Offline" else "error",
                "device": device_name, "state_before": before, "state": state}
    return sta.run(_tia_call, _run)