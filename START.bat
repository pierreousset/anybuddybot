@echo off
REM ===========================================================================
REM  AnyBuddy Sniper - DEMARRAGE (Windows)
REM  Double-clique ce fichier. C'est tout.
REM ===========================================================================
cd /d "%~dp0"

REM Trouve Python (py launcher ou python dans le PATH)
where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")

if not exist .venv (
  echo Installation en cours... patiente ~2 minutes.
  %PY% -m venv .venv
  if errorlevel 1 (
    echo.
    echo Python 3 est requis. Installe-le depuis https://www.python.org/downloads/
    echo  ^(coche "Add Python to PATH" pendant l'installation^), puis relance.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\pip.exe" install -q -r requirements.txt
  ".venv\Scripts\python.exe" -m playwright install chromium
)

".venv\Scripts\python.exe" -m anybuddy.launcher
echo.
echo Termine. Tu peux fermer cette fenetre.
pause
