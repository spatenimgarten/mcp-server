"""
worker.py — führt die TIA-Openness-Aufrufe in einem eigenen Prozess aus.

Wird von server.py gestartet. Protokoll: eine JSON-Zeile pro Auftrag auf stdin
({"tool": ..., "args": {...}}), eine JSON-Zeile pro Antwort auf stdout
({"ok": true, "result": ...} oder {"ok": false, "error": {...}}).

Warum ein eigener Prozess: Nach dem ersten Openness-Zugriff bleibt im Prozess etwas bei
TIA angemeldet, das weder Dispose noch das Abmelden der Event-Handler löst. TIA hängt
dann z.B. beim Schließen des Projekts, bis der Prozess endet. Der Server beendet deshalb
beim Trennen / nach Leerlauf / nach Timeout diesen Worker statt sich selbst.
"""
import json
import os
import sys

# stdout ist für das Protokoll reserviert — alle anderen Ausgaben nach stderr
_proto_out = sys.stdout
sys.stdout = sys.stderr

# Leerlauf-Trennung übernimmt der Server (beendet den Worker); intern nicht doppelt trennen
os.environ["TIA_MCP_IDLE_DISCONNECT"] = "0"

import tia                      # noqa: E402
from tia import TiaError        # noqa: E402
import server                   # noqa: E402  (_dispatch; beim Import wird nichts gestartet)


def main():
    tia.setup()
    tia._log("worker").info(f"Worker gestartet (PID {os.getpid()})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            result = server._dispatch(req["tool"], req.get("args") or {})
            out = {"ok": True, "result": result}
        except TiaError as e:
            out = {"ok": False, "error": e.to_dict()}
        except Exception as e:
            tia._log("worker").error(f"{e}", exc_info=True)
            out = {"ok": False, "error": {"status": "error", "code": "UNEXPECTED", "message": str(e)}}
        # Antwort als reines ASCII (Sonderzeichen als \uXXXX): stdout ist eine Pipe, und Python
        # schreibt dort unter Windows mit cp1252. Ein Zeichen ausserhalb von cp1252 (z.B. griechisches
        # mu oder Pfeile in Variablennamen/Texten) liess das Schreiben scheitern; der Worker hing dann,
        # bis der Server ihn nach dem Timeout beendete.
        try:
            data = json.dumps(out, ensure_ascii=True, default=str)
            _proto_out.write(data + "\n")
            _proto_out.flush()
            if len(data) > 100000:
                tia._log("worker").info(f"Antwort gesendet ({len(data) // 1024} KB)")
        except Exception as e:
            tia._log("worker").error(f"Antwort konnte nicht gesendet werden: {e}", exc_info=True)
            os._exit(1)             # sicher beenden - sonst haelt die .NET-Laufzeit den Prozess am Leben
    tia._log("worker").info("Worker beendet (stdin geschlossen)")
    tia.teardown()
    os._exit(0)                     # .NET-Vordergrund-Threads duerfen das Prozessende nicht verhindern


if __name__ == "__main__":
    main()
