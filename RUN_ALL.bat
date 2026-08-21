@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PROJECT_PYTHON=.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
  echo ERROR: Project virtual environment was not found. Run SETUP.bat.
  goto :failed
)
if not exist "input\script.json" (
  echo ERROR: input\script.json does not exist.
  goto :failed
)
"%PROJECT_PYTHON%" -m src.pipeline --script input\script.json --run-all
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
echo RUN ALL FAILED. Read the error above.
pause
exit /b 1
