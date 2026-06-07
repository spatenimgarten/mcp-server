@echo off
setlocal

REM ═══════════════════════════════════════════════════════════════
REM  start_bridge.bat — TIA Portal MCP fuer Ollama (bridge.py)
REM  Startet: TIA Portal (minimiert) → bridge.py
REM
REM  Voraussetzungen:
REM    pip install ollama
REM    ollama pull qwen2.5:14b   (oder gewuenschtes Modell)
REM    Modell in bridge.py unter MODEL einstellen
REM ═══════════════════════════════════════════════════════════════

set PROJECT_DIR=F:\02_Projekte\AI\MCP-Server
set PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe
set TIA_EXE=C:\Program Files\Siemens\Automation\Portal V21\bin\TIA.exe
set TIA_WAIT=35

echo ===============================================================
echo   TIA Portal MCP Server -- Ollama Bridge Modus
echo ===============================================================

REM ── 1. TIA Portal starten ───────────────────────────────────────
echo.
echo [1/2] Starte TIA Portal (minimiert)...
start /min "" "%TIA_EXE%"
echo       Warte %TIA_WAIT% Sekunden bis TIA Portal bereit ist...
timeout /t %TIA_WAIT% /nobreak > nul

REM ── 2. bridge.py starten ────────────────────────────────────────
echo.
echo [2/2] Starte Ollama Bridge...
echo.
echo ===============================================================
echo   Bridge laeuft. Eingabe nach der Aufforderung "Du: "
echo   Beenden: "exit" eingeben oder Fenster schliessen
echo ===============================================================
echo.

cd /d "%PROJECT_DIR%"
"%PYTHON_EXE%" bridge.py

endlocal
