@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "CHECK_FAILED=0"

echo ========================================
echo YTB02 AutoEditor - Environment Check
echo ========================================

py -3.12 --version >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('py -3.12 --version 2^>^&1') do echo [OK] %%I
) else (
  python --version >nul 2>&1
  if errorlevel 1 (
    echo [FAIL] Python 3.12 not found
    set "CHECK_FAILED=1"
  ) else (
    for /f "delims=" %%I in ('python --version 2^>^&1') do echo [WARN] %%I - Python 3.12 is recommended
  )
)

where ffmpeg >nul 2>&1 && (echo [OK] ffmpeg) || (echo [FAIL] ffmpeg not found & set "CHECK_FAILED=1")
where ffprobe >nul 2>&1 && (echo [OK] ffprobe) || (echo [FAIL] ffprobe not found & set "CHECK_FAILED=1")

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Content -Raw -LiteralPath 'config.json' | ConvertFrom-Json).kokoro_python"`) do set "KOKORO_PY=%%I"
if exist "%KOKORO_PY%" (
  echo [OK] Kokoro Python: %KOKORO_PY%
  "%KOKORO_PY%" -c "from kokoro import KPipeline" >nul 2>&1 && (echo [OK] English Kokoro import) || (echo [FAIL] English Kokoro import & set "CHECK_FAILED=1")
  "%KOKORO_PY%" -c "from kokoro_vietnamese import KokoroVietnamese" >nul 2>&1 && (echo [OK] Vietnamese Kokoro import) || (echo [FAIL] Vietnamese Kokoro import & set "CHECK_FAILED=1")
) else (
  echo [FAIL] Kokoro Python not found: %KOKORO_PY%
  set "CHECK_FAILED=1"
)

if exist "input\script.json" (echo [OK] input\script.json) else (echo [WARN] input\script.json is missing)
for /f %%I in ('dir /b /a-d "input\videos" 2^>nul ^| find /v /c ""') do set "CLIP_COUNT=%%I"
echo [INFO] Video clips in input\videos: !CLIP_COUNT!

echo ========================================
if "%CHECK_FAILED%"=="0" (echo CHECK COMPLETE - environment is ready) else (echo CHECK COMPLETE - fix the FAIL items above)
echo ========================================
pause
exit /b %CHECK_FAILED%
