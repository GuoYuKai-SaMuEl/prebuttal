@echo off
REM ==========================================================================
REM install-sim.cmd — simulate "pip install prebuttal" exactly the way a PyPI
REM user will experience it: fresh venv in a clean directory OUTSIDE the repo,
REM install from the built wheel, verify entry point + package data, smoke test.
REM
REM Run from any directory:   D:\Prebuttal\scripts\install-sim.cmd
REM (Git Bash:                /d/Prebuttal/scripts/install-sim.cmd)
REM ==========================================================================
setlocal enabledelayedexpansion
set REPO=%~dp0..
for %%I in ("%REPO%") do set REPO=%%~fI
set DIST=%REPO%\dist
set SIM=%TEMP%\prebuttal-pip-sim

echo [1/6] building fresh wheel + sdist ...
if not exist "%REPO%\.venv\Scripts\python.exe" (
  echo   no dev venv found at %REPO%\.venv - create it first.
  goto :fail
)
REM pass the project dir explicitly: users run this from ANY directory
"%REPO%\.venv\Scripts\python.exe" -m build "%REPO%" --outdir "%DIST%" || goto :fail

set WHEEL=
for %%f in ("%DIST%\prebuttal-*-py3-none-any.whl") do set WHEEL=%%f
if "!WHEEL!"=="" (
  echo   no wheel found in %DIST%
  goto :fail
)
echo   built: !WHEEL!

echo [2/6] fresh venv in clean path %SIM% ...
if exist "%SIM%" rmdir /s /q "%SIM%"
mkdir "%SIM%" || goto :fail
REM use the dev venv's interpreter so we never depend on PATH 'python'
"%REPO%\.venv\Scripts\python.exe" -m venv "%SIM%\venv" || goto :fail

echo [3/6] pip install from wheel (this is what PyPI users get) ...
"%SIM%\venv\Scripts\python.exe" -m pip install --quiet "!WHEEL!" || goto :fail

echo [4/6] verifying FROM THE CLEAN DIRECTORY (outside the repo) ...
cd /d "%SIM%"
"%SIM%\venv\Scripts\prebuttal.exe" --version || goto :fail

echo [5/6] package data + entry point check ...
"%SIM%\venv\Scripts\python.exe" -c "import prebuttal, pathlib; p = pathlib.Path(prebuttal.__file__).parent; print('  installed at:', p); from prebuttal.personas import load_persona; from prebuttal.venues import get_venue; assert 'Reviewer 2' in load_persona('adversarial'); assert 'Rating' in get_venue('iclr').form_text(); assert (p / 'py.typed').is_file(); print('  personas / venue forms / py.typed all ship OK')"

echo [6/6] smoke test: dry-run a real arXiv paper (no model calls) ...
"%SIM%\venv\Scripts\prebuttal.exe" run https://arxiv.org/abs/2312.00752 --venue iclr --dry-run || goto :fail

echo.
echo ========================================================================
echo  SUCCESS - that is exactly what "pip install prebuttal" will feel like.
echo  The venv is NOT on PATH yet. Copy-paste one of these:
echo.
echo    [cmd]          %SIM%\venv\Scripts\activate
echo    [PowerShell]   ^& $env:TEMP^\prebuttal-pip-sim\venv\Scripts\Activate.ps1
echo    [any shell]    %SIM%\venv\Scripts\prebuttal.exe --version
echo.
echo  Then, with the venv active (or via the full path above):
echo    prebuttal run your-paper.pdf --venue iclr
echo    (set GEMINI_API_KEY first, or install claude/codex CLI, or use relay)
echo  Future real users will just:  pipx install prebuttal   (PATH handled)
echo ========================================================================
goto :eof

:fail
echo.
echo  FAILED - see the output above.
exit /b 1
