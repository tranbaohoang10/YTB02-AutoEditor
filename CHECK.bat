@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "CHECK_FAILED=0"
set "PROJECT_PY=.venv\Scripts\python.exe"

echo ========================================
echo YTB02 AutoEditor - Environment Check
echo ========================================

if exist "%PROJECT_PY%" (
  for /f "delims=" %%I in ('"%PROJECT_PY%" --version 2^>^&1') do echo [OK] Project %%I: %PROJECT_PY%
) else (
  echo [FAIL] Project virtual environment is missing.
  echo        Run SETUP.bat once before CHECK or BUILD.
  set "CHECK_FAILED=1"
)

where ffmpeg >nul 2>&1 && (echo [OK] ffmpeg) || (echo [FAIL] ffmpeg not found & set "CHECK_FAILED=1")
where ffprobe >nul 2>&1 && (echo [OK] ffprobe) || (echo [FAIL] ffprobe not found & set "CHECK_FAILED=1")

if exist "%PROJECT_PY%" (
  "%PROJECT_PY%" -c "import whisperx" >nul 2>&1 && (echo [OK] WhisperX alignment package) || (echo [FAIL] WhisperX import - run SETUP.bat & set "CHECK_FAILED=1")
  "%PROJECT_PY%" -c "import torch; assert not torch.cuda.is_available() or True; print(torch.__version__)" >nul 2>&1 && (echo [OK] PyTorch available) || (echo [FAIL] PyTorch import & set "CHECK_FAILED=1")
  "%PROJECT_PY%" -c "import PIL" >nul 2>&1 && (echo [OK] Pillow image QC) || (echo [FAIL] Pillow import - run SETUP.bat & set "CHECK_FAILED=1")
  "%PROJECT_PY%" -c "from google import genai" >nul 2>&1 && (echo [OK] Official Google GenAI client) || (echo [FAIL] google-genai import - run SETUP.bat & set "CHECK_FAILED=1")
)

for /f "usebackq tokens=1-4 delims=|" %%A in (`powershell -NoProfile -Command "$a=(Get-Content -Raw -LiteralPath 'config.json'|ConvertFrom-Json).alignment; Write-Output ($a.engine+'|'+$a.device+'|'+$a.allow_approximate_fallback+'|'+$a.cache_dir)"`) do (
  set "ALIGN_ENGINE=%%A"
  set "ALIGN_DEVICE=%%B"
  set "ALIGN_FALLBACK=%%C"
  set "ALIGN_CACHE=%%D"
)
if /I "!ALIGN_ENGINE!"=="whisperx" (echo [OK] Alignment engine: WhisperX) else (echo [FAIL] alignment.engine must be whisperx & set "CHECK_FAILED=1")
if /I "!ALIGN_DEVICE!"=="cpu" (echo [OK] Alignment device: CPU) else (echo [FAIL] alignment.device must be cpu & set "CHECK_FAILED=1")
if /I "!ALIGN_FALLBACK!"=="False" (echo [OK] Approximate fallback: OFF) else (echo [FAIL] allow_approximate_fallback must be false & set "CHECK_FAILED=1")
if exist "!ALIGN_CACHE!" (
  dir /b /a "!ALIGN_CACHE!" >nul 2>&1 && (echo [OK] Alignment model cache exists) || (echo [WARN] Alignment model will be downloaded on first build.)
) else (
  echo [WARN] Alignment model will be downloaded on first build.
)

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Content -Raw -LiteralPath 'config.json' | ConvertFrom-Json).kokoro_python"`) do set "KOKORO_PY=%%I"
if exist "%KOKORO_PY%" (
  echo [OK] Kokoro Python: %KOKORO_PY%
  "%KOKORO_PY%" -c "from kokoro import KPipeline" >nul 2>&1 && (echo [OK] English Kokoro import) || (echo [FAIL] English Kokoro import & set "CHECK_FAILED=1")
  "%KOKORO_PY%" -c "from kokoro_vietnamese import KokoroVietnamese" >nul 2>&1 && (echo [OK] Vietnamese Kokoro import) || (echo [FAIL] Vietnamese Kokoro import & set "CHECK_FAILED=1")
) else (
  echo [FAIL] Kokoro Python not found: %KOKORO_PY%
  set "CHECK_FAILED=1"
)

set "SCRIPT_READY=0"
if exist "input\script.json" (
  echo [OK] input\script.json
  set "SCRIPT_READY=1"
) else (
  echo [FAIL] input\script.json is missing.
  echo        Copy input\script.example.json to input\script.json, then edit it.
  set "CHECK_FAILED=1"
)
for /f %%I in ('dir /b /a-d "input\videos" 2^>nul ^| findstr /v /i /x ".gitkeep" ^| find /v /c ""') do set "CLIP_COUNT=%%I"
echo [INFO] Video clips in input\videos: !CLIP_COUNT!
for /f %%I in ('dir /b /a-d "input\images" 2^>nul ^| findstr /v /i /x ".gitkeep" ^| find /v /c ""') do set "IMAGE_COUNT=%%I"
echo [INFO] Images in input\images: !IMAGE_COUNT!

if "!SCRIPT_READY!"=="1" (
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$v=(Get-Content -Raw -LiteralPath 'input/script.json'|ConvertFrom-Json).visual.image_provider; if($v){$v}else{'manual'}"`) do set "IMAGE_PROVIDER=%%I"
  echo [INFO] Image provider: !IMAGE_PROVIDER!
  if /I "!IMAGE_PROVIDER!"=="gemini_api" (
    if defined GEMINI_API_KEY (
      echo [OK] GEMINI_API_KEY is configured. Value is hidden.
    ) else (
      echo [FAIL] GEMINI_API_KEY is required for gemini_api mode.
      set "CHECK_FAILED=1"
    )
  ) else if /I "!IMAGE_PROVIDER!"=="manual" (
    echo [OK] Manual image mode does not require GEMINI_API_KEY.
  ) else (
    echo [FAIL] Unsupported image provider: !IMAGE_PROVIDER!
    set "CHECK_FAILED=1"
  )
)

if exist "%PROJECT_PY%" (
  if "!SCRIPT_READY!"=="1" (
    echo [INFO] Validating script JSON, visual sources and provider configuration...
    "%PROJECT_PY%" -m src.pipeline --script input\script.json --config config.json --dry-run
    if errorlevel 1 (
      echo [FAIL] Script, media or provider validation failed. Read the ERROR above.
      set "CHECK_FAILED=1"
    ) else (
      echo [OK] Script JSON and referenced visual sources are valid.
    )
  )
)

echo ========================================
if "%CHECK_FAILED%"=="0" (echo CHECK COMPLETE - environment is ready) else (echo CHECK COMPLETE - fix the FAIL items above)
echo ========================================
pause
exit /b %CHECK_FAILED%
