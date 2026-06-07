"""
tia.py — TIA Portal Openness Anbindung
STA Thread · Fehler · Logging · Session · HMI · Bibliothek · Executor
"""

import os, sys, threading, queue, logging, textwrap
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

@dataclass
class _Job:
    fn: Callable; args: tuple; kwargs: dict; result_q: queue.Queue

class _Err:
    def __init__(self, e): self.exception = e

class STAThread:
    _instance = None; _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance._started = False
        return cls._instance

    def start(self):
        if self._started: return
        self._q: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, name="TIA-STA", daemon=True).start()
        self._started = True
        _log("sta").info("STA Thread gestartet")

    def stop(self):
        if not self._started: return
        self._q.put(None); self._started = False
        _log("sta").info("STA Thread gestoppt")

    def run(self, fn, *args, **kwargs):
        if not self._started: raise RuntimeError("STAThread nicht gestartet")
        rq = queue.Queue()
        self._q.put(_Job(fn, args, kwargs, rq))
        out = rq.get()
        if isinstance(out, _Err): raise out.exception
        return out

    def _loop(self):
        try:
            import pythoncom; pythoncom.CoInitialize()
        except ImportError: pass
        while True:
            job = self._q.get()
            if job is None: break
            try: job.result_q.put(job.fn(*job.args, **job.kwargs))
            except Exception as e:
                _log("sta").error(str(e), exc_info=True)
                job.result_q.put(_Err(e))
        try:
            import pythoncom; pythoncom.CoUninitialize()
        except ImportError: pass

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

    def ensure_portal(self):
        if not self.portal:
            raise TiaError("NOT_CONNECTED","Nicht verbunden. connect_portal aufrufen.",True)

    def ensure_project(self):
        self.ensure_portal()
        if not self.project:
            raise TiaError("NO_PROJECT","Kein Projekt. open_project aufrufen.",True)

_sess = _Session()

def connect_portal(mode="attach"):
    def _run():
        _sess.ensure_dlls()
        from Siemens.Engineering import TiaPortal, TiaPortalMode
        if mode == "attach":
            procs = list(TiaPortal.GetProcesses())
            if not procs: raise TiaError("NO_PORTAL_PROCESS","TIA Portal starten.",True)
            _sess.portal = procs[0].Attach()
            _log("session").info(f"Attached PID={procs[0].Id} V={_sess.tia_version}")
            return {"status":"ok","mode":"attach","tia_version":_sess.tia_version,"process_id":procs[0].Id}
        tm = TiaPortalMode.WithoutUserInterface if mode=="headless" else TiaPortalMode.WithUserInterface
        _sess.portal = TiaPortal(tm)
        _log("session").info(f"Gestartet mode={mode} V={_sess.tia_version}")
        return {"status":"ok","mode":mode,"tia_version":_sess.tia_version}
    return sta.run(_tia_call, _run)

def attach_project():
    """Holt das bereits in TIA Portal geoeffnete Projekt — kein Pfad noetig."""
    def _run():
        _sess.ensure_portal()
        projects = list(_sess.portal.Projects)
        if not projects:
            raise TiaError("NO_PROJECT",
                "Kein Projekt in TIA Portal offen. Bitte zuerst ein Projekt oeffnen.",True)
        _sess.project = projects[0]
        _log("session").info(f"Projekt uebernommen: {_sess.project.Name}")
        return {"status":"ok","project":_sess.project.Name,
                "path":str(_sess.project.Path)}
    return sta.run(_tia_call, _run)

def open_project(path):
    def _run():
        _sess.ensure_portal()
        from System.IO import FileInfo
        fi = FileInfo(path)
        if not fi.Exists: raise TiaError("FILE_NOT_FOUND",f"Nicht gefunden: {path}",True)
        _sess.project = _sess.portal.Projects.Open(fi)
        _log("session").info(f"Projekt: {_sess.project.Name}")
        return {"status":"ok","project":_sess.project.Name,"path":path}
    return sta.run(_tia_call, _run)

def get_session_status():
    ver = None
    for v in _VERSIONS:
        for sub in [f"PublicAPI/{v}/net48", f"PublicAPI/{v}"]:
            p = Path(_TIA_BASE) / f"Portal {v}" / sub
            if (p / "Siemens.Engineering.Base.dll").exists() or                (p / "Siemens.Engineering.dll").exists():
                ver = v; break
        if ver: break
    return {"tia_installed":ver,"portal_connected":_sess.portal is not None,
            "project_open":_sess.project is not None,
            "project_name":_sess.project.Name if _sess.project else None}

def get_project_info():
    def _run():
        _sess.ensure_project(); p = _sess.project
        return {"name":p.Name,"path":str(p.Path),
                "devices":[{"name":d.Name,"type":str(d.TypeIdentifier)} for d in p.Devices]}
    return sta.run(_tia_call, _run)

def list_devices():
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        sw_type = _get_sw_container_type()
        result = []
        for device in _sess.project.Devices:
            sw_list = []
            stack = list(device.DeviceItems)
            while stack:
                item = stack.pop()
                sw = _try_get_software(item, "", sw_type, eng)
                if sw:
                    tn = type(sw).__name__
                    hw = "Unified"  if "Unified" in tn else \
                         "Advanced" if "Hmi"     in tn else \
                         "PLC"      if "Plc"     in tn else tn
                    sw_list.append({"item": item.Name, "type": hw})
                try:
                    for sub in item.DeviceItems: stack.append(sub)
                except Exception: pass
            result.append({"name": device.Name, "software": sw_list})
        return {"devices": result, "count": len(result)}
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# HMI
# ═══════════════════════════════════════════════════════════════════════════════

def _get_hmi(device_name):
    import Siemens.Engineering as eng
    for device in _sess.project.Devices:
        if device.Name != device_name: continue
        for item in device.DeviceItems:
            try:
                swc = item.GetService[eng.SW.SoftwareContainer]()
                if swc:
                    sw = swc.Software; tn = type(sw).__name__
                    if "Unified" in tn: return sw,"Unified"
                    if "Hmi"     in tn: return sw,"Advanced"
            except Exception: pass
    raise TiaError("HMI_NOT_FOUND",f"HMI '{device_name}' nicht gefunden.",True,
                   {"available":[d.Name for d in _sess.project.Devices]})

def list_hmi_screens(device_name):
    def _run():
        _sess.ensure_project(); sw,ht = _get_hmi(device_name)
        screens = [{"name":s.Name,"width":getattr(s,"Width",None),
                    "height":getattr(s,"Height",None),
                    "items":s.ScreenItems.Count if hasattr(s,"ScreenItems") else None}
                   for s in sw.Screens]
        return {"device":device_name,"hmi_type":ht,"screens":screens,"count":len(screens)}
    return sta.run(_tia_call, _run)

def list_hmi_tags(device_name, table_name=None):
    def _run():
        _sess.ensure_project(); sw,ht = _get_hmi(device_name); tags = []
        for table in sw.TagTableGroup.TagTables:
            if table_name and table.Name != table_name: continue
            for tag in table.Tags:
                tags.append({"name":tag.Name,"table":table.Name,
                    "type":str(getattr(tag,"DataTypeName","?")),
                    "high":getattr(tag,"HighLimit",None),
                    "low":getattr(tag,"LowLimit",None),
                    "archive":getattr(tag,"LoggingEnabled",None)})
        return {"device":device_name,"hmi_type":ht,"tags":tags,"count":len(tags)}
    return sta.run(_tia_call, _run)

def list_hmi_alarms(device_name):
    def _run():
        _sess.ensure_project(); sw,ht = _get_hmi(device_name); alarms = []
        for attr,kind in [("DiscreteAlarms","discrete"),("AnalogAlarms","analog"),("Alarms","unified")]:
            if hasattr(sw,attr):
                for a in getattr(sw,attr):
                    alarms.append({"name":a.Name,"type":kind,"class":str(getattr(a,"AlarmClass","?"))})
        return {"device":device_name,"hmi_type":ht,"alarms":alarms,"count":len(alarms)}
    return sta.run(_tia_call, _run)

def list_hmi_textlists(device_name):
    def _run():
        _sess.ensure_project(); sw,ht = _get_hmi(device_name); tls = []
        if hasattr(sw,"TextLists"):
            for tl in sw.TextLists:
                entries = [{"value":getattr(e,"Value",None),"text":str(getattr(e,"Text",""))}
                           for e in (tl.TextListEntries if hasattr(tl,"TextListEntries") else [])]
                tls.append({"name":tl.Name,"entries":entries})
        return {"device":device_name,"hmi_type":ht,"textlists":tls,"count":len(tls)}
    return sta.run(_tia_call, _run)

def export_hmi_screen(device_name, screen_name, output_path):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng; from System.IO import FileInfo
        sw,ht = _get_hmi(device_name)
        for s in sw.Screens:
            if s.Name == screen_name:
                s.Export(FileInfo(output_path), eng.ExportOptions.WithDefaults)
                return {"status":"ok","device":device_name,"screen":screen_name,"output":output_path}
        raise TiaError("SCREEN_NOT_FOUND",f"Screen '{screen_name}' nicht gefunden.",True,
                       {"available":[s.Name for s in sw.Screens]})
    return sta.run(_tia_call, _run)

def export_hmi_tags(device_name, output_path):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng; from System.IO import FileInfo
        sw,ht = _get_hmi(device_name)
        sw.TagTableGroup.Export(FileInfo(output_path), eng.ExportOptions.WithDefaults)
        return {"status":"ok","device":device_name,"output":output_path}
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# BIBLIOTHEK
# ═══════════════════════════════════════════════════════════════════════════════

def _find_lib(name):
    p = _sess.project
    if p.ProjectLibrary.Name == name: return p.ProjectLibrary,"project"
    for gl in p.GlobalLibraries:
        if gl.Name == name: return gl,"global"
    raise TiaError("LIBRARY_NOT_FOUND",f"Bibliothek '{name}' nicht gefunden.",True,
                   {"available":[p.ProjectLibrary.Name]+[gl.Name for gl in p.GlobalLibraries]})

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
        libs = [{"name":pl.Name,"scope":"project",
                 "types":pl.TypeFolder.Types.Count,"copies":pl.MasterCopyFolder.MasterCopies.Count}]
        for gl in p.GlobalLibraries:
            libs.append({"name":gl.Name,"scope":"global","path":str(gl.Path),
                         "types":gl.TypeFolder.Types.Count,"copies":gl.MasterCopyFolder.MasterCopies.Count})
        return {"libraries":libs,"count":len(libs)}
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
_BLOCKED_ALWAYS = ["exec","eval","open","os.","sys.","subprocess","shutil","__import__","builtins"]
_SAFE_BUILTINS  = {
    "len":len,"str":str,"int":int,"float":float,"bool":bool,"list":list,"dict":dict,
    "tuple":tuple,"set":set,"print":print,"range":range,"enumerate":enumerate,
    "zip":zip,"map":map,"filter":filter,"sorted":sorted,"hasattr":hasattr,
    "getattr":getattr,"isinstance":isinstance,"type":type,
    "None":None,"True":True,"False":False,
}

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

    for device in project.Devices:
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
        _sess.ensure_portal()
        import Siemens.Engineering as eng
        import Siemens.Engineering.SW as eng_sw
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
            "find_software": lambda n,h="": _find_sw(_sess.project,n,h,eng),
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
        block.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)

        # XML lesen
        xml_content = xml_file.read_text(encoding="utf-8")
        block_type  = type(block).__name__
        language    = getattr(block, "ProgrammingLanguage", None)
        lang_str    = str(language) if language else "Unknown"

        # SCL-Quellcode extrahieren
        scl_source  = None
        scl_file    = None
        if "SCL" in lang_str.upper() or "StructuredControlLanguage" in lang_str:
            scl_source = _extract_scl(xml_content)
            if scl_source:
                scl_file = out_dir / f"{block_name}.scl"
                scl_file.write_text(scl_source, encoding="utf-8")

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
    """SCL-Quellcode aus TIA-XML extrahieren."""
    import re
    # TIA Portal speichert SCL in <StructuredText> oder <Body>
    for tag in ["StructuredText", "Body", "SourceText"]:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml_content, re.DOTALL)
        if m:
            src = m.group(1).strip()
            # CDATA entfernen falls vorhanden
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
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        for table in sw.TagTableGroup.TagTables:
            if table.Name == table_name:
                out_dir  = _export_dir(output_path)
                xml_file = out_dir / f"hmi_tags_{table_name}.xml"
                table.Export(FileInfo(str(xml_file)), eng.ExportOptions.WithDefaults)
                return {"status": "ok", "device": device_name, "hmi_type": ht,
                        "table": table_name, "xml_path": str(xml_file)}
        raise TiaError("TABLE_NOT_FOUND", f"HMI Tag-Tabelle '{table_name}' nicht gefunden.", True)
    return sta.run(_tia_call, _run)

def import_hmi_tagtable(device_name, file_path):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        fi = FileInfo(file_path)
        if not fi.Exists:
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        sw.TagTableGroup.Import(fi, eng.ImportOptions.Override)
        return {"status": "ok", "device": device_name, "imported_from": file_path}
    return sta.run(_tia_call, _run)

def import_hmi_screen(device_name, file_path):
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        from System.IO import FileInfo
        sw, ht = _get_hmi(device_name)
        fi = FileInfo(file_path)
        if not fi.Exists:
            raise TiaError("FILE_NOT_FOUND", f"Datei nicht gefunden: {file_path}", True)
        sw.Screens.Import(fi, eng.ImportOptions.Override)
        return {"status": "ok", "device": device_name, "imported_from": file_path}
    return sta.run(_tia_call, _run)

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

def compile_plc(device_name):
    """SPS kompilieren — behebt inkonsistente Bausteine vor dem Export."""
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng
        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # ICompilable per Reflection — funktioniert zuverlässig in V21
        compilable_type = plc.GetType().Assembly.GetType(
            "Siemens.Engineering.Compiler.ICompilable")
        if not compilable_type:
            raise TiaError("COMPILE_NOT_SUPPORTED",
                "ICompilable nicht gefunden — TIA Version pruefen.", False)

        compiler = plc.GetService[compilable_type]()
        if not compiler:
            raise TiaError("COMPILE_NOT_SUPPORTED",
                "Kein Compiler-Service verfuegbar.", False)

        result = compiler.Compile()
        status = "ok" if result.ErrorCount == 0 else "error"
        _log("compile").info(
            f"Kompiliert {device_name}: {result.ErrorCount} Fehler, {result.WarningCount} Warnungen")

        messages = []
        try:
            for msg in result.Messages:
                messages.append({
                    "severity": str(msg.Severity),
                    "description": str(msg.Description),
                    "path": str(getattr(msg, "Path", ""))
                })
        except Exception: pass

        return {
            "status":   status,
            "device":   device_name,
            "errors":   result.ErrorCount,
            "warnings": result.WarningCount,
            "messages": messages[:20]   # max 20 Meldungen
        }
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# PLC LESEN — Bausteine, Tag-Tabellen, Tags
# ═══════════════════════════════════════════════════════════════════════════════

def list_plc_blocks(device_name, group_path=None):
    """
    Alle Bausteine der PLC als JSON — ohne Export, direkt aus dem Objektmodell.

    group_path: optional, z.B. "Antriebe" oder "Antriebe/Pumpen".
                Leer = alle Gruppen rekursiv.

    Rueckgabe je Baustein: name, number, type (OB/FC/FB/DB/UDT), language, path
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # Startgruppe ermitteln — optional auf Unterordner einschraenken
        start_group = plc.BlockGroup
        if group_path:
            for part in group_path.strip("/").split("/"):
                found = None
                for sub in start_group.Groups:
                    if sub.Name == part:
                        found = sub
                        break
                if not found:
                    avail = [g.Name for g in start_group.Groups]
                    raise TiaError("GROUP_NOT_FOUND",
                        f"Gruppe '{part}' in '{group_path}' nicht gefunden.", True,
                        {"available": avail})
                start_group = found

        # Klassenname → lesbarer Typ
        type_map = {
            "DataBlock":          "DB",
            "PlcType":            "UDT",
            "PlcTypeComposition": "UDT",
        }

        blocks = []
        stack  = [(start_group, group_path or "")]
        while stack:
            group, path = stack.pop()
            for block in group.Blocks:
                raw_type   = type(block).__name__
                block_type = type_map.get(raw_type, raw_type)
                language   = getattr(block, "ProgrammingLanguage", None)
                blocks.append({
                    "name":     block.Name,
                    "number":   getattr(block, "Number", None),
                    "type":     block_type,
                    "language": str(language) if language is not None else None,
                    "path":     path,
                })
            for sub in group.Groups:
                sub_path = f"{path}/{sub.Name}".lstrip("/")
                stack.append((sub, sub_path))

        _log("plc").info(f"list_plc_blocks {device_name}: {len(blocks)} Bausteine")
        return {
            "status":       "ok",
            "device":       device_name,
            "group_filter": group_path,
            "blocks":       blocks,
            "count":        len(blocks),
        }
    return sta.run(_tia_call, _run)


def list_plc_tag_tables(device_name):
    """
    Alle PLC Tag-Tabellen mit Name und Tag-Anzahl.
    Vorstufe zu list_plc_tags / export_plc_tagtable.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        tables = []
        stack  = [(plc.TagTableGroup, "")]
        while stack:
            group, path = stack.pop()
            for table in group.TagTables:
                try:    tag_count = table.Tags.Count
                except: tag_count = None
                tables.append({
                    "name":      table.Name,
                    "path":      path,
                    "tag_count": tag_count,
                })
            try:
                for sub in group.Groups:
                    stack.append((sub, f"{path}/{sub.Name}".lstrip("/")))
            except Exception:
                pass

        _log("plc").info(f"list_plc_tag_tables {device_name}: {len(tables)} Tabellen")
        return {"status": "ok", "device": device_name, "tables": tables, "count": len(tables)}
    return sta.run(_tia_call, _run)


def list_plc_tags(device_name, table_name=None):
    """
    PLC-Tags direkt als JSON — ohne XML-Export.

    table_name: optional. Leer = alle Tabellen.

    Rueckgabe je Tag: name, data_type, logical_address, comment, table
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # Alle Tabellennamen vorab sammeln (fuer Fehlerfall)
        all_table_names = []
        tags = []

        stack = [(plc.TagTableGroup, "")]
        while stack:
            group, path = stack.pop()
            for table in group.TagTables:
                all_table_names.append(table.Name)
                if table_name and table.Name != table_name:
                    continue
                for tag in table.Tags:
                    # Kommentar: MultilingualText — erste Sprache lesen
                    comment = None
                    try:
                        ml = tag.Comment
                        if ml and ml.Items.Count > 0:
                            comment = str(ml.Items[0].Text)
                    except Exception:
                        pass
                    tags.append({
                        "name":            tag.Name,
                        "data_type":       str(getattr(tag, "DataTypeName", "?")),
                        "logical_address": str(getattr(tag, "LogicalAddress", "") or ""),
                        "comment":         comment,
                        "table":           table.Name,
                    })
            try:
                for sub in group.Groups:
                    stack.append((sub, f"{path}/{sub.Name}".lstrip("/")))
            except Exception:
                pass

        if table_name and table_name not in all_table_names:
            raise TiaError("TABLE_NOT_FOUND",
                f"Tag-Tabelle '{table_name}' nicht gefunden.", True,
                {"available": all_table_names})

        _log("plc").info(
            f"list_plc_tags {device_name}"
            f"{f'/{table_name}' if table_name else ''}: {len(tags)} Tags")
        return {
            "status":       "ok",
            "device":       device_name,
            "table_filter": table_name,
            "tags":         tags,
            "count":        len(tags),
        }
    return sta.run(_tia_call, _run)


# ═══════════════════════════════════════════════════════════════════════════════
# PROJEKT SPEICHERN
# ═══════════════════════════════════════════════════════════════════════════════

def save_project():
    """Aktuelles Projekt speichern — explizit statt per execute_openness."""
    def _run():
        _sess.ensure_project()
        name = _sess.project.Name
        path = str(_sess.project.Path)
        _sess.project.Save()
        _log("session").info(f"Projekt gespeichert: {name}")
        return {"status": "ok", "project": name, "path": path}
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# BIBLIOTHEK — Öffnen, Suchen
# ═══════════════════════════════════════════════════════════════════════════════

def find_libraries(folder):
    """
    Durchsucht einen Ordner nach globalen TIA-Bibliotheken (.al*).
    Gibt Name, Pfad und erkannte TIA-Version zurück.
    Hilfreich um die richtige Bibliotheksdatei für die aktuelle TIA-Version zu finden.
    """
    import re
    p = Path(folder)
    if not p.exists():
        raise TiaError("FOLDER_NOT_FOUND", f"Ordner nicht gefunden: {folder}", True)

    result = []
    # .al18 / .al19 / .al20 / .al21 usw.
    for f in sorted(p.glob("*.al*")):
        m = re.search(r"\.al(\d+)$", f.suffix, re.IGNORECASE)
        if m:
            ver = f"V{m.group(1)}"
            result.append({
                "name":    f.stem,
                "path":    str(f),
                "version": ver,
                "match":   ver == _sess.tia_version,  # passt zur laufenden TIA-Version
            })

    _log("library").info(f"find_libraries {folder}: {len(result)} Bibliotheken")
    return {
        "status":        "ok",
        "folder":        folder,
        "tia_version":   _sess.tia_version,
        "libraries":     result,
        "count":         len(result),
    }


def open_library(path_or_folder, name_hint=None):
    """
    Öffnet eine globale TIA-Bibliothek.

    path_or_folder:
        Vollständiger Dateipfad (.al21 etc.) — wird direkt geöffnet.
        Oder Ordnerpfad — sucht automatisch die Datei die zur
        laufenden TIA-Version passt. name_hint hilft bei mehreren Treffer.

    name_hint: optionaler Teilname z.B. "Antriebe" um bei mehreren
               Bibliotheken im Ordner die richtige zu wählen.
    """
    def _run():
        _sess.ensure_portal()
        from System.IO import FileInfo
        import re

        p = Path(path_or_folder)

        # Vollständiger Dateipfad — direkt öffnen
        if p.is_file():
            target = p
        else:
            # Ordner — passende Version suchen
            if not p.is_dir():
                raise TiaError("PATH_NOT_FOUND",
                    f"Pfad nicht gefunden: {path_or_folder}", True)

            ver_num = _sess.tia_version.lstrip("V") if _sess.tia_version else ""
            pattern = f"*.al{ver_num}" if ver_num else "*.al*"
            candidates = list(p.glob(pattern))

            if not candidates:
                # Fallback: alle .al* Dateien
                candidates = [f for f in p.glob("*.al*")
                              if re.search(r"\.al\d+$", f.suffix, re.IGNORECASE)]

            if name_hint:
                candidates = [f for f in candidates
                              if name_hint.lower() in f.stem.lower()]

            if not candidates:
                raise TiaError("LIBRARY_NOT_FOUND",
                    f"Keine passende Bibliothek in {path_or_folder} "
                    f"für TIA {_sess.tia_version} gefunden.", True,
                    {"searched": pattern, "hint": name_hint})

            if len(candidates) > 1:
                raise TiaError("LIBRARY_AMBIGUOUS",
                    f"Mehrere Bibliotheken gefunden — name_hint angeben.",
                    True, {"found": [str(c) for c in candidates]})

            target = candidates[0]

        # Prüfen ob bereits geöffnet
        for gl in _sess.portal.GlobalLibraries:
            if Path(str(gl.Path)) == target:
                _log("library").info(f"Bibliothek bereits offen: {target.name}")
                return {"status": "ok", "name": gl.Name,
                        "path": str(target), "already_open": True}

        lib = _sess.portal.GlobalLibraries.Open(FileInfo(str(target)))
        _log("library").info(f"Bibliothek geöffnet: {target.name}")
        return {
            "status":       "ok",
            "name":         lib.Name,
            "path":         str(target),
            "already_open": False,
            "types":        lib.TypeFolder.Types.Count,
            "copies":       lib.MasterCopyFolder.MasterCopies.Count,
        }
    return sta.run(_tia_call, _run)


# ═══════════════════════════════════════════════════════════════════════════════
# UDTs lesen
# ═══════════════════════════════════════════════════════════════════════════════

def list_plc_udts(device_name):
    """
    Alle UDTs (PlcType) der PLC als JSON mit vollständiger Memberstruktur.
    Felder je Member: name, data_type, default_value, comment, offset
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        udts = []
        stack = [(plc.BlockGroup, "")]
        while stack:
            group, path = stack.pop()
            for block in group.Blocks:
                # PlcType = UDT, PlcTypeComposition = strukturierter UDT
                raw = type(block).__name__
                if "PlcType" not in raw:
                    continue

                members = []
                try:
                    for m in block.Interface.Members:
                        comment = None
                        try:
                            ml = m.Comment
                            if ml and ml.Items.Count > 0:
                                comment = str(ml.Items[0].Text)
                        except Exception:
                            pass
                        members.append({
                            "name":          m.Name,
                            "data_type":     str(getattr(m, "Datatype", "?")),
                            "default_value": str(getattr(m, "StartValue", "") or ""),
                            "comment":       comment,
                            "offset":        str(getattr(m, "Offset", "") or ""),
                        })
                except Exception as e:
                    members = [{"error": str(e)}]

                udts.append({
                    "name":    block.Name,
                    "number":  getattr(block, "Number", None),
                    "path":    path,
                    "members": members,
                    "member_count": len(members),
                })

            for sub in group.Groups:
                stack.append((sub, f"{path}/{sub.Name}".lstrip("/")))

        _log("plc").info(f"list_plc_udts {device_name}: {len(udts)} UDTs")
        return {
            "status": "ok",
            "device": device_name,
            "udts":   udts,
            "count":  len(udts),
        }
    return sta.run(_tia_call, _run)


# ═══════════════════════════════════════════════════════════════════════════════
# Bibliothekstyp in PLC instanziieren
# ═══════════════════════════════════════════════════════════════════════════════

def use_library_type(device_name, library_name, type_name, group_path=None):
    """
    Instanziiert einen Bibliothekstyp (UDT, FB, FC) im PLC.
    Verwendet die Standardversion des Typs.

    group_path: optionaler Zielordner im PLC, z.B. "Antriebe".
                Leer = BlockGroup (Wurzel).
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # Zielgruppe ermitteln
        target_group = plc.BlockGroup
        if group_path:
            for part in group_path.strip("/").split("/"):
                found = None
                for sub in target_group.Groups:
                    if sub.Name == part:
                        found = sub
                        break
                if not found:
                    # Gruppe anlegen wenn nicht vorhanden
                    found = target_group.Groups.Create(part)
                    _log("plc").info(f"Gruppe angelegt: {part}")
                target_group = found

        # Bibliothek suchen (Projekt + global)
        lib, scope = _find_lib(library_name)

        # Typ suchen
        types_list = []
        _collect_types(lib.TypeFolder, types_list)
        match = next((t for t in types_list if t["name"] == type_name), None)
        if not match:
            raise TiaError("TYPE_NOT_FOUND",
                f"Typ '{type_name}' in Bibliothek '{library_name}' nicht gefunden.", True,
                {"available": [t["name"] for t in types_list]})

        # Typ-Objekt aus Bibliothek holen und Standardversion instanziieren
        def _find_type_obj(folder):
            for t in folder.Types:
                if t.Name == type_name:
                    return t
            for sub in folder.Folders:
                r = _find_type_obj(sub)
                if r: return r
            return None

        type_obj = _find_type_obj(lib.TypeFolder)
        if not type_obj:
            raise TiaError("TYPE_NOT_FOUND",
                f"Typ '{type_name}' nicht gefunden.", True)

        version = type_obj.DefaultVersion
        if not version:
            raise TiaError("NO_DEFAULT_VERSION",
                f"Typ '{type_name}' hat keine Standardversion.", True)

        # In Zielgruppe instanziieren
        target_group.Blocks.CreateFrom(version)
        _log("plc").info(
            f"Typ '{type_name}' v{match['default_version']} "
            f"aus '{library_name}' in '{device_name}/{group_path or ''}' instanziiert")

        return {
            "status":   "ok",
            "device":   device_name,
            "library":  library_name,
            "type":     type_name,
            "version":  match["default_version"],
            "group":    group_path or "(root)",
        }
    return sta.run(_tia_call, _run)


# ═══════════════════════════════════════════════════════════════════════════════
# PLC-Tags anlegen / schreiben
# ═══════════════════════════════════════════════════════════════════════════════

def create_plc_tag(device_name, table_name, tag_name,
                   data_type, address=None, comment=None):
    """
    Einzelnen PLC-Tag anlegen.
    table_name: Tabelle muss existieren (vorher list_plc_tag_tables prüfen).
    data_type:  z.B. "Bool", "Int", "Real", "DWord", "UDT_Antrieb"
    address:    z.B. "%M0.0", "%MW10" — optional
    comment:    optional
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # Tabelle suchen
        table = None
        stack = [(plc.TagTableGroup, "")]
        while stack:
            group, _ = stack.pop()
            for t in group.TagTables:
                if t.Name == table_name:
                    table = t
                    break
            if table:
                break
            try:
                for sub in group.Groups:
                    stack.append((sub, ""))
            except Exception:
                pass

        if not table:
            raise TiaError("TABLE_NOT_FOUND",
                f"Tag-Tabelle '{table_name}' nicht gefunden.", True)

        tag = table.Tags.Create(tag_name, data_type)

        if address:
            tag.LogicalAddress = address

        if comment:
            try:
                tag.Comment.Items[0].Text = comment
            except Exception:
                pass

        _log("plc").info(f"PLC-Tag angelegt: {table_name}.{tag_name} ({data_type})")
        return {
            "status":    "ok",
            "device":    device_name,
            "table":     table_name,
            "tag":       tag_name,
            "data_type": data_type,
            "address":   address,
            "comment":   comment,
        }
    return sta.run(_tia_call, _run)


def create_plc_tag_table(device_name, table_name):
    """
    Neue PLC Tag-Tabelle anlegen.
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        table = plc.TagTableGroup.TagTables.Create(table_name)
        _log("plc").info(f"Tag-Tabelle angelegt: {table_name}")
        return {"status": "ok", "device": device_name, "table": table_name}
    return sta.run(_tia_call, _run)


# ═══════════════════════════════════════════════════════════════════════════════
# HMI-Tags anlegen / schreiben
# ═══════════════════════════════════════════════════════════════════════════════

def create_hmi_tag(device_name, table_name, tag_name, data_type,
                   plc_tag=None, high_limit=None, low_limit=None,
                   logging_enabled=False, comment=None):
    """
    Einzelnen HMI-Tag anlegen.
    table_name:      Tabelle muss existieren.
    data_type:       z.B. "Int", "Real", "Bool"
    plc_tag:         Verknüpfung mit PLC-Tag, z.B. "PLC_1.DB1.Motor1_Drehzahl"
    high_limit:      oberer Grenzwert (für analoge Tags)
    low_limit:       unterer Grenzwert
    logging_enabled: Archivierung ein/aus
    comment:         optional
    """
    def _run():
        _sess.ensure_project()

        sw, ht = _get_hmi(device_name)

        # Tabelle suchen
        table = None
        for t in sw.TagTableGroup.TagTables:
            if t.Name == table_name:
                table = t
                break

        if not table:
            raise TiaError("TABLE_NOT_FOUND",
                f"HMI Tag-Tabelle '{table_name}' nicht gefunden.", True,
                {"available": [t.Name for t in sw.TagTableGroup.TagTables]})

        tag = table.Tags.Create(tag_name, data_type)

        if plc_tag:
            try:
                tag.PlcTag = plc_tag
            except Exception:
                pass

        if high_limit is not None:
            try:
                tag.HighLimit = high_limit
            except Exception:
                pass

        if low_limit is not None:
            try:
                tag.LowLimit = low_limit
            except Exception:
                pass

        try:
            tag.LoggingEnabled = logging_enabled
        except Exception:
            pass

        if comment:
            try:
                tag.Comment = comment
            except Exception:
                pass

        _log("hmi").info(
            f"HMI-Tag angelegt: {device_name}/{table_name}.{tag_name} ({data_type})")
        return {
            "status":           "ok",
            "device":           device_name,
            "hmi_type":         ht,
            "table":            table_name,
            "tag":              tag_name,
            "data_type":        data_type,
            "plc_tag":          plc_tag,
            "high_limit":       high_limit,
            "low_limit":        low_limit,
            "logging_enabled":  logging_enabled,
        }
    return sta.run(_tia_call, _run)


def create_hmi_tag_table(device_name, table_name):
    """
    Neue HMI Tag-Tabelle anlegen.
    """
    def _run():
        _sess.ensure_project()
        sw, ht = _get_hmi(device_name)
        sw.TagTableGroup.TagTables.Create(table_name)
        _log("hmi").info(f"HMI Tag-Tabelle angelegt: {device_name}/{table_name}")
        return {"status": "ok", "device": device_name,
                "hmi_type": ht, "table": table_name}
    return sta.run(_tia_call, _run)

# ═══════════════════════════════════════════════════════════════════════════════
# QUERVERWEISE & UNGENUTZTE TAGS
# ═══════════════════════════════════════════════════════════════════════════════

def get_cross_references(device_name, symbol):
    """
    Alle Verwendungsstellen eines Symbols (Tag, Baustein, DB-Variable) in der PLC.

    symbol: z.B. "Motor1_Start", "FB_Antrieb", "DB1", "UDT_Antrieb"

    Rückgabe je Treffer:
        block, block_type, language, usage (Read/Write/ReadWrite/Call), location
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        refs = []
        try:
            xref_data = plc.CrossReferenceData
            # Alle Querverweise durchsuchen
            for item in xref_data:
                try:
                    # Symbol-Name prüfen
                    sym = str(getattr(item, "Symbol", "") or "")
                    name = str(getattr(item, "Name", "") or "")
                    if symbol.lower() not in sym.lower() and \
                       symbol.lower() not in name.lower():
                        continue

                    refs.append({
                        "block":      str(getattr(item, "BlockName",    "") or ""),
                        "block_type": str(getattr(item, "BlockType",    "") or ""),
                        "language":   str(getattr(item, "Language",     "") or ""),
                        "usage":      str(getattr(item, "UseType",      "") or ""),
                        "location":   str(getattr(item, "Location",     "") or ""),
                        "symbol":     sym or name,
                    })
                except Exception:
                    pass
        except Exception as e:
            # Fallback: CrossReferenceData nicht verfügbar
            raise TiaError("XREF_NOT_AVAILABLE",
                f"Querverweise nicht verfügbar: {e}", False,
                {"hint": "TIA Portal muss kompiliert sein"})

        _log("plc").info(
            f"get_cross_references {device_name}/{symbol}: {len(refs)} Treffer")
        return {
            "status":  "ok",
            "device":  device_name,
            "symbol":  symbol,
            "refs":    refs,
            "count":   len(refs),
        }
    return sta.run(_tia_call, _run)


def find_unused_plc_tags(device_name):
    """
    Findet alle PLC-Tags die in keinem Baustein verwendet werden.
    Nutzt CrossReferenceData — PLC muss kompiliert sein.

    Rückgabe je ungenutztem Tag:
        name, data_type, logical_address, table
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # Alle verwendeten Symbolnamen aus CrossReferenceData sammeln
        used_symbols = set()
        try:
            for item in plc.CrossReferenceData:
                try:
                    sym = str(getattr(item, "Symbol", "") or "")
                    if sym:
                        used_symbols.add(sym.lower())
                except Exception:
                    pass
        except Exception as e:
            raise TiaError("XREF_NOT_AVAILABLE",
                f"Querverweise nicht verfügbar: {e}", False,
                {"hint": "Erst compile_plc aufrufen"})

        # Alle Tags durchgehen und mit used_symbols vergleichen
        unused = []
        stack = [(plc.TagTableGroup, "")]
        while stack:
            group, _ = stack.pop()
            for table in group.TagTables:
                for tag in table.Tags:
                    if tag.Name.lower() not in used_symbols:
                        unused.append({
                            "name":            tag.Name,
                            "data_type":       str(getattr(tag, "DataTypeName", "?")),
                            "logical_address": str(getattr(tag, "LogicalAddress", "") or ""),
                            "table":           table.Name,
                        })
            try:
                for sub in group.Groups:
                    stack.append((sub, ""))
            except Exception:
                pass

        _log("plc").info(
            f"find_unused_plc_tags {device_name}: {len(unused)} ungenutzte Tags")
        return {
            "status":  "ok",
            "device":  device_name,
            "unused":  unused,
            "count":   len(unused),
            "hint":    "Bitte Liste prüfen bevor delete_plc_tag aufgerufen wird.",
        }
    return sta.run(_tia_call, _run)


def find_unused_hmi_tags(device_name):
    """
    Findet alle HMI-Tags die in keinem Screen verwendet werden.
    Gibt Name, Datentyp und Tabelle zurück.

    Hinweis: HMI-Querverweise sind über CrossReferenceData des HMI-Objekts
    verfügbar — Verfügbarkeit hängt vom HMI-Typ ab.
    """
    def _run():
        _sess.ensure_project()
        sw, ht = _get_hmi(device_name)

        # Verwendete Tags aus HMI-CrossReferenceData
        used_symbols = set()
        try:
            for item in sw.CrossReferenceData:
                try:
                    sym = str(getattr(item, "Symbol", "") or "")
                    name = str(getattr(item, "Name",   "") or "")
                    s = sym or name
                    if s:
                        used_symbols.add(s.lower())
                except Exception:
                    pass
        except Exception:
            # Fallback: CrossReferenceData nicht verfügbar beim HMI-Typ
            # In diesem Fall alle Tags als "potenziell ungenutzt" melden
            _log("hmi").warning(
                f"HMI CrossReferenceData nicht verfügbar für {device_name} "
                f"({ht}) — alle Tags werden gelistet")

        unused = []
        for table in sw.TagTableGroup.TagTables:
            for tag in table.Tags:
                if not used_symbols or tag.Name.lower() not in used_symbols:
                    unused.append({
                        "name":      tag.Name,
                        "data_type": str(getattr(tag, "DataTypeName", "?")),
                        "table":     table.Name,
                        "verified":  bool(used_symbols),  # False = CrossRef nicht verfügbar
                    })

        _log("hmi").info(
            f"find_unused_hmi_tags {device_name}: {len(unused)} Tags")
        return {
            "status":   "ok",
            "device":   device_name,
            "hmi_type": ht,
            "unused":   unused,
            "count":    len(unused),
            "verified": bool(used_symbols),
            "hint":     "verified=false bedeutet CrossReferenceData nicht verfügbar "
                        "— manuelle Prüfung empfohlen vor dem Löschen.",
        }
    return sta.run(_tia_call, _run)


# ═══════════════════════════════════════════════════════════════════════════════
# TAGS LÖSCHEN
# ═══════════════════════════════════════════════════════════════════════════════

def delete_plc_tag(device_name, table_name, tag_name):
    """
    Einzelnen PLC-Tag löschen.
    Vorher find_unused_plc_tags aufrufen und Liste prüfen!
    """
    def _run():
        _sess.ensure_project()
        import Siemens.Engineering as eng

        plc = _find_sw(_sess.project, device_name, "PlcSoftware", eng)
        if not plc:
            raise TiaError("PLC_NOT_FOUND", f"PLC '{device_name}' nicht gefunden.", True)

        # Tabelle und Tag suchen
        stack = [(plc.TagTableGroup, "")]
        while stack:
            group, _ = stack.pop()
            for table in group.TagTables:
                if table.Name == table_name:
                    for tag in table.Tags:
                        if tag.Name == tag_name:
                            tag.Delete()
                            _log("plc").info(
                                f"PLC-Tag gelöscht: {table_name}.{tag_name}")
                            return {
                                "status": "ok",
                                "device": device_name,
                                "table":  table_name,
                                "tag":    tag_name,
                            }
                    raise TiaError("TAG_NOT_FOUND",
                        f"Tag '{tag_name}' in Tabelle '{table_name}' nicht gefunden.",
                        True)
            try:
                for sub in group.Groups:
                    stack.append((sub, ""))
            except Exception:
                pass

        raise TiaError("TABLE_NOT_FOUND",
            f"Tag-Tabelle '{table_name}' nicht gefunden.", True)
    return sta.run(_tia_call, _run)


def delete_hmi_tag(device_name, table_name, tag_name):
    """
    Einzelnen HMI-Tag löschen.
    Vorher find_unused_hmi_tags aufrufen und Liste prüfen!
    """
    def _run():
        _sess.ensure_project()
        sw, ht = _get_hmi(device_name)

        for table in sw.TagTableGroup.TagTables:
            if table.Name == table_name:
                for tag in table.Tags:
                    if tag.Name == tag_name:
                        tag.Delete()
                        _log("hmi").info(
                            f"HMI-Tag gelöscht: {device_name}/{table_name}.{tag_name}")
                        return {
                            "status":   "ok",
                            "device":   device_name,
                            "hmi_type": ht,
                            "table":    table_name,
                            "tag":      tag_name,
                        }
                raise TiaError("TAG_NOT_FOUND",
                    f"Tag '{tag_name}' in Tabelle '{table_name}' nicht gefunden.",
                    True)

        raise TiaError("TABLE_NOT_FOUND",
            f"HMI Tag-Tabelle '{table_name}' nicht gefunden.", True)
    return sta.run(_tia_call, _run)
