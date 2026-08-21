@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo YTB02 AutoEditor - One-time Setup
echo ========================================

py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.12 was not found.
  echo Install Python 3.12, then run SETUP.bat again.
  goto :failed
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating project virtual environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failed
) else (
  echo Reusing existing .venv.
)

echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo Installing CPU-only PyTorch...
".venv\Scripts\python.exe" -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :failed

echo Installing project, WhisperX, Pillow and official Google GenAI dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo Verifying installed dependencies...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto :failed

echo Verifying WhisperX runtime imports without loading alignment models...
".venv\Scripts\python.exe" -c "import whisperx; import torch; import torchaudio; import PIL; from google import genai; print('WhisperX, Pillow and Google GenAI OK')"
if errorlevel 1 goto :failed

echo.
echo ========================================
echo SETUP COMPLETE
echo Run CHECK.bat next.
echo Alignment models download on first build.
echo ========================================
pause
exit /b 0

:failed
echo.
echo SETUP FAILED. Read the error above.
pause
exit /b 1
