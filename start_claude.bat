@echo off
setlocal

REM ═══════════════════════════════════════════════════════════════
REM  start_claude.bat — TIA Portal MCP fuer Claude Desktop
REM  Startet: TIA Portal (minimiert) → server.py
REM
REM  Hinweis: server.py laeuft als stdio-Server und wartet auf
REM  Verbindung von Claude Desktop. Claude Desktop muss separat
REM  gestartet werden (claude_desktop_config.json konfigurieren).
REM  Normalerweise startet Claude Desktop server.py automatisch —
REM  diese Batch ist fuer den manuellen Test / Fehlersuche.
REM ═══════════════════════════════════════════════════════════════

set PROJECT_DIR=F:\02_Projekte\AI\MCP-Server
set PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe
set TIA_EXE=C:\Program Files\Siemens\Automation\Portal V21\bin\TIA.exe
set TIA_WAIT=35

echo ===============================================================
echo   TIA Portal MCP Server -- Claude Desktop Modus
echo ===============================================================

REM ── 1. TIA Portal starten ───────────────────────────────────────
echo.
echo [1/2] Starte TIA Portal (minimiert)...
start /min "" "%TIA_EXE%"
echo       Warte %TIA_WAIT% Sekunden bis TIA Portal bereit ist...
timeout /t %TIA_WAIT% /nobreak > nul

REM ── 2. server.py starten ────────────────────────────────────────
echo.
echo [2/2] Starte MCP stdio Server...
echo       (Claude Desktop verbindet sich automatisch)
echo.
echo ===============================================================
echo   Server laeuft. Claude Desktop kann jetzt verbinden.
echo   Beenden: Strg+C
echo ===============================================================
echo.

cd /d "%PROJECT_DIR%"
"%PYTHON_EXE%" server.py

endlocal
