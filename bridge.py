"""
bridge.py — Ollama <-> TIA Portal MCP Bridge

Verbindet Ollama (lokales LLM) mit dem TIA Portal MCP Server.
Startet server.py automatisch als Unterprozess.

Voraussetzungen:
  pip install ollama
  ollama pull qwen2.5:14b

Start:
  python bridge.py

Oder per Batch-Datei:
  start_tia_bridge.bat
"""

import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import ollama

# ── Konfiguration ──────────────────────────────────────────────────────────────

MODEL      = "qwen2.5:14b"                           # Modell: 7b / 14b / 32b
SERVER_PY  = r"F:\MCP-Server\server.py"              # Pfad zu server.py
PYTHON_EXE = r"F:\MCP-Server\.venv\Scripts\python.exe"  # venv Python
CWD        = r"F:\MCP-Server"                        # Arbeitsverzeichnis

# System Prompt direkt aus server.py — eine einzige Quelle fuer beide Clients
from server import _PROMPT
SYSTEM_PROMPT = _PROMPT

# Optional: projektspezifische Ergaenzungen anfuegen
# SYSTEM_PROMPT += """
#
# # Mein Projekt
# - PLC heisst: PLC_1
# - HMI heisst: HMI_1
# """

# ── MCP Tools -> Ollama Format konvertieren ────────────────────────────────────

def mcp_tools_to_ollama(mcp_tools):
    """Konvertiert MCP Tool-Liste ins Ollama Function-Calling Format."""
    result = []
    for tool in mcp_tools.tools:
        schema = tool.inputSchema or {"type": "object", "properties": {}}
        result.append({
            "type": "function",
            "function": {
                "name":        tool.name,
                "description": tool.description or "",
                "parameters":  schema,
            }
        })
    return result

# ── Tool-Call ausfuehren ───────────────────────────────────────────────────────

async def call_mcp_tool(session: ClientSession, name: str, arguments: dict):
    """Ruft ein MCP-Tool auf und gibt das Ergebnis als String zurueck."""
    try:
        result = await session.call_tool(name, arguments)
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
        return "\n".join(parts) if parts else "(kein Ergebnis)"
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

# ── Haupt-Chat-Loop ────────────────────────────────────────────────────────────

async def chat_loop(session: ClientSession, tools_raw):
    tools    = mcp_tools_to_ollama(tools_raw)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    client   = ollama.AsyncClient()

    print(f"\n  TIA Bridge bereit — Modell: {MODEL}")
    print(f"  {len(tools)} Tools geladen")
    print("  'exit' zum Beenden\n")

    while True:
        try:
            user_input = input("Du: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBeendet.")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            print("Auf Wiedersehen!")
            break

        messages.append({"role": "user", "content": user_input})

        # ── Agentic Loop: Ollama -> Tool-Call -> Ollama ... ───────────────────
        while True:
            response = await client.chat(
                model=MODEL,
                messages=messages,
                tools=tools,
                options={"temperature": 0.1},   # niedrig = zuverlaessigere Tool-Calls
            )

            assistant_msg = response.message
            messages.append(assistant_msg)

            # Kein Tool-Call -> fertig, Antwort ausgeben
            if not assistant_msg.tool_calls:
                print(f"\nAssistent: {assistant_msg.content}\n")
                break

            # Tool-Calls abarbeiten
            for tc in assistant_msg.tool_calls:
                fn   = tc.function
                name = fn.name
                args = fn.arguments if isinstance(fn.arguments, dict) \
                       else json.loads(fn.arguments or "{}")

                print(f"  🔧  {name}({json.dumps(args, ensure_ascii=False)})")

                tool_result = await call_mcp_tool(session, name, args)

                messages.append({
                    "role":    "tool",
                    "content": tool_result,
                    "name":    name,
                })

                # Kurze Vorschau des Ergebnisses
                preview = tool_result[:120].replace("\n", " ")
                print(f"  ↩  {preview}{'...' if len(tool_result) > 120 else ''}")

            # Naechste Iteration: Ollama wertet Tool-Ergebnis aus

# ── Entry Point ────────────────────────────────────────────────────────────────

async def main():
    server_params = StdioServerParameters(
        command=PYTHON_EXE,
        args=[SERVER_PY],
        cwd=CWD,
        env=None,
    )

    print(f"Starte MCP-Server: {SERVER_PY}")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"MCP-Server verbunden, {len(tools.tools)} Tools gefunden.")
            await chat_loop(session, tools)

if __name__ == "__main__":
    asyncio.run(main())
