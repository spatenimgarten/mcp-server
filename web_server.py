"""
web_server.py — TIA Portal MCP Server (Streamable HTTP Transport)
Fuer Copilot Studio via Microsoft Dev Tunnel.

Voraussetzungen (einmalig):
  pip install uvicorn starlette
  winget install Microsoft.devtunnel
  devtunnel user login
  devtunnel create tia-mcp --allow-anonymous
  devtunnel port create tia-mcp -p 8000

Start (via start_copilot.bat oder manuell):
  python web_server.py

Dann Tunnel starten:
  devtunnel host tia-mcp

Copilot Studio Agent -> Tools -> Add Tool -> MCP:
  URL: https://tia-mcp-8000.euw.devtunnels.ms/mcp

HINWEIS: server.py (stdio/Claude Desktop) und web_server.py verwenden
denselben TIA STA-Thread — nicht gleichzeitig starten!
"""

import json, sys, os, asyncio, logging
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.routing import Route
import uvicorn

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp import types

import tia
from tia import TiaError, _DEFAULT_EXPORT

# Gemeinsame Tool-Logik und Prompt aus server.py importieren
from server import _PROMPT, _STANDARD_TEMPLATE, _dispatch

# ── Konfiguration ──────────────────────────────────────────────────────────────

PORT = int(os.environ.get("MCP_PORT", 8000))
HOST = "127.0.0.1"   # Nur lokal — Dev Tunnel forwarded von aussen

# ── MCP Server ─────────────────────────────────────────────────────────────────

server = Server("tia-portal-http")

@server.list_prompts()
async def list_prompts():
    return [types.Prompt(name="tia-assistant",
                         description="TIA Portal Openness Assistent V21")]

@server.get_prompt()
async def get_prompt(name, arguments=None):
    return types.GetPromptResult(
        description="TIA Portal Openness Assistent",
        messages=[types.PromptMessage(
            role="user",
            content=types.TextContent(type="text", text=_PROMPT))])

@server.list_tools()
async def list_tools():
    # Tool-Liste identisch mit server.py — zentrale Hilfsfunktion
    def T(name, desc, props=None, req=None):
        schema = {"type": "object", "properties": props or {}}
        if req: schema["required"] = req
        return types.Tool(name=name, description=desc, inputSchema=schema)

    return [
        T("connect_portal",  "TIA Portal verbinden.",
          {"mode": {"type": "string", "enum": ["attach","headless","gui"],
                    "default": "attach"}}),
        T("attach_project",  "Bereits in TIA Portal geoeffnetes Projekt uebernehmen."),
        T("open_project",    "Projekt oeffnen (.ap21).",
          {"path": {"type": "string"}}, ["path"]),
        T("get_session_status", "Verbindungsstatus."),
        T("get_project_info",   "Projektinfo und Geraete."),
        T("list_devices",       "Alle Geraete mit HMI-Typ."),

        # PLC Lesen
        T("list_plc_blocks",
          "Alle Bausteine als JSON: name, number, type, language, path. "
          "group_path optional fuer Unterordner.",
          {"device_name": {"type": "string"},
           "group_path":  {"type": "string"}}, ["device_name"]),
        T("list_plc_tag_tables",
          "PLC Tag-Tabellen mit Namen und Tag-Anzahl.",
          {"device_name": {"type": "string"}}, ["device_name"]),
        T("list_plc_tags",
          "PLC-Tags als JSON: name, data_type, logical_address, comment, table.",
          {"device_name": {"type": "string"},
           "table_name":  {"type": "string"}}, ["device_name"]),

        # PLC Export/Import
        T("compile_plc",
          "SPS kompilieren. Vor Export bei inkonsistenten Bloecken aufrufen.",
          {"device_name": {"type": "string"}}, ["device_name"]),
        T("export_plc_block",
          f"Baustein als XML exportieren. Standard: {_DEFAULT_EXPORT}",
          {"device_name": {"type": "string"}, "block_name": {"type": "string"},
           "output_path": {"type": "string"}}, ["device_name","block_name"]),
        T("import_plc_block",
          "Baustein aus XML importieren.",
          {"device_name": {"type": "string"}, "file_path": {"type": "string"}},
          ["device_name","file_path"]),
        T("get_plc_block_source",
          "Quellcode lesen: SCL direkt, LAD/FBD als XML.",
          {"device_name": {"type": "string"}, "block_name": {"type": "string"},
           "output_path": {"type": "string"}}, ["device_name","block_name"]),
        T("export_plc_tagtable",
          f"PLC Tag-Tabelle als XML exportieren. Standard: {_DEFAULT_EXPORT}",
          {"device_name": {"type": "string"}, "table_name": {"type": "string"},
           "output_path": {"type": "string"}}, ["device_name","table_name"]),
        T("import_plc_tagtable",
          "PLC Tag-Tabelle aus XML importieren.",
          {"device_name": {"type": "string"}, "file_path": {"type": "string"}},
          ["device_name","file_path"]),
        T("save_project", "Projekt speichern. Nach jeder Aenderung aufrufen."),

        # HMI
        T("list_hmi_screens",
          {"device_name": {"type": "string"}}, ["device_name"]),
        T("list_hmi_tags",
          "Tags mit Typ, High/Low-Limit, Archivierung.",
          {"device_name": {"type": "string"}, "table_name": {"type": "string"}},
          ["device_name"]),
        T("list_hmi_alarms",
          {"device_name": {"type": "string"}}, ["device_name"]),
        T("export_hmi_screen",
          {"device_name": {"type": "string"}, "screen_name": {"type": "string"},
           "output_path": {"type": "string"}},
          ["device_name","screen_name","output_path"]),
        T("export_hmi_tags",
          {"device_name": {"type": "string"}, "output_path": {"type": "string"}},
          ["device_name","output_path"]),
        T("export_hmi_tagtable",
          {"device_name": {"type": "string"}, "table_name": {"type": "string"},
           "output_path": {"type": "string"}}, ["device_name","table_name"]),
        T("import_hmi_tagtable",
          {"device_name": {"type": "string"}, "file_path": {"type": "string"}},
          ["device_name","file_path"]),
        T("import_hmi_screen",
          {"device_name": {"type": "string"}, "file_path": {"type": "string"}},
          ["device_name","file_path"]),

        # Bibliothek
        T("list_libraries",     "Alle Bibliotheken im Projekt."),
        T("list_library_types",
          {"library_name": {"type": "string"}}, ["library_name"]),
        T("list_master_copies",
          {"library_name": {"type": "string"}}, ["library_name"]),
        T("get_library_type_versions",
          {"library_name": {"type": "string"}, "type_name": {"type": "string"}},
          ["library_name","type_name"]),

        # Allgemein
        T("execute_openness",
          "Python-Code direkt gegen TIA Openness. mode='read'|'write'",
          {"code": {"type": "string"},
           "mode": {"type": "string", "enum": ["read","write"], "default": "read"}},
          ["code"]),
        T("get_standard_template", "Vorlage fuer Standardprojektstruktur."),
        T("write_import_file",
          "Hochgeladene Datei fuer Import speichern.",
          {"filename": {"type": "string"}, "content": {"type": "string"}},
          ["filename","content"]),
        T("read_export_file",
          "Exportierte Datei lesen und Inhalt zurueckgeben.",
          {"file_path": {"type": "string"}}, ["file_path"]),
    ]

@server.call_tool()
async def call_tool(name, arguments):
    log = logging.getLogger("tia.web_server")
    a = arguments or {}
    log.info(f"Tool: {name}  keys={list(a.keys())}")
    try:
        result = _dispatch(name, a)
        return [types.TextContent(type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2))]
    except TiaError as e:
        log.warning(f"{name} → {e.code}: {e.message}")
        return [types.TextContent(type="text",
                text=json.dumps(e.to_dict(), ensure_ascii=False, indent=2))]
    except Exception as e:
        log.error(f"{name} → {e}", exc_info=True)
        return [types.TextContent(type="text",
                text=json.dumps({"status":"error","code":"UNEXPECTED",
                                 "message":str(e),"tool":name},
                                ensure_ascii=False, indent=2))]

# ── Starlette ASGI App ─────────────────────────────────────────────────────────

def make_app():
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,   # Copilot Studio erwartet JSON (kein SSE-Stream)
        stateless=True,       # Jeder Request ist unabhaengig — besser fuer Tunnel
    )

    async def handle_mcp(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            tia.setup()
            logging.getLogger("tia.web_server").info("TIA Setup abgeschlossen")
            yield
            tia.teardown()
            logging.getLogger("tia.web_server").info("TIA Teardown abgeschlossen")

    return Starlette(
        routes=[Route("/mcp", endpoint=handle_mcp, methods=["GET","POST","DELETE"])],
        lifespan=lifespan,
    )

# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  TIA Portal MCP Server — HTTP / Copilot Studio")
    print("=" * 60)
    print(f"  Lokale URL :  http://{HOST}:{PORT}/mcp")
    print(f"  Tunnel-URL :  devtunnel host tia-mcp  (separates Fenster)")
    print(f"  Beenden    :  Strg+C")
    print("=" * 60)

    uvicorn.run(
        make_app(),
        host=HOST,
        port=PORT,
        log_level="info",
    )
