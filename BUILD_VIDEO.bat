@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_PYTHON=.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
  echo ERROR: Project virtual environment was not found.
  echo Run SETUP.bat once, then run CHECK.bat.
  goto :failed
)
"%PROJECT_PYTHON%" -c "import whisperx" >nul 2>&1
if errorlevel 1 (
  echo ERROR: WhisperX is not installed in the project environment.
  echo Run SETUP.bat again.
  goto :failed
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo ERROR: ffmpeg was not found in PATH.
  goto :failed
)
where ffprobe >nul 2>&1
if errorlevel 1 (
  echo ERROR: ffprobe was not found in PATH.
  goto :failed
)
if not exist "input\script.json" (
  echo ERROR: input\script.json does not exist.
  echo Copy input\script.example.json to input\script.json, then edit it.
  goto :failed
)
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Content -Raw -LiteralPath 'config.json' | ConvertFrom-Json).kokoro_python"`) do set "KOKORO_PY=%%I"
if not exist "%KOKORO_PY%" (
  echo ERROR: Kokoro Python was not found: %KOKORO_PY%
  echo Update kokoro_python in config.json.
  goto :failed
)

"%PROJECT_PYTHON%" -m src.pipeline --script input\script.json --build
if errorlevel 1 goto :failed

echo.
echo ================================
echo VIDEO BUILD COMPLETE
echo output\FINAL_VIDEO.mp4
echo ================================
pause
exit /b 0

:failed
echo.
echo BUILD FAILED. Read the error above.
pause
exit /b 1
