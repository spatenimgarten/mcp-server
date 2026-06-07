@echo off
setlocal

REM ═══════════════════════════════════════════════════════════════
REM  start_copilot.bat — TIA Portal MCP fuer Copilot Studio
REM  Startet: TIA Portal → web_server.py → Dev Tunnel
REM ═══════════════════════════════════════════════════════════════

set PROJECT_DIR=F:\02_Projekte\AI\MCP-Server
set PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe
set TIA_EXE=C:\Program Files\Siemens\Automation\Portal V21\bin\TIA.exe
set TUNNEL_NAME=tia-mcp
set TIA_WAIT=35

echo ===============================================================
echo   TIA Portal MCP Server -- Copilot Studio Modus
echo ===============================================================

REM ── 1. TIA Portal starten ───────────────────────────────────────
echo.
echo [1/3] Starte TIA Portal...
start "" "%TIA_EXE%"
echo       Warte %TIA_WAIT% Sekunden bis TIA Portal bereit ist...
timeout /t %TIA_WAIT% /nobreak > nul

REM ── 2. web_server.py starten ────────────────────────────────────
echo.
echo [2/3] Starte MCP HTTP Server (Port 8000)...
start "TIA MCP HTTP Server" cmd /k "cd /d %PROJECT_DIR% && %PYTHON_EXE% web_server.py"
echo       Warte 5 Sekunden bis Server bereit ist...
timeout /t 5 /nobreak > nul

REM ── 3. Dev Tunnel starten ───────────────────────────────────────
echo.
echo [3/3] Starte Dev Tunnel '%TUNNEL_NAME%'...
echo       (Tunnel-URL wird im naechsten Fenster angezeigt)
start "Dev Tunnel" cmd /k "devtunnel host %TUNNEL_NAME%"

REM ── Fertig ──────────────────────────────────────────────────────
echo.
echo ===============================================================
echo   Alles gestartet!
echo.
echo   Tunnel-URL: Im Fenster 'Dev Tunnel' nachsehen
echo   Format:     https://%TUNNEL_NAME%-8000.euw.devtunnels.ms/mcp
echo.
echo   Copilot Studio:
echo     Agent oeffnen
echo     Tools - Add Tool - New Tool - Model Context Protocol
echo     URL eintragen (einmalig)
echo.
echo   Beenden: Beide Fenster schliessen + TIA Portal beenden
echo ===============================================================
echo.
pause
endlocal
