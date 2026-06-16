@echo off
setlocal
cd /d %~dp0
if "%~1"=="" (
    echo Usage: commit.bat "Commit message"
    exit /b 1
)
git add tia.py server.py README.md TESTING.md
git commit -m "%~1 Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push
endlocal
