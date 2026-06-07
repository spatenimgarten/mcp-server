@echo off
setlocal

REM ═══════════════════════════════════════════════════════════════
REM  start_webui.bat — TIA Portal MCP fuer OpenWebUI + Ollama
REM  Startet: TIA Portal → web_server.py → OpenWebUI
REM
REM  Voraussetzungen (einmalig):
REM    .venv\Scripts\activate
REM    pip install open-webui
REM    ollama pull qwen2.5-coder:14b
REM
REM  OpenWebUI einrichten (einmalig im Browser):
REM    http://localhost:3000
REM    Admin Settings → External Tools → Add Server
REM    Type: MCP (Streamable HTTP)
REM    URL:  http://localhost:8000/mcp
REM ═══════════════════════════════════════════════════════════════

set PROJECT_DIR=F:\02_Projekte\AI\MCP-Server
set PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe
set TIA_EXE=C:\Program Files\Siemens\Automation\Portal V21\bin\TIA.exe
set TIA_WAIT=35

echo ===============================================================
echo   TIA Portal MCP Server -- OpenWebUI Modus
echo ===============================================================

REM ── 1. TIA Portal starten ───────────────────────────────────────
echo.
echo [1/3] Starte TIA Portal (minimiert)...
start /min "" "%TIA_EXE%"
echo       Warte %TIA_WAIT% Sekunden bis TIA Portal bereit ist...
timeout /t %TIA_WAIT% /nobreak > nul

REM ── 2. web_server.py starten ────────────────────────────────────
echo.
echo [2/3] Starte MCP HTTP Server (Port 8000)...
start "TIA MCP HTTP Server" cmd /k "cd /d %PROJECT_DIR% && %PYTHON_EXE% web_server.py"
echo       Warte 5 Sekunden bis Server bereit ist...
timeout /t 5 /nobreak > nul

REM ── 3. OpenWebUI starten ────────────────────────────────────────
echo.
echo [3/3] Starte OpenWebUI (Port 3000)...
start "OpenWebUI" cmd /k "cd /d %PROJECT_DIR% && %PYTHON_EXE% -m open_webui serve"

REM ── Fertig ──────────────────────────────────────────────────────
echo.
echo ===============================================================
echo   Alles gestartet!
echo.
echo   OpenWebUI:  http://localhost:3000
echo               (kurz warten bis OpenWebUI vollstaendig geladen)
echo.
echo   MCP Server: http://localhost:8000/mcp
echo               (einmalig in OpenWebUI unter
echo                Admin Settings - External Tools eintragen)
echo.
echo   Beenden: Beide Fenster schliessen + TIA Portal beenden
echo ===============================================================
echo.
pause
endlocal
